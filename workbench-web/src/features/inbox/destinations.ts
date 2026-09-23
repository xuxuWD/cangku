/**
 * 通知目标落点解析 —— 「能到 / 不能到」都要**如实说清**，绝不出现"点了没反应"。
 *
 * **2026-09-23 更新（换壳之后）**：应用壳有了**右栏「当前对象」**（B3 §5），
 * 于是"能到哪"从**二选一**变成了**两档**：
 *
 * | 档 | 能不能 | 说明 |
 * | --- | --- | --- |
 * | **右栏摘要** | ✅ 能 | 通知本身带着标题与目标标识 ⇒ 右栏能立刻显示该对象的简要信息 |
 * | **完整页面** | ❌ 仍不能 | 任务详情 / 运行详情等页面尚未合并进本工作台 |
 *
 * ⚠️ **不再返回"完全打不开"**：以前是空集 + 一句说明，现在是"能看摘要在右栏、看全页还不行"。
 * 这两句必须**同时**说，只说前者会让人以为功能齐了，只说后者会让人以为什么都做不了。
 */
import { INBOX_TARGET_LABELS } from './types'
import type { InboxItem } from './types'

export interface InboxDestination {
  /** 目标标识是否可用（右栏预览的前提）。 */
  canPreview: boolean
  /** 能预览时的按钮文案；不能时为 `null`（**不渲染按钮**）。 */
  label: string | null
  /** 完整页面尚未合并的如实说明；无目标时为 `null`。 */
  note: string | null
}

/** 无目标（如"注册申请已通过"）：没有落点，也就没有说明 —— 不制造多余文案。 */
const NO_TARGET: InboxDestination = { canPreview: false, label: null, note: null }

export function resolveInboxDestination(item: InboxItem): InboxDestination {
  if (!item.target_type || !item.target_id) return NO_TARGET

  const targetName = INBOX_TARGET_LABELS[item.target_type]
  return {
    canPreview: true,
    label: '在右栏查看',
    note: `可在右栏看到「${targetName}」的简要信息；该对象的**完整页面**尚未合并进本工作台。`,
  }
}
