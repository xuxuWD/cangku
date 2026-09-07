export type SubjectType = 'role' | 'agent'

export interface KnowledgeBinding { binding_type: SubjectType; binding_key: string; knowledge_base_ids: string[] }
export interface KnowledgeAudit { id?: string; binding_type: SubjectType; binding_key: string; before_knowledge_base_ids: string[]; after_knowledge_base_ids: string[]; actor_id: string; created_at: string }
export interface ApiErrorShape { status: number; message: string; retryable: boolean; unauthorized: boolean }
export interface KnowledgeState { subjectType: SubjectType; subjectKey: string; selectedIds: string[]; initialIds: string[]; bindingLoaded: boolean; loading: boolean; saving: boolean; error: ApiErrorShape | null; saveError: ApiErrorShape | null; auditError: ApiErrorShape | null; audits: KnowledgeAudit[]; auditsLoading: boolean; toast: string | null }

export const KNOWLEDGE_BASES = [
  { id: 'company-general', name: '公司通用知识库', description: '制度、品牌规范、常用流程', icon: 'document' },
  { id: 'content-operations', name: '内容运营知识库', description: '选题、标题、平台规则、案例', icon: 'content' },
  { id: 'media-projects', name: '自媒体项目资料', description: '当前项目的素材、脚本与复盘', icon: 'project' },
  { id: 'geo-project', name: 'GEO 项目知识库', description: '仅限绑定项目检索，自动记录引用来源', icon: 'geo', sensitive: true },
  { id: 'finance', name: '财务与经营数据', description: '报表、预算、结算信息', icon: 'document' },
  { id: 'client-delivery', name: '客户交付资料', description: '合同、需求、交付记录', icon: 'project' },
]
