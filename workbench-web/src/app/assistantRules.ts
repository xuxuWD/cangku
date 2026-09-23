/**
 * 悬浮助手的**规则层**（B3 §6 + §11 N3）
 *
 * 规格 §11 N3 逐字：**「不在悬浮助手里用 LLM 做排序/意图识别」**——
 * 「理由：待办排序与意图识别是**确定性逻辑**，用 LLM 只会更慢更贵更不可测」。
 *
 * ⇒ 本文件**全是纯函数、零副作用、零模型调用**，可穷举测试。
 *
 * ⚠️ **单一可信来源**：本文件是规则层的**唯一实现**。`src/prototype/`（B3 形态原型）也从这里 import
 * —— 不保留第二份拷贝，避免两处规则漂移。
 */

/** 待办类别（受控枚举，且**顺序即排序** —— 规格 §6 指定的顺序）。 */
export type AttentionKind = '待审批' | '待输入' | '受阻' | '失败' | '完成'

/** 规格 §6 逐字：按 `待审批 > 待输入 > 受阻 > 失败 > 完成` 排序。 */
export const ATTENTION_ORDER: readonly AttentionKind[] = ['待审批', '待输入', '受阻', '失败', '完成']

/** 规则层只依赖这三个字段，具体来源（通知 / 审批 / 原型样例）由调用方适配。 */
export interface AttentionLike {
  id: string
  kind: AttentionKind
  title: string
}

/**
 * 跨模块统一「待你处理」清单。
 *
 * **排序是稳定排序**（同 kind 保持输入顺序）：`Array.prototype.sort` 自 ES2019 起保证稳定，
 * 所以同一份输入**每次得到同一份输出** —— 这是"可测"的前提。
 */
export function buildAttentionItems<T extends AttentionLike>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => ATTENTION_ORDER.indexOf(a.kind) - ATTENTION_ORDER.indexOf(b.kind))
}

/** 条数文案（0 条时**不显示数字**，避免"0"被读成别的意思）。 */
export function attentionBadgeText(count: number): string {
  if (count <= 0) return '暂无待你处理'
  return `待你处理 ${count} 条`
}

/**
 * 跟进建议 —— **纯规则**（规格 §6：省钱且可测）。
 * 只为**非完成态**给建议：完成态没有"下一步"，硬凑一条就是在编。
 */
export function buildSuggestedActions(kind: AttentionKind): string[] {
  switch (kind) {
    case '待审批':
      return ['查看工作项后批准或驳回', '让数字员工补充修改说明']
    case '待输入':
      return ['补齐缺失的输入后重新提交']
    case '受阻':
      return ['查看阻塞原因', '让数字员工换一条执行路径']
    case '失败':
      return ['查看失败步骤', '让数字员工重试']
    case '完成':
      return []
  }
}

/** 意图（受控枚举，不是自由文本 —— 便于穷举与断言）。 */
export type AssistantIntent = 'delegate' | 'approvals' | 'new_conversation' | 'unknown'

export interface IntentMatch {
  intent: AssistantIntent
  /** 命中的正则原文，供界面如实显示"为什么这么理解"。 */
  matched: string | null
}

/**
 * 中文正则意图路由（规格 §6 逐字给出前两条，其余按同一口径补）。
 *
 * **顺序有意义**：先判更具体的（委派 → 审批 → 新建），避免"派给审批岗"被后一条误吃。
 * 匹配不到**如实返回 `unknown`，绝不猜** —— 猜错比不猜更贵。
 */
const INTENT_RULES: readonly { intent: AssistantIntent; pattern: RegExp }[] = [
  { intent: 'delegate', pattern: /委派|交给|派给|安排给/ },
  { intent: 'approvals', pattern: /审批|待我批|批准|驳回/ },
  { intent: 'new_conversation', pattern: /新对话|新建对话|开个对话|重新开始/ },
]

export function routeIntent(text: string): IntentMatch {
  const trimmed = text.trim()
  if (trimmed === '') return { intent: 'unknown', matched: null }
  for (const rule of INTENT_RULES) {
    const hit = rule.pattern.exec(trimmed)
    if (hit) return { intent: rule.intent, matched: hit[0] }
  }
  return { intent: 'unknown', matched: null }
}

/** 意图 → 界面文案（唯一来源，组件不另写一套）。 */
export const INTENT_LABEL: Record<AssistantIntent, string> = {
  delegate: '按「委派」处理',
  approvals: '跳转到「待我处理」的审批项',
  new_conversation: '新建对话',
  unknown: '没听懂 —— 请把要做的事再说具体一点',
}
