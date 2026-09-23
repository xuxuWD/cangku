/**
 * 应用壳 · 轻量 URL 路由（B3 §8）
 *
 * **为什么现在才加**：`AppShell` 原来的注释写着「本轮没有深链分享与前进后退需求…引入正式路由时再统一升级」。
 * B3 §8 把它列为「不像一个产品」的**具体、可验收的缺口**：不能地址栏直达、不能分享、刷新丢状态、
 * 前进后退不可用。本文件就是补这个缺口。
 *
 * ⚠️ **B3 §13.1 V2 仍未裁决**（引入 `react-router` vs 自建）。本文件是**自建**方案，理由：
 *  ① 引入依赖属「依赖新增决策」，须单独裁决 —— 不该顺手带入；
 *  ② `admin-web` 已有同款自建路由的**先例**（`URLSearchParams` + `popstate` + `pushState`），
 *     这里沿用同一口径，**全仓只有一套路由规则**；
 *  ③ 若最终裁决引 `react-router`，**替换点只有本文件**（页面不认识 URL —— 它们都是无 props 组件）。
 *
 * 覆盖验收 **A5**：所有页面可地址栏直达、可刷新、可分享。
 */
import { useEffect, useState } from 'react'
import { ALL_NAV_KEYS } from './navigation'
import type { NavKey } from './navigation'

/** 右栏页签（B3 §5：「当前对象的简要信息 + 数字员工面板」）。 */
export type PanelTab = 'brief' | 'employee'

export interface ShellRoute {
  view: NavKey
  /** 右栏当前对象（如通知指向的任务/运行）。`null` = 右栏空态。 */
  objectId: string | null
  /** 对象类型（`task` / `run` / …），用于右栏措辞与将来的上下文注入字段名。 */
  objectType: string | null
  panel: PanelTab | null
  /** 右栏展开为整页（B3 §5 的逃生口；展开时**主区域隐藏**）。 */
  expand: boolean
}

/**
 * 合法视图键用 `ALL_NAV_KEYS`（**含不在侧栏的页**），**不是** `NAV_ITEMS`。
 * 用错会让"从设置弹窗打开的页"被判非法并回落 —— 详见 `navigation.ts` 里 `ALL_NAV_KEYS` 的说明。
 */
const ALL_KEYS: readonly NavKey[] = ALL_NAV_KEYS

function isNavKey(value: string | null): value is NavKey {
  return value !== null && (ALL_KEYS as readonly string[]).includes(value)
}

/**
 * 解析 `location.search` → 路由。
 *
 * **非法 `view` 一律回落默认页，不抛错、不留白屏**（地址栏是用户可编辑的输入，必须当不可信输入处理）。
 */
export function parseShellRoute(search: string, fallback: NavKey): ShellRoute {
  const params = new URLSearchParams(search)
  const rawView = params.get('view')
  const rawPanel = params.get('panel')
  return {
    view: isNavKey(rawView) ? rawView : fallback,
    objectId: params.get('object'),
    objectType: params.get('objectType'),
    panel: rawPanel === 'brief' || rawPanel === 'employee' ? rawPanel : null,
    expand: params.get('expand') === '1',
  }
}

/** 路由 → `?query`（`false` / `null` 一律不拼，避免同一状态有两条 URL）。 */
export function buildShellSearch(route: ShellRoute): string {
  const params = new URLSearchParams()
  params.set('view', route.view)
  if (route.objectId) params.set('object', route.objectId)
  if (route.objectType) params.set('objectType', route.objectType)
  if (route.panel) params.set('panel', route.panel)
  if (route.expand) params.set('expand', '1')
  return `?${params.toString()}`
}

/**
 * 跳转。`replace = true` 走 `replaceState`（用于"把非法 view 规范化回默认页"这类**不该进历史栈**的动作）。
 *
 * `pushState` **不会**触发 `popstate`，所以这里主动广播一次 —— 否则订阅者收不到（自建路由最常见的坑）。
 */
export function navigateShell(route: ShellRoute, options: { replace?: boolean } = {}): void {
  const search = buildShellSearch(route)
  if (options.replace) window.history.replaceState(null, '', search)
  else window.history.pushState(null, '', search)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

/** 便捷构造（界面各处跳转用），避免每处都写全字段。 */
export function shellRoute(
  view: NavKey,
  object: { id: string; type: string } | null = null,
  panel: PanelTab | null = null,
  expand = false,
): ShellRoute {
  return { view, objectId: object?.id ?? null, objectType: object?.type ?? null, panel, expand }
}

/**
 * 订阅当前路由（含浏览器前进 / 后退）。
 *
 * `fallback` 是"当前角色不可见任何页面时"的兜底键 —— 由调用方按角色算出来传入，
 * 保证任何一个角色都至少能取到一页（与 `AppShell` 既有的"回落而不是渲染空白"口径一致）。
 */
export function useShellRoute(fallback: NavKey): ShellRoute {
  const [route, setRoute] = useState<ShellRoute>(() => parseShellRoute(window.location.search, fallback))

  useEffect(() => {
    const sync = () => setRoute(parseShellRoute(window.location.search, fallback))
    window.addEventListener('popstate', sync)
    // 首次进入若地址栏是空或非法，**把 URL 规范化**（用 replace，不污染历史栈）
    const initial = parseShellRoute(window.location.search, fallback)
    if (window.location.search !== buildShellSearch(initial)) navigateShell(initial, { replace: true })
    return () => window.removeEventListener('popstate', sync)
  }, [fallback])

  return route
}
