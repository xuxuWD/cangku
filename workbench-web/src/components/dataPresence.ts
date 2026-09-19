/**
 * 「数据可用性」词汇表（状态保真）—— 指标卡与表格共用。
 *
 * 口径来自契约 `docs/contracts/role-templates.md` 验收第 5 条：
 * 「未配置 / 样本不足 / 未验证」三种**非数值态**必须如实展示，
 * **不得**渲染成 `0`，也**不得**贴上"成功"之类的语义标签。
 * 因此这个枚举是 StatCard / DataTable / StatusTag 组件 API 的一部分，而不是调用方的自由文本。
 */

/** 数据可用性：就绪 + 三种非数值态。 */
export type DataPresence = 'ready' | 'not_configured' | 'insufficient_sample' | 'unverified'

/** 非就绪态的短标签（就绪态不显示任何占位文案）。 */
export const DATA_PRESENCE_LABEL: Record<Exclude<DataPresence, 'ready'>, string> = {
  not_configured: '未配置',
  insufficient_sample: '样本不足',
  unverified: '未验证',
}

/** 非就绪态的整句说明（表格等需要完整说明的位置用）。 */
export const DATA_PRESENCE_DESCRIPTION: Record<Exclude<DataPresence, 'ready'>, string> = {
  not_configured: '尚未配置数据源，暂不展示统计。',
  insufficient_sample: '样本不足，暂不展示统计。',
  unverified: '数据未验证，暂不展示统计。',
}

/** 取短标签；`ready` 返回 undefined（调用方据此决定是否显示占位）。 */
export function presenceLabel(presence: DataPresence): string | undefined {
  return presence === 'ready' ? undefined : DATA_PRESENCE_LABEL[presence]
}

/** 取整句说明；`ready` 返回 undefined。 */
export function presenceDescription(presence: DataPresence): string | undefined {
  return presence === 'ready' ? undefined : DATA_PRESENCE_DESCRIPTION[presence]
}