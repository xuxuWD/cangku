'use strict';

// 主进程：整个工程里**唯一** require('electron') 的业务文件。
const { app, BrowserWindow, shell } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const {
  isAllowedNavigation,
  resolveAllowedOrigins,
  resolveAppUrl,
  resolveUpdateOptions,
  resolveWindowOptions,
} = require('./config.cjs');

// 模块加载时计算一次，作为导航白名单。
const ALLOWED_ORIGINS = resolveAllowedOrigins(process.env);

// 自动更新策略同样只解析一次；未配置更新源时为 { enabled: false }（fail-closed）。
const UPDATE_OPTIONS = resolveUpdateOptions(process.env);

// 更新检查间隔：6 小时。启动时先查一次，之后按间隔轮询。
const UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

let mainWindow = null;

/**
 * 按配置启用自动更新。
 * 未配置更新源时**不加载 electron-updater**，也不发起任何网络请求。
 */
function setupAutoUpdate() {
  if (!UPDATE_OPTIONS.enabled) {
    return;
  }

  // 延迟 require：仅启用自动更新时才加载该依赖。
  const { autoUpdater } = require('electron-updater');

  autoUpdater.setFeedURL({
    provider: 'generic',
    url: UPDATE_OPTIONS.feedUrl,
    channel: UPDATE_OPTIONS.channel,
  });
  autoUpdater.channel = UPDATE_OPTIONS.channel;
  autoUpdater.allowPrerelease = UPDATE_OPTIONS.allowPrerelease;
  autoUpdater.autoDownload = UPDATE_OPTIONS.autoDownload;
  autoUpdater.autoInstallOnAppQuit = UPDATE_OPTIONS.autoInstallOnAppQuit;

  // 更新失败不得影响应用使用：只记录脱敏后的错误信息。
  autoUpdater.on('error', (error) => {
    const message = error && error.message ? error.message : String(error);
    console.error(`自动更新失败：${message}`);
  });

  const check = () => {
    autoUpdater.checkForUpdates().catch((error) => {
      const message = error && error.message ? error.message : String(error);
      console.error(`自动更新检查失败：${message}`);
    });
  };

  check();
  setInterval(check, UPDATE_CHECK_INTERVAL_MS).unref();
}

function createWindow() {
  mainWindow = new BrowserWindow(
    resolveWindowOptions(path.join(__dirname, 'preload.cjs')),
  );

  // 等首屏渲染完成再显示，避免白屏闪烁。
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // 外链一律交给系统浏览器，绝不在应用内新开窗口。
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: 'deny' };
  });

  // 应用内导航只允许白名单来源，其余（含 file:、javascript:）直接拦截。
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url, ALLOWED_ORIGINS)) {
      event.preventDefault();
    }
  });

  mainWindow.loadURL(
    resolveAppUrl(process.env, {
      bundledIndexPath: path.join(__dirname, '..', 'web', 'index.html'),
      fileExists: fs.existsSync,
    }),
  );

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

const gotSingleInstanceLock = app.requestSingleInstanceLock();

if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) {
      return;
    }
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
  });

  // 禁止任何渲染进程挂载 webview。
  app.on('web-contents-created', (_event, contents) => {
    contents.on('will-attach-webview', (event) => {
      event.preventDefault();
    });
  });

  app.whenReady().then(() => {
    createWindow();
    setupAutoUpdate();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });
}
