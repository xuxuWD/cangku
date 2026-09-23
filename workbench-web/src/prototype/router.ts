/**
 * B3 原型 · 轻量路由（规格 §8，**方案 B：自建，零新依赖**）
 *
 * ⚠️ **B3 §13.1 V2 尚未裁决**（引入 `react-router` vs 自建）。本原型**选自建**，理由：
 *  ① 引入依赖属「依赖新增决策」，须单独裁决 —— 原型阶段不该先斩后奏；
 *  ② `admin-web` 已有同款自建路由的**先例**（`URLSearchParams` + `popstate` + `pushState`），
 *     本文件沿用同一口径，**不引入第二套规则**；
 *  ③ 规格 §8 要求的是"可直达 / 可分享 / 可刷新 / 前进后退"这四条**能力**，自建即可满足；
 *     若最终裁决引 `react-router`，替换点**只有本文件**（页面不认识 URL）。
 *
 * 覆盖验收 **A5**：所有页面可地址栏直达、可刷新、可分享。
 */
import { useEffect, useState } from 'react'
import { PRIMARY_NAV, MORE_NAV } from './nav'
import type { PrototypeView } from './nav'

export interface PrototypeRoute {
  view: PrototypeView
  /** 右栏当前对象（规格 §5「当前业务对象」）。`null` = 右栏空态。 */
  objectId: string | null
  /** 右栏页签（`brief` 简要信息 / `employee` 数字员工面板）。 */
  panel: 'brief' | 'employee' | null
  /**
   * 右栏是否展开为整页（规格 §5 的"逃生口"：展开时**左对话隐藏**）。
   * **放进 URL**（而不是组件内 state）——因为规格 §8 要求"所有页面可直达/可刷新/可分享"，
   * 展开态若只在内存里，刷新就丢了。
   */
  expand: boolean
}

const ALL_VIEWS: readonly PrototypeView[] = [...PRIMARY_NAV, ...MORE_NAV].map((item) => item.view)

function isView(value: string | null): value is PrototypeView {
  return value !== null && (ALL_VIEWS as readonly string[]).includes(value)
}

/** 解析 `location.search` → 路由。无法识别的 `view` 回落到 `chat`（**不报错、不留白屏**）。 */
export function parseRoute(search: string): PrototypeRoute {
  const params = new URLSearchParams(search)
  const rawView = params.get('view')
  const rawPanel = params.get('panel')
  return {
    view: isView(rawView) ? rawView : 'chat',
    objectId: params.get('object'),
    panel: rawPanel === 'brief' || rawPanel === 'employee' ? rawPanel : null,
    expand: params.get('expand') === '1',
  }
}

/** 路由 → `?query` 串（`null` / `false` 值不拼进去）。 */
export function buildSearch(route: PrototypeRoute): string {
  const params = new URLSearchParams()
  params.set('view', route.view)
  if (route.objectId) params.set('object', route.objectId)
  if (route.panel) params.set('panel', route.panel)
  if (route.expand) params.set('expand', '1')
  return `?${params.toString()}`
}

/**
 * 跳转。`replace = true` 时用 `replaceState`（用于"修正掉非法 view"这类**不该进历史栈**的动作）。
 * **同步**更新 URL —— 与规格 §4 要求 ② 同一精神：可见性相关的事不做异步。
 */
export function navigate(route: PrototypeRoute, options: { replace?: boolean } = {}): void {
  const search = buildSearch(route)
  if (options.replace) window.history.replaceState(null, '', search)
  else window.history.pushState(null, '', search)
  // `pushState` 不触发 `popstate`，故必须主动广播一次，否则订阅者收不到
  window.dispatchEvent(new PopStateEvent('popstate'))
}

/** 订阅当前路由（含浏览器前进 / 后退）。 */
export function useRoute(): PrototypeRoute {
  const [route, setRoute] = useState<PrototypeRoute>(() => parseRoute(window.location.search))

  useEffect(() => {
    const sync = () => setRoute(parseRoute(window.location.search))
    window.addEventListener('popstate', sync)
    // 「地址栏直达一个非法 view」时**把 URL 修正为规范化形态**（用 replace，不污染历史栈）
    const initial = parseRoute(window.location.search)
    if (window.location.search !== buildSearch(initial)) navigate(initial, { replace: true })
    return () => window.removeEventListener('popstate', sync)
  }, [])

  return route
}

/** 便捷构造（界面各处跳转用），避免每处都写全字段。 */
export function routeFor(
  view: PrototypeView,
  objectId: string | null = null,
  panel: 'brief' | 'employee' | null = null,
  expand = false,
): PrototypeRoute {
  return { view, objectId, panel, expand }
}
