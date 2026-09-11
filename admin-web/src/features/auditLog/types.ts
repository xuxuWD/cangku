// 通用审计查询前端类型：与服务端 GET /api/v1/audits 契约保持一致。
export interface AuditRecord {
  record_id: string
  action: string
  actor_id: string | null
  target_type: string | null
  target_id: string | null
  phone_masked: string | null
  detail: Record<string, unknown>
  occurred_at: string
}

export interface AuditListResponse {
  items: AuditRecord[]
  total: number
  limit: number
  offset: number
}

// 查询条件：空字符串表示不筛选，actions 为空数组表示不限动作。
export interface AuditFilters {
  actions: string[]
  actorId: string
  targetType: string
  targetId: string
  since: string
  until: string
  limit: number
  offset: number
}

export interface AuditErrorShape {
  status: number
  message: string
  retryable: boolean
}

export interface AuditLogState {
  items: AuditRecord[]
  total: number
  loading: boolean
  error: AuditErrorShape | null
}

// 审计动作中文标签；键必须覆盖后端 AuditAction 的全部 33 个取值（有漂移守护测试）。
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  'account.registration.requested': '注册申请已提交',
  'account.registration.approved': '注册申请已通过',
  'account.registration.rejected': '注册申请被驳回',
  'account.login.succeeded': '登录成功',
  'account.login.failed': '登录失败',
  'account.login.locked': '账号已锁定',
  'account.password.changed': '密码已修改',
  'account.password.reset': '密码已重置',
  'account.totp.enrolled': '已登记动态口令',
  'account.totp.confirmed': '动态口令已确认',
  'account.totp.reset': '动态口令已重置',
  'account.totp.enrollment_required': '要求登记动态口令',
  'account.sso.login.succeeded': '单点登录成功',
  'account.sso.login.rejected': '单点登录被拒绝',
  'account.sso.identity.bound': '已绑定单点身份',
  'account.sso.mfa_required': '单点登录要求二次验证',
  'plan.proposed': '计划已提交',
  'plan.approved': '计划已通过',
  'plan.rejected': '计划被驳回',
  'plan.run_started': '计划已开始运行',
  'orchestration.proposed': '编排提案已提交',
  'orchestration.approved': '编排提案已通过',
  'orchestration.rejected': '编排提案被驳回',
  'dead_letter.notified': '死信已通知',
  'dead_letter.notification_failed': '死信通知失败',
  'content.source.scraped': '内容来源已抓取',
  'content.publication.requested': '发布请求已提交',
  'content.publication.succeeded': '发布成功',
  'content.publication.manual_takeover': '发布转人工接管',
  'content.publication.verified': '发布结果已验证',
  'inbox.write_failed': '通知写入失败',
  'run.notify_skipped': '运行通知已跳过',
  'run.approval_decided': '运行审批已决议',
}

// 取不到标签时回落显示动作码本身，避免出现空白。
export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}

// 明细只渲染一层标量；嵌套对象/数组折叠为「…」，不把未知结构 dump 到界面。
export function auditDetailEntries(detail: Record<string, unknown>): Array<{ key: string; text: string }> {
  return Object.entries(detail ?? {}).map(([key, value]) => {
    if (typeof value === 'string') return { key, text: value }
    if (typeof value === 'number') return { key, text: String(value) }
    if (typeof value === 'boolean') return { key, text: value ? '是' : '否' }
    if (value === null || value === undefined) return { key, text: '—' }
    return { key, text: '…' }
  })
}
