'use strict';

// 主进程：整个工程里**唯一** require('electron') 的业务文件。
const { app, BrowserWindow, shell } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const {
  isAllowedNavigation,
  resolveAllowedOrigins,
  resolveAppUrl,
  resolveWindowOptions,
} = require('./config.cjs');

// 模块加载时计算一次，作为导航白名单。
const ALLOWED_ORIGINS = resolveAllowedOrigins(process.env);

let mainWindow = null;

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
