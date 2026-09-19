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
import { ApiError } from '../api/client'

/** 页面上唯一一处"示例数据"标识文案（项目级固定文案，禁止各处另写）。
 *  只在**开发模式**存在：生产构建里为空串 ⇒ 「示例数据（未接后端）」字样不进产物（构建后 grep 为 0）。 */
export const SAMPLE_DATA_BADGE: string = import.meta.env.DEV ? '示例数据（未接后端）' : ''

/**
 * 适配层模式解析（各模块共用，单一来源）：显式构建变量 > 开发期默认 `mock` > **生产默认 `http`**。
 * 生产**不允许**回落到样例数据 —— 那会让"没接线"看起来像"真的没有内容"（假空）。
 */
export function resolveServiceMode(): 'mock' | 'http' {
  const injected = import.meta.env.VITE_WORKBENCH_API_MODE
  if (injected === 'mock' || injected === 'http') return injected
  return import.meta.env.DEV ? 'mock' : 'http'
}

/**
 * 样例数据信封：`sample` 是**硬标记**（`true` = 开发期样例，`false` = 后端真实数据）。
 * 界面据此显示"示例数据（未接后端）"标识，避免假数据被当成真数据；**禁止**把真实数据标成样例，反之亦然。
 */
export interface SamplePayload<T> {
  sample: boolean
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
  throw new ServiceError(`${what}尚未接入：后端接口未接线，本批不展示任何数据。`, 'not_connected')
}

/**
 * 请求层失败 → 适配层失败（第 6 轮接线批 2 新增的共用原语）。
 *
 * - `403` ⇒ `forbidden`（界面走"无权限"态，与"加载失败"分开）；
 * - 其余（`401` / `404` / `409` / `422` / `429` / `5xx` / 网络）⇒ `failed`，
 *   文案沿用请求层**已 sanitize** 的 `message`（堆栈 / SQL / 内部路径在请求层已被丢弃）；
 * - 非请求层错误原样抛出（不吞异常、不改写成"未接入"）。
 */
export function serviceErrorFromApi(error: unknown): never {
  if (error instanceof ApiError) {
    throw new ServiceError(error.message, error.failure === 'forbidden' ? 'forbidden' : 'failed')
  }
  throw error
}

/** 取数失败 → 界面四态：`forbidden` 单独区分（无权限），其余一律按 `error` 处理。 */
export function panelStateOfError(error: unknown): 'error' | 'forbidden' {
  return error instanceof ServiceError && error.failure === 'forbidden' ? 'forbidden' : 'error'
}