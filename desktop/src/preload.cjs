'use strict';

// 预加载脚本：只向渲染进程透出极小的只读信息，绝不开放任何 Node 能力。
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld(
  'workbenchDesktop',
  Object.freeze({
    platform: process.platform,
    appVersion: process.versions.electron,
  }),
);
