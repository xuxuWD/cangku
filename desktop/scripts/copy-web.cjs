'use strict';

// 把 admin-web 的构建产物复制到 desktop/web，供打包时以 file:// 内置加载。
// 源目录不存在时以非 0 退出码结束，避免打包出「空壳」安装包。

const fs = require('node:fs');
const path = require('node:path');

const projectRoot = path.join(__dirname, '..');
const source = path.join(projectRoot, '..', 'admin-web', 'dist');
const target = path.join(projectRoot, 'web');

if (!fs.existsSync(source)) {
  console.error(
    `未找到 admin-web 构建产物：${source}\n请先在 admin-web 目录执行 npm run build 后再重试。`,
  );
  process.exit(1);
}

fs.rmSync(target, { recursive: true, force: true });
fs.mkdirSync(target, { recursive: true });
fs.cpSync(source, target, { recursive: true });

console.log(`已复制内置网页端产物：${source} -> ${target}`);
