export type ContentStatus = 'generating' | 'reviewing' | 'confirmed' | 'failed'
export interface ContentSource { url: string; excerpt: string }
export interface ContentDraft { draft_id: string; title: string; summary: string; body_markdown: string; image_suggestions: string[]; citations: Array<{ url: string }>; template_version: string; confirmed_by?: string | null; confirmed_at?: string | null }
export interface ContentTask { task_id: string; run_id: string; status: ContentStatus; revision: number; topic: string; sources: ContentSource[]; knowledge_references: string[]; draft: ContentDraft }
export interface ContentTaskSummary {
  task_id: string
  tenant_id?: string
  created_by: string
  topic: string
  status: ContentStatus
  run_id: string
  created_at: string
  updated_at: string
}
export interface ContentTaskList {
  items: ContentTaskSummary[]
  page: number
  page_size: number
  total: number
  has_next: boolean
}
