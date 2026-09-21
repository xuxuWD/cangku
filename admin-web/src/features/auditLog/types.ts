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

// 审计动作中文标签；键必须覆盖后端 AuditAction 的全部 49 个取值（有漂移守护测试）。
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
  'run.acceptance_decided': '运行验收已决议',
  'run.promoted_to_task': '运行已沉淀为任务',
  'workforce.role.created': '岗位已新增',
  'workforce.role.updated': '岗位已更新',
  'workforce.role.disabled': '岗位已停用',
  'workforce.agent.created': '数字员工已新增',
  'workforce.agent.updated': '数字员工已更新',
  'workforce.agent.disabled': '数字员工已停用',
  'conversation.created': '会话已创建',
  'conversation.archived': '会话已归档',
  'conversation.message.sent': '对话消息已发送',
  'workforce.agent.config.read': '数字员工配置已查看',
  'workforce.agent.config.updated': '数字员工配置已更新',
  'workforce.agent.config.rejected': '数字员工配置被拒绝',
  'tool.executed': '工具已执行',
  'tool.blocked': '工具执行被拦截',
  'commercial.retention.updated': '保留策略已更新',
  'commercial.retention.purged': '过期数据已按保留策略清理',
  'commercial.deletion.executed': '租户删除已执行',
  'commercial.deletion.confirmed': '租户删除已确认',
  'memory.fact.created': '记忆事实已创建',
  'memory.fact.superseded': '记忆事实已作废',
  'memory.rule.created': '记忆规则已创建',
  'memory.profile.updated': '画像已更新',
  'skill.submitted': '技能包已提交',
  'skill.approved': '技能包已通过',
  'skill.rejected': '技能包已驳回',
  'skill.enabled': '技能已启用',
  'skill.disabled': '技能已停用',
  'knowledge.doc.registered': '知识文档已登记',
  'knowledge.doc.published': '知识文档已发布',
  'knowledge.doc.archived': '知识文档已归档',
  'knowledge.doc.reviewed': '知识文档已复核',
  'knowledge.doc.review_due': '知识文档已到期待复核',
  'knowledge.search.blocked': '知识检索被守卫拦截',
  'evolution.case.changed': '评测用例已变更',
  'evolution.eval.completed': '评测运行已完成',
  // P5a CRM（2026-09-17）：十七个动作码（crm-p5a-design §2.10）。
  'crm.account.created': '客户已创建',
  'crm.contact.created': '联系人已创建',
  'crm.lead.converted': '线索已转化',
  'crm.opportunity.created': '商机已创建',
  'crm.opportunity.stage_changed': '商机阶段已迁移',
  'crm.activity.logged': '跟进活动已登记',
  'crm.quote.created': '报价已创建',
  'crm.quote.confirmed': '报价已确认',
  'crm.quote.converted': '报价已转合同',
  'crm.quote.voided': '报价已作废',
  'crm.contract.created': '合同已创建',
  'crm.contract.signed': '合同签署已登记',
  'crm.contract.voided': '合同已作废',
  'crm.contract.payment_registered': '合同回款已登记',
  'crm.insight.generated': '跟进计划已生成',
  'crm.sensitive.revealed': '完整联系方式已显示',
  'crm.health.recomputed': '客户健康度已重算',
  // P2b 实时流（2026-09-17）：熔断 / 写失败 / 悬挂兜底的治理事件。
  'conversation.stream.unavailable': '过程回放暂时不可用',
  // P2c-4（2026-09-17）：会话模式变更 / 本人导出 / 物理删除 / 只问答模式拒绝执行。
  'conversation.mode.changed': '会话模式已变更',
  'conversation.exported': '个人会话数据已导出',
  'conversation.deleted': '会话已被本人删除',
  'conversation.execution.rejected': '会话模式拒绝执行',
  // P2c-6（2026-09-17）：会话协作——成员添加 / 撤销（只记标识与授权档，不含姓名与手机号）。
  'conversation.member.added': '会话成员已添加',
  'conversation.member.removed': '会话成员已撤销',
  // 第 13 轮（2026-09-21）：审计导出留痕（契约 docs/contracts/audit-export-plan.md §4）。
  'audit.exported': '审计日志已导出',
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
