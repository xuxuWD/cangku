export type ContentStatus = 'generating' | 'reviewing' | 'confirmed' | 'failed'
export interface ContentSource { url: string; excerpt: string }
export interface ContentDraft { draft_id: string; title: string; summary: string; body_markdown: string; image_suggestions: string[]; citations: Array<{ url: string }>; template_version: string; confirmed_by?: string | null; confirmed_at?: string | null }
export interface ContentTask { task_id: string; run_id: string; status: ContentStatus; revision: number; topic: string; sources: ContentSource[]; knowledge_references: string[]; draft: ContentDraft }
