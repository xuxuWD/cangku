import '@testing-library/jest-dom/vitest'

// jsdom 不实现 matchMedia 与 ResizeObserver，而 AntD 的响应式与溢出测量组件需要它们存在。
// 这里只做最小桩：不引入额外依赖，也不改变组件行为（一律按"不匹配 / 无观察"处理）。
if (typeof window.matchMedia !== 'function') {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
}