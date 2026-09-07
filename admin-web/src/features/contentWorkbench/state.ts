export function createIdempotencyKey(topic: string, sources: Array<{ url: string; excerpt: string }>, references: string[]) { return `content:${topic.trim()}:${JSON.stringify(sources)}:${[...references].sort().join(',')}` }

export function createRegenerationIdempotencyKey(taskId: string, runId: string) { return `content:regenerate:${taskId}:${runId}` }
