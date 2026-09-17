import type { StreamFrame } from '../conversation/types'

/**
 * 内容级回传的两个面板（P2c-2 事项 I；契约「内容级回传」）。
 *
 * 纪律（§1.3 / §2.5）：
 * - **只渲染白名单字段**（`output_excerpt` / `output_truncated` / `output_bytes` / `output_sha256` /
 *   `file_changes[].{virtual_path, change_kind, bytes, sha256, diff_excerpt}`），未知键一律不猜测；
 * - **截断必须显式告知**（`output_truncated` / `output_bytes`）；二进制只给字节数与摘要（不落内容）；
 * - **无数据不摆假面板**（面板按批次出现：本批出终端；`file_changes` 随 P2c-3 的 `fs.*` 落地才有数据）。
 */

interface TerminalEntry {
  seq: number
  toolKey: string
  excerpt: string | null
  truncated: boolean
  bytes: number | null
  sha256: string | null
}

const asString = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

function terminalEntries(frames: StreamFrame[]): TerminalEntry[] {
  const entries: TerminalEntry[] = []
  for (const frame of frames) {
    if (frame.kind !== 'tool.result') continue
    const payload = frame.payload
    const hasOutput =
      asString(payload.output_excerpt) !== null ||
      typeof payload.output_truncated === 'boolean' ||
      asNumber(payload.output_bytes) !== null
    if (!hasOutput) continue
    entries.push({
      seq: frame.seq,
      toolKey: asString(payload.tool_key) ?? '工具',
      excerpt: asString(payload.output_excerpt),
      truncated: payload.output_truncated === true,
      bytes: asNumber(payload.output_bytes),
      sha256: asString(payload.output_sha256),
    })
  }
  return entries
}

/** 终端输出面板：展示**最近一次**带输出的工具结果（有界摘录 + 截断告知）。 */
export function TerminalOutputPanel({ frames }: { frames: StreamFrame[] }) {
  const entries = terminalEntries(frames)
  if (entries.length === 0) return null
  const latest = entries[entries.length - 1]
  return (
    <section className="history-panel stage-panel" aria-label="终端输出">
      <div className="panel-header">
        <h2>终端输出</h2>
        <span>
          {latest.toolKey}
          {latest.truncated ? ' · 已截断' : ''}
        </span>
      </div>
      <div className="panel-body">
        {latest.excerpt !== null ? (
          <pre className="terminal-output" aria-label="执行输出摘录">
            {latest.excerpt}
          </pre>
        ) : (
          <p className="stage-hint">非文本输出不落内容：只记录字节数与摘要。</p>
        )}
        <p className="stage-hint">
          {latest.truncated
            ? `输出超过回传上限，已截断（已读取 ${latest.bytes ?? 0} 字节；完整内容不进入回传通道）。`
            : `本次回传 ${latest.bytes ?? 0} 字节（有界摘录）。`}
          {latest.sha256 ? ` 摘要 ${latest.sha256.slice(0, 19)}…` : ''}
          {entries.length > 1 ? ` 另有 ${entries.length - 1} 条更早的输出。` : ''}
        </p>
      </div>
    </section>
  )
}

interface FileChangeEntry {
  seq: number
  virtualPath: string
  changeKind: string | null
  bytes: number | null
  sha256: string | null
  diffExcerpt: string | null
}

const CHANGE_KIND_LABELS: Record<string, string> = {
  create: '新建',
  write: '写入',
  overwrite: '覆盖',
  delete: '删除',
  modify: '修改',
}

function fileChangeEntries(frames: StreamFrame[]): FileChangeEntry[] {
  const entries: FileChangeEntry[] = []
  for (const frame of frames) {
    const changes = frame.payload.file_changes
    if (!Array.isArray(changes)) continue
    for (const item of changes) {
      if (typeof item !== 'object' || item === null) continue
      const change = item as Record<string, unknown>
      const virtualPath = asString(change.virtual_path)
      if (!virtualPath) continue // 虚拟路径是唯一必填键；缺失即整条丢弃（不猜测）
      entries.push({
        seq: frame.seq,
        virtualPath,
        changeKind: asString(change.change_kind),
        bytes: asNumber(change.bytes),
        sha256: asString(change.sha256),
        diffExcerpt: asString(change.diff_excerpt),
      })
    }
  }
  return entries
}

/** 文件改动面板：虚拟路径 + 变更类型 + 字节 + 有界 diff 摘录（数据随 P2c-3 的 `fs.*` 落地）。 */
export function FileDiffPanel({ frames }: { frames: StreamFrame[] }) {
  const changes = fileChangeEntries(frames)
  if (changes.length === 0) return null
  return (
    <section className="history-panel stage-panel" aria-label="文件改动">
      <div className="panel-header">
        <h2>文件改动</h2>
        <span>{changes.length} 项</span>
      </div>
      <div className="panel-body">
        <ul className="file-changes">
          {changes.map((change) => (
            <li className="file-change" key={`${change.seq}:${change.virtualPath}`}>
              <div className="file-change__line">
                <span className="file-change__path">{change.virtualPath}</span>
                {change.changeKind && (
                  <span className="file-change__kind">
                    {CHANGE_KIND_LABELS[change.changeKind] ?? change.changeKind}
                  </span>
                )}
                {change.bytes !== null && <span className="file-change__bytes">{change.bytes} B</span>}
              </div>
              {change.diffExcerpt && (
                <pre className="file-change__diff" aria-label={`${change.virtualPath} 的 diff 摘录`}>
                  {change.diffExcerpt}
                </pre>
              )}
            </li>
          ))}
        </ul>
        <p className="stage-hint">diff 为**有界摘录**；完整内容不进入回传通道。</p>
      </div>
    </section>
  )
}