'use strict';

// 纯函数配置模块：**禁止 import electron**，以便 `node --test` 直接加载测试。
// 主进程从这里取窗口选项、目标地址与导航白名单。

const pathToFileURL = require('node:url').pathToFileURL;

const DEFAULT_DEV_URL = 'http://localhost:5173/';
const DEFAULT_ALLOWED_ORIGINS = [
  'http://localhost:5173',
  'http://127.0.0.1:5173',
];

function trimmed(value) {
  return typeof value === 'string' ? value.trim() : '';
}

/**
 * 解析桌面端要加载的地址。
 * 优先级：环境变量 WORKBENCH_DESKTOP_URL > 打包内置产物（file://）> 默认开发服务器。
 */
function resolveAppUrl(env = process.env, options = {}) {
  const override = trimmed(env && env.WORKBENCH_DESKTOP_URL);
  if (override) {
    return override;
  }

  const bundledIndexPath = options.bundledIndexPath;
  const fileExists = options.fileExists || (() => false);
  if (bundledIndexPath && fileExists(bundledIndexPath)) {
    return pathToFileURL(bundledIndexPath).href;
  }

  return DEFAULT_DEV_URL;
}

/**
 * 解析允许加载/导航的来源清单。
 * 环境变量以英文逗号分隔，去空白并丢弃空项；为空时回退到默认开发来源。
 */
function resolveAllowedOrigins(env = process.env) {
  const raw = trimmed(env && env.WORKBENCH_DESKTOP_ALLOWED_ORIGINS);
  if (!raw) {
    return [...DEFAULT_ALLOWED_ORIGINS];
  }

  const parsed = raw
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);

  if (parsed.length === 0) {
    return [...DEFAULT_ALLOWED_ORIGINS];
  }

  return parsed;
}

/**
 * 判断一次导航是否允许。
 * 采用 fail-closed：只接受 http/https 且 origin 命中白名单的地址；
 * javascript:、file:、非法 URL 与解析异常一律拒绝。
 */
function isAllowedNavigation(targetUrl, allowedOrigins) {
  if (typeof targetUrl !== 'string' || !Array.isArray(allowedOrigins)) {
    return false;
  }

  let parsed;
  try {
    parsed = new URL(targetUrl);
  } catch (error) {
    return false;
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return false;
  }

  return allowedOrigins.includes(parsed.origin);
}

/**
 * 生成 BrowserWindow 选项，集中固化安全基线。
 */
function resolveWindowOptions(preloadPath) {
  return {
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      spellcheck: false,
    },
  };
}

module.exports = {
  DEFAULT_DEV_URL,
  DEFAULT_ALLOWED_ORIGINS,
  resolveAppUrl,
  resolveAllowedOrigins,
  isAllowedNavigation,
  resolveWindowOptions,
};
