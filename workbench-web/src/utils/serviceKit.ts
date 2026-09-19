/**
 * 适配层共享原语 —— 每个模块的 `services/*` 都要遵守同一条口径，所以放在这里共用。
 *
 * 三条纪律（与第 3 轮一致，接线层通用）：
 *  ① 样例数据必须带 `sample: true`，界面必须显示「示例数据（未接后端）」；
 *  ② `http` 分支**必须抛错**，不得静默返回空数组 —— 静默空会伪装成"真的没有数据"；
 *  ③ 失败必须分类，`forbidden` 与其它失败映射到不同的界面四态。
 *
 * 说明：`src/features/myWorkbench/services/myWorkbenchService.ts`（第 3 轮）里还有一份等价实现，
 * 那是先落在模块内的版本；**本轮未擅自改动已稳定的模块**，建议经确认后再合并到本文件（收尾清单会列出）。
 */

/** 页面上唯一一处"示例数据"标识文案（项目级固定文案，禁止各处另写）。 */
export const SAMPLE_DATA_BADGE = '示例数据（未接后端）'

/**
 * 样例数据信封：`sample: true` 是**硬标记**。
 * 界面据此显示"示例数据（未接后端）"标识，避免假数据被当成真数据。
 */
export interface SamplePayload<T> {
  sample: true
  items: T[]
}

/** 失败分类：决定界面进入哪一种四态。 */
export type ServiceFailure = 'not_connected' | 'forbidden' | 'failed'

/** 适配层错误（只带可读文案与分类，**不含**凭据 / 内部地址 / 堆栈）。 */
export class ServiceError extends Error {
  readonly failure: ServiceFailure

  constructor(message: string, failure: ServiceFailure) {
    super(message)
    this.name = 'ServiceError'
    this.failure = failure
  }
}

/** `http` 分支的统一出口：明确报"尚未接入"，绝不返回空数据。 */
export function notConnected(what: string): never {
  throw new ServiceError(`${what}尚未接入：后端接口未接线（本轮为${SAMPLE_DATA_BADGE}）。`, 'not_connected')
}

/** 取数失败 → 界面四态：`forbidden` 单独区分（无权限），其余一律按 `error` 处理。 */
export function panelStateOfError(error: unknown): 'error' | 'forbidden' {
  return error instanceof ServiceError && error.failure === 'forbidden' ? 'forbidden' : 'error'
}