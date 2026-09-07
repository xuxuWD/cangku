import type { ContentSource, ContentTask, ContentTaskList, ContentStatus } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')
const headers = (extra: HeadersInit = {}): HeadersInit => ({ Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'employee', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'employee', ...extra })

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  if (!response.ok) throw new Error(`服务暂时无法完成请求（${response.status}）`)
  return await response.json() as T
}

export function createContentTask(topic: string, sources: ContentSource[], knowledgeReferences: string[], idempotencyKey: string) { return request<ContentTask>('/content-tasks', { method: 'POST', body: JSON.stringify({ topic, sources, knowledge_references: knowledgeReferences, idempotency_key: idempotencyKey }) }) }
export function getContentTask(taskId: string) { return request<ContentTask>(`/content-tasks/${encodeURIComponent(taskId)}`) }
export function listContentTasks(status: ContentStatus | '', page = 1, pageSize = 20) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status) params.set('status', status)
  return request<ContentTaskList>(`/content-tasks?${params.toString()}`)
}
export function updateDraft(taskId: string, revision: number, draft: ContentTask['draft']) { return request<ContentTask>(`/content-tasks/${encodeURIComponent(taskId)}/draft`, { method: 'PUT', body: JSON.stringify({ revision, title: draft.title, summary: draft.summary, body_markdown: draft.body_markdown, image_suggestions: draft.image_suggestions }) }) }
export function confirmContentTask(taskId: string, revision: number) { return request<ContentTask>(`/content-tasks/${encodeURIComponent(taskId)}/confirmation`, { method: 'POST', body: JSON.stringify({ revision }) }) }
export function regenerateContentTask(taskId: string, idempotencyKey: string) { return request<ContentTask>(`/content-tasks/${encodeURIComponent(taskId)}/regenerations`, { method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }) }) }
export async function downloadMarkdown(taskId: string) { const response = await fetch(`${apiBase}/content-tasks/${encodeURIComponent(taskId)}/export.md`, { headers: headers() }); if (!response.ok) throw new Error('确认后才能导出'); return response.blob() }
