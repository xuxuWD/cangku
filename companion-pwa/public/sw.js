// 工作台伴侣端 Service Worker（手写，安全第一）。
//
// 缓存策略：
//   - install 阶段预缓存应用外壳（HTML、manifest、图标），让离线仍能打开界面；
//   - activate 阶段清理旧版本缓存；
//   - fetch 阶段只对「同源 + 非 API + GET」请求做缓存优先。
//
// 安全红线：
//   认证接口与业务接口的响应含个人待办等敏感数据，绝不缓存。
//   因此任何 /api/ 前缀请求、跨源请求一律直接交给网络，不读取缓存、不写入缓存。
//   非 GET 请求（POST 审批动作等）一律不拦截。

const CACHE_NAME = 'workbench-companion-v1';
const APP_SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/icon-192.svg',
  './icons/icon-512.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // 非 GET 请求（例如审批 POST）不拦截，直接交给网络。
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // 跨源请求不缓存（避免把第三方响应写入本站缓存）。
  if (url.origin !== self.location.origin) return;

  // 认证与业务接口响应含个人待办数据，绝不缓存；/api/ 前缀请求直接交给网络。
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
