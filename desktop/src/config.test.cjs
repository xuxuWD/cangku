'use strict';

// 零依赖单元测试：只使用 Node 内置 node:test + node:assert/strict。
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const {
  DEFAULT_DEV_URL,
  DEFAULT_ALLOWED_ORIGINS,
  resolveAppUrl,
  resolveAllowedOrigins,
  isAllowedNavigation,
  resolveWindowOptions,
} = require('./config.cjs');

const BUNDLED_INDEX = path.join(__dirname, '..', 'web', 'index.html');

test('resolveAppUrl 优先使用环境变量并去除空白', () => {
  const url = resolveAppUrl(
    { WORKBENCH_DESKTOP_URL: '  https://workbench.example.com/app  ' },
    { bundledIndexPath: BUNDLED_INDEX, fileExists: () => true },
  );

  assert.equal(url, 'https://workbench.example.com/app');
});

test('resolveAppUrl 环境变量为空且内置产物存在时返回 file:// 地址', () => {
  const url = resolveAppUrl(
    {},
    { bundledIndexPath: BUNDLED_INDEX, fileExists: () => true },
  );

  assert.equal(url, pathToFileURL(BUNDLED_INDEX).href);
  assert.ok(url.startsWith('file://'));
});

test('resolveAppUrl 环境变量为空且内置产物缺失时回退默认开发地址', () => {
  const url = resolveAppUrl(
    { WORKBENCH_DESKTOP_URL: '   ' },
    { bundledIndexPath: BUNDLED_INDEX, fileExists: () => false },
  );

  assert.equal(url, DEFAULT_DEV_URL);
});

test('resolveAppUrl 未提供 fileExists 时默认视为不存在', () => {
  assert.equal(resolveAppUrl({}, { bundledIndexPath: BUNDLED_INDEX }), DEFAULT_DEV_URL);
});

test('resolveAllowedOrigins 未配置时返回默认清单的副本', () => {
  const origins = resolveAllowedOrigins({});

  assert.deepEqual(origins, DEFAULT_ALLOWED_ORIGINS);
  assert.notEqual(origins, DEFAULT_ALLOWED_ORIGINS);
});

test('resolveAllowedOrigins 按逗号解析并去空白、丢空项', () => {
  const origins = resolveAllowedOrigins({
    WORKBENCH_DESKTOP_ALLOWED_ORIGINS: ' http://a.example.com , http://b.example.com ,, ',
  });

  assert.deepEqual(origins, ['http://a.example.com', 'http://b.example.com']);
});

test('resolveAllowedOrigins 全部为空项时回退默认清单', () => {
  const origins = resolveAllowedOrigins({
    WORKBENCH_DESKTOP_ALLOWED_ORIGINS: ' , , ',
  });

  assert.deepEqual(origins, DEFAULT_ALLOWED_ORIGINS);
});

test('isAllowedNavigation 放行白名单内 origin 及其子路径', () => {
  assert.equal(
    isAllowedNavigation('http://localhost:5173/', DEFAULT_ALLOWED_ORIGINS),
    true,
  );
  assert.equal(
    isAllowedNavigation('http://localhost:5173/#/content/history', DEFAULT_ALLOWED_ORIGINS),
    true,
  );
});

test('isAllowedNavigation 拒绝白名单外的 origin', () => {
  assert.equal(
    isAllowedNavigation('http://evil.example.com/', DEFAULT_ALLOWED_ORIGINS),
    false,
  );
});

test('isAllowedNavigation 拒绝 javascript: 与 file: 协议', () => {
  assert.equal(isAllowedNavigation('javascript:alert(1)', DEFAULT_ALLOWED_ORIGINS), false);
  assert.equal(isAllowedNavigation('file:///etc/passwd', DEFAULT_ALLOWED_ORIGINS), false);
});

test('isAllowedNavigation 对非法 URL 与非法入参 fail-closed', () => {
  assert.equal(isAllowedNavigation('not a url', DEFAULT_ALLOWED_ORIGINS), false);
  assert.equal(isAllowedNavigation('', DEFAULT_ALLOWED_ORIGINS), false);
  assert.equal(isAllowedNavigation(null, DEFAULT_ALLOWED_ORIGINS), false);
  assert.equal(isAllowedNavigation('http://localhost:5173/', null), false);
});

test('isAllowedNavigation 区分 http 与 https 不同源', () => {
  assert.equal(
    isAllowedNavigation('https://localhost:5173/', ['http://localhost:5173']),
    false,
  );
});

test('resolveWindowOptions 固化安全基线并原样透传 preload 路径', () => {
  const preload = path.join(__dirname, 'preload.cjs');
  const options = resolveWindowOptions(preload);

  assert.equal(options.webPreferences.preload, preload);
  assert.equal(options.webPreferences.contextIsolation, true);
  assert.equal(options.webPreferences.nodeIntegration, false);
  assert.equal(options.webPreferences.sandbox, true);
  assert.equal(options.webPreferences.webSecurity, true);
  assert.equal(options.webPreferences.allowRunningInsecureContent, false);
  assert.equal(options.webPreferences.experimentalFeatures, false);
  assert.equal(options.webPreferences.spellcheck, false);
  assert.equal(options.show, false);
  assert.equal(options.autoHideMenuBar, true);
});
