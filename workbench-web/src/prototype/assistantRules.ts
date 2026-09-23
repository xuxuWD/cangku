/**
 * ⚠️ **本文件只是转发，不是第二份实现。**
 *
 * 规则层（待办排序 / 跟进建议 / 中文正则意图路由）的**唯一实现**在
 * `src/app/assistantRules.ts` —— 2026-09-23 把原型与真壳的实现**收敛成了一份**，
 * 避免两处规则漂移（B3 §11 N4 的同一精神：不新造第二套）。
 *
 * 保留这个转发文件是为了让原型的其它文件与用例不用改 import 路径。
 */
export {
  ATTENTION_ORDER,
  INTENT_LABEL,
  attentionBadgeText,
  buildAttentionItems,
  buildSuggestedActions,
  routeIntent,
} from '../app/assistantRules'
export type { AssistantIntent, AttentionKind, AttentionLike, IntentMatch } from '../app/assistantRules'
