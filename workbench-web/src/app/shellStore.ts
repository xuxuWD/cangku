/**
 * 应用壳 · 右栏「当前对象」的状态（B3 §5）
 *
 * **为什么要有这个文件**：`AppShell` 的页面注册表里**所有页面都是无 props 组件**（`<Page />`）。
 * 三栏壳需要一个「当前对象」来填右栏，但**不能为此改掉页面的 props 契约**（那会波及全部页面与用例）。
 * 所以用**单一状态树**解耦：页面通过 `showObject()` **上报**它当前在讲哪个对象，壳从同一棵树读。
 *
 * **单一可信来源的口径（重要）**：
 * - **`objectId` / `objectType` 的唯一来源是 URL**（`shellRouter`）—— 这样"分享链接"能带上它；
 * - 本文件只存**详情**（标题 / 状态 / 说明），按 id 缓存；
 * - 深链直接打开时壳只有 id、没有详情 ⇒ 右栏**如实说明**"摘要需从对应页面进入"，
 *   **不编造标题**。
 */
import { create } from 'zustand'
import { navigateShell, shellRoute } from './shellRouter'
import type { PanelTab, ShellRoute } from './shellRouter'
import type { NavKey } from './navigation'

/** 右栏要展示的对象摘要（**字段全部来自页面的真实数据**，不臆造）。 */
export interface ShellObject {
  id: string
  /** 对象类型（`task` / `run` / …），决定措辞与将来的上下文注入字段名。 */
  type: string
  title: string
  /** 次要一行（如状态）。 */
  status?: string
  /** 如实说明：该对象的详情页是否已合并进来。 */
  detail?: string
}

interface ShellStoreState {
  /** 按 id 缓存的详情：深链 + 浏览器后退时能重新显示同一对象。 */
  objects: Record<string, ShellObject>
  remember: (object: ShellObject) => void
  forgetAll: () => void

  /* ---- 壳级 UI 状态（悬浮助手与设置弹窗；**不进 URL** —— 它们不该被分享出去） ---- */
  assistantOpen: boolean
  setAssistantOpen: (open: boolean) => void
  /** 悬浮助手里输入的最后一句（纯规则意图路由用，**不调 LLM**，规格 §11 N3）。 */
  assistantDraft: string
  setAssistantDraft: (text: string) => void
  settingsOpen: boolean
  setSettingsOpen: (open: boolean) => void
}

export const useShellStore = create<ShellStoreState>()((set) => ({
  objects: {},
  remember: (object) => set((state) => ({ objects: { ...state.objects, [object.id]: object } })),
  forgetAll: () => set({ objects: {} }),

  assistantOpen: false,
  setAssistantOpen: (open) => set({ assistantOpen: open }),
  assistantDraft: '',
  setAssistantDraft: (text) => set({ assistantDraft: text }),
  settingsOpen: false,
  setSettingsOpen: (open) => set({ settingsOpen: open }),
}))

/**
 * 页面调用它把「当前对象」推到右栏。
 *
 * **同时把 `object` / `objectType` 写进 URL** —— 否则右栏状态不可分享，
 * 就违背了「这一页可直达 / 可分享」的承诺（B3 §8）。
 */
export function showObject(
  object: ShellObject,
  options: { view: NavKey; panel?: PanelTab; expand?: boolean } = { view: 'my-workbench' },
): void {
  useShellStore.getState().remember(object)
  navigateShell(shellRoute(options.view, { id: object.id, type: object.type }, options.panel ?? 'brief', options.expand ?? false))
}

/** 清掉右栏对象（保持当前 view 不变）。 */
export function clearObject(route: ShellRoute): void {
  navigateShell(shellRoute(route.view))
}

/** 仅供用例：重置（store 是模块级单例，用例之间会互相污染）。 */
export function resetShellStore(): void {
  useShellStore.setState({
    objects: {},
    assistantOpen: false,
    assistantDraft: '',
    settingsOpen: false,
  })
}
