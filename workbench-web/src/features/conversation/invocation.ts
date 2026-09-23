// P2c-1 发送路径路由：判定输入是不是「结构化工具调用」。
// 契约口径（「工具执行（P2a 段二）」变更点 5）：带 `Idempotency-Key` ⇒ 真实执行 + 幂等，
// 且 `content` 必须是 `{"tool_key": string, "params": object}`；非结构化内容一律 422（不静默执行）。
//
// 这里只做**路径选择**（决定带不带键、走不走 `messages:stream`），**不是权限判定**：
// 服务端仍是唯一权威（结构化但未知工具 ⇒ 422 原样展示）。
export interface ToolInvocation {
  tool_key: string
  params: Record<string, unknown>
}

export function parseToolInvocation(content: string): ToolInvocation | null {
  const text = content.trim()
  if (!text.startsWith('{') || !text.endsWith('}')) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return null
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null
  const candidate = parsed as { tool_key?: unknown; params?: unknown }
  const toolKey = typeof candidate.tool_key === 'string' ? candidate.tool_key.trim() : ''
  const params = candidate.params
  if (!toolKey) return null
  if (typeof params !== 'object' || params === null || Array.isArray(params)) return null
  return { tool_key: toolKey, params: params as Record<string, unknown> }
}