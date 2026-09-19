import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'

// `findBy*` / `waitFor` 的默认等待只有 1000ms：本机负载高（如刚跑完 build/dev server）时
// 交互类用例会**假红**（2026-09-19 实测：CreateAgentDrawer 两条 Select 交互用例超时，
// 空闲复跑即全绿）。CI 机器通常比本机更慢 ⇒ 统一把默认等待放宽到 5s，
// 让"红"只代表真实缺陷，而不是机器忙。**不放宽断言本身**：超时仍会失败，只是给足时间。
configure({ asyncUtilTimeout: 5000 })

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