'use strict';

// P2c-5 桌面端核对（规格 §7 第 5 批 ②）：在**真实 Electron 渲染进程**下核对三件事——
//   ① `fetch` + 读流的**增量**流式读是否可用（脚本自带本地 SSE 服务器造两段带间隔的数据，
//      第二段到达时间明显晚于第一段 ⇒ 证明不是整体缓冲后一次吐出）；
//   ② 页面是否设置 CSP（meta 与导航响应头）、被测请求的响应是否带 CSP（全部在页面内取证）；
//   ③ 桌面端加载的网页端能否连到后端（会话列表 + SSE 读端点，使用与本机 dev 后端一致的身份头）。
//
// 用法（本机需已具备 Electron 运行时；本脚本**不参与** `node --test`，也不改任何应用行为）：
//   cd desktop
//   npx electron scripts/desktop-stream-check.cjs
//   # 可选：$env:WORKBENCH_DESKTOP_URL="http://localhost:5173/" 指定要核对的网页端地址
//   # 可选：$env:WORKBENCH_CHECK_API_BASE="http://127.0.0.1:8010/api/v1" 指定后端基地址
//
// 输出：JSON 结果 + 结论行；流式读判据不满足时以非 0 退出码结束。
//
// 实现注记：**不使用 `webRequest.onHeadersReceived`** —— Electron 44.3.0 实测对默认会话注册该
// 监听会让 `file://` 页面加载失败（`ERR_FAILED -2`）或直接挂起；CSP 取证改为在页面内读
// `fetch` 响应头（等价证据，且不影响任何加载路径）。

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { app, BrowserWindow } = require('electron');

const { resolveAppUrl, resolveWindowOptions } = require('../src/config.cjs');

const API_BASE = process.env.WORKBENCH_CHECK_API_BASE || 'http://127.0.0.1:8010/api/v1';
const DEV_HEADERS = {
  Accept: 'application/json',
  'Content-Type': 'application/json',
  'X-Tenant-Id': 'demo-tenant',
  'X-User-Id': 'admin',
  'X-User-Role': 'super_admin',
};
// 两段 SSE 数据的间隔：明显大于网络往返，便于区分「增量读」与「整体缓冲」。
const SSE_GAP_MS = 300;

/** 本地 SSE 服务器：两段数据 + 中间间隔，并放开 CORS（供 file:// 源核对）。 */
function startSseServer() {
  return new Promise((resolve) => {
    const server = http.createServer((request, response) => {
      if (request.url !== '/sse') {
        response.writeHead(404);
        response.end();
        return;
      }
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Access-Control-Allow-Origin': '*',
      });
      response.write('id: 1\nevent: tool.call\ndata: {"seq":1,"kind":"tool.call","payload":{},"is_terminal":false}\n\n');
      setTimeout(() => {
        response.write('id: 2\nevent: run.completed\ndata: {"seq":2,"kind":"run.completed","payload":{},"is_terminal":true}\n\n');
        response.end();
      }, SSE_GAP_MS);
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

/** 渲染进程内执行的核对脚本（必须自包含：不得引用外部变量）。 */
async function pageCheck(params) {
  const started = performance.now();
  const out = { url: location.href, cspMeta: null, navCsp: null, stream: null, backendList: null, backendStream: null };

  const meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
  out.cspMeta = meta ? meta.getAttribute('content') : null;

  // 导航响应头里的 CSP（file:// 源取不到时如实记为错误文本）。
  try {
    const nav = await fetch(location.href, { cache: 'no-store' });
    out.navCsp = nav.headers.get('content-security-policy');
  } catch (error) {
    out.navCsp = `取不到（${String(error)}）`;
  }

  try {
    const response = await fetch(params.sseUrl, { headers: { Accept: 'text/event-stream' }, cache: 'no-store' });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const chunks = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push({ atMs: Math.round(performance.now() - started), text: decoder.decode(value, { stream: true }) });
    }
    out.stream = {
      status: response.status,
      contentType: response.headers.get('content-type'),
      csp: response.headers.get('content-security-policy'),
      chunks,
    };
  } catch (error) {
    out.stream = { error: String(error) };
  }

  try {
    const response = await fetch(`${params.apiBase}/conversations?limit=1&offset=0`, { headers: params.headers });
    out.backendList = { status: response.status, ok: response.ok, conversationId: null, csp: response.headers.get('content-security-policy') };
    if (response.ok) {
      const body = await response.json();
      out.backendList.conversationId = body && body.items && body.items[0] ? body.items[0].conversation_id : null;
    }
  } catch (error) {
    out.backendList = { error: String(error) };
  }

  if (out.backendList && out.backendList.conversationId) {
    try {
      const response = await fetch(
        `${params.apiBase}/conversations/${encodeURIComponent(out.backendList.conversationId)}/stream`,
        { headers: { ...params.headers, Accept: 'text/event-stream' } },
      );
      const info = {
        status: response.status,
        contentType: response.headers.get('content-type'),
        runHeader: response.headers.get('X-Stream-Run-Id'),
        firstChunk: null,
        timedOut: false,
      };
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const first = await Promise.race([
        reader.read(),
        new Promise((resolve) => setTimeout(() => resolve({ timeout: true }), 2500)),
      ]);
      if (first && first.timeout) info.timedOut = true;
      else if (first && !first.done) info.firstChunk = decoder.decode(first.value);
      reader.cancel().catch(() => {});
      out.backendStream = info;
    } catch (error) {
      out.backendStream = { error: String(error) };
    }
  }

  return out;
}

async function checkTarget(label, appUrl, params) {
  const window_ = new BrowserWindow(resolveWindowOptions(path.join(__dirname, '..', 'src', 'preload.cjs')));
  const record = { label, appUrl, result: null, error: null };
  try {
    await window_.loadURL(appUrl);
    record.result = await window_.webContents.executeJavaScript(`(${pageCheck.toString()})(${JSON.stringify(params)})`, true);
  } catch (error) {
    record.error = String(error);
  } finally {
    window_.destroy();
  }
  return record;
}

/** 流式读判据：至少两段，且第二段到达时间晚于第一段不少于半个间隔（证明是增量而非整体缓冲）。 */
function streamVerdict(record) {
  const stream = record.result && record.result.stream;
  if (!stream || stream.error || !Array.isArray(stream.chunks)) {
    return { ok: false, reason: stream && stream.error ? stream.error : '没有读到数据' };
  }
  if (stream.chunks.length < 2) return { ok: false, reason: `只读到 ${stream.chunks.length} 段（预期 2 段）` };
  const [first, second] = stream.chunks;
  const gap = second.atMs - first.atMs;
  if (gap < SSE_GAP_MS / 2) return { ok: false, reason: `两段间隔 ${gap}ms 过短，疑似整体缓冲` };
  return { ok: true, reason: `两段增量到达（间隔 ${gap}ms），终态帧文本完整：${second.text.includes('run.completed')}` };
}

async function main() {
  const sseServer = await startSseServer();
  const ssePort = sseServer.address().port;
  const params = { sseUrl: `http://127.0.0.1:${ssePort}/sse`, apiBase: API_BASE, headers: DEV_HEADERS };

  const bundledIndexPath = path.join(__dirname, '..', 'web', 'index.html');
  const bundledExists = fs.existsSync(bundledIndexPath);
  const records = [];

  // ① 远程模式（未设置 WORKBENCH_DESKTOP_URL 时的默认开发地址）。
  records.push(await checkTarget('远程模式（网页端地址）', resolveAppUrl(process.env, { bundledIndexPath: null, fileExists: () => false }), params));

  // ② 内置模式（file://）：仅在 desktop/web 产物存在时核对（`npm run copy:web` 生成）。
  if (bundledExists) {
    records.push(await checkTarget('内置模式（file:// 产物）', resolveAppUrl({}, { bundledIndexPath, fileExists: fs.existsSync }), params));
  }

  const verdicts = records.map((record) => ({ label: record.label, verdict: streamVerdict(record) }));
  const report = {
    checkedAt: new Date().toISOString(),
    runtime: { electron: process.versions.electron, chrome: process.versions.chrome, node: process.versions.node },
    apiBase: API_BASE,
    sseGapMs: SSE_GAP_MS,
    bundledProduct: bundledExists ? bundledIndexPath : null,
    records,
    verdicts,
  };
  console.log(JSON.stringify(report, null, 2));

  for (const verdict of verdicts) {
    console.log(`${verdict.verdict.ok ? 'OK  ' : 'FAIL'} ${verdict.label}：${verdict.verdict.reason}`);
  }
  for (const record of records) {
    const result = record.result;
    if (!result) continue;
    const backendCsp = result.backendList
      ? result.backendList.csp ?? (result.backendList.error ? '（请求失败）' : '无')
      : '未取到';
    console.log(
      `CSP（${record.label}）：meta=${result.cspMeta ?? '无'}；导航响应头=${result.navCsp ?? '无'}；` +
        `本地 SSE=${result.stream && !result.stream.error ? result.stream.csp ?? '无' : '未取到'}；` +
        `后端列表=${backendCsp}`,
    );
  }

  sseServer.close();
  const allOk = verdicts.length > 0 && verdicts.every((item) => item.verdict.ok);
  app.exit(allOk ? 0 : 1);
}

// 串行核对多个窗口：关掉前一个窗口后**不退出应用**（否则后续窗口加载会失败）。
app.on('window-all-closed', () => {});

app.whenReady().then(() => {
  main().catch((error) => {
    console.error(JSON.stringify({ fatal: String(error) }));
    app.exit(2);
  });
});