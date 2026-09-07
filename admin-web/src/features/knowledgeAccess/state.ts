import type { KnowledgeState, SubjectType } from './types'

export const initialKnowledgeState: KnowledgeState = { subjectType: 'role', subjectKey: 'content-operator', selectedIds: [], initialIds: [], bindingLoaded: false, loading: true, saving: false, error: null, saveError: null, auditError: null, audits: [], auditsLoading: true, toast: null }
export function createIdempotencyKey(type: SubjectType, key: string, ids: string[]): string { return `${type}:${key}:${[...ids].sort().join(',')}` }
