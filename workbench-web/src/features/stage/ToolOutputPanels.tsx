/**
 * 内容级回传的两个面板（P2c-2 事项 I；契约「内容级回传」）。
 *
 * **来源**：由 `admin-web/src/features/stage/ToolOutputPanels.tsx` 合并移植（行为等价）。
 * 呈现层从手写 CSS（17 处 className）换成 **AntD `Card` + 令牌**，符合 ADR-0003。
 *
 * **纪律（原实现，重写后由用例保证）**：
 * - **只渲染白名单字段**（`output_excerpt` / `output_truncated` / `output_bytes` / `output_sha256` /
 *   `file_changes[].{virtual_path, change_kind, bytes, sha256, diff_excerpt}`），**未知键一律不猜测**；
 * - **截断必须显式告知**（`output_truncated` / `output_bytes`）；二进制只给字节数与摘要（**不落内容**）；
 * - **无数据不摆假面板**（面板按批次出现；`file_changes` 随 P2c-3 的 `fs.*` 落地才有数据）。
 */
import { Card, Space, Typography } from 'antd'
import type { StreamFrame } from '../conversation/types'
import { changeKindLabel } from '../runDetail/types'

interface TerminalEntry {
  seq: number
  toolKey: string
  excerpt: string | null
  truncated: boolean
  bytes: number | null
  sha256: string | null
}

const asString = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

function terminalEntries(frames: StreamFrame[]): TerminalEntry[] {
  const entries: TerminalEntry[] = []
  for (const frame of frames) {
    if (frame.kind !== 'tool.result') continue
    const payload = frame.payload
    const hasOutput =
      asString(payload.output_excerpt) !== null ||
      typeof payload.output_truncated === 'boolean' ||
      asNumber(payload.output_bytes) !== null
    if (!hasOutput) continue
    entries.push({
      seq: frame.seq,
      toolKey: asString(payload.tool_key) ?? '工具',
      excerpt: asString(payload.output_excerpt),
      truncated: payload.output_truncated === true,
      bytes: asNumber(payload.output_bytes),
      sha256: asString(payload.output_sha256),
    })
  }
  return entries
}

/** 终端输出面板：展示**最近一次**带输出的工具结果（有界摘录 + 截断告知）。 */
export function TerminalOutputPanel({ frames }: { frames: StreamFrame[] }) {
  const entries = terminalEntries(frames)
  if (entries.length === 0) return null
  const latest = entries[entries.length - 1]
  return (
    // ⚠️ 外层必须是 `<section aria-label>`：AntD `Card` 渲染 `<div>`，
    // 直接给它 aria-label 拿不到 `region` 角色（用例按 role=region 取面板）。
    <section aria-label="终端输出">
    <Card
      size="small"
      title={
        <Space>
          <span>终端输出</span>
          <Typography.Text type="secondary">
            {latest.toolKey}
            {latest.truncated ? ' · 已截断' : ''}
          </Typography.Text>
        </Space>
      }
    >
      {latest.excerpt !== null ? (
        <pre aria-label="执行输出摘录" style={{ margin: 0, overflowX: 'auto' }}>
          {latest.excerpt}
        </pre>
      ) : (
        <Typography.Text type="secondary">非文本输出不落内容：只记录字节数与摘要。</Typography.Text>
      )}
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
        {latest.truncated
          ? `输出超过回传上限，已截断（已读取 ${latest.bytes ?? 0} 字节；完整内容不进入回传通道）。`
          : `本次回传 ${latest.bytes ?? 0} 字节（有界摘录）。`}
        {latest.sha256 ? ` 摘要 ${latest.sha256.slice(0, 19)}…` : ''}
        {entries.length > 1 ? ` 另有 ${entries.length - 1} 条更早的输出。` : ''}
      </Typography.Paragraph>
    </Card>
    </section>
  )
}

export interface FileChangeEntry {
  seq: number
  virtualPath: string
  changeKind: string | null
  bytes: number | null
  sha256: string | null
  diffExcerpt: string | null
}

/** 从帧里收集变更条目（**逐条白名单**；缺虚拟路径即整条丢弃，不猜测）。P2c-3 与其他面板共用。 */
export function collectFileChanges(frames: StreamFrame[]): FileChangeEntry[] {
  const entries: FileChangeEntry[] = []
  for (const frame of frames) {
    const changes = frame.payload.file_changes
    if (!Array.isArray(changes)) continue
    for (const item of changes) {
      if (typeof item !== 'object' || item === null) continue
      const change = item as Record<string, unknown>
      const virtualPath = asString(change.virtual_path)
      if (!virtualPath) continue // 虚拟路径是唯一必填键；缺失即整条丢弃（不猜测）
      entries.push({
        seq: frame.seq,
        virtualPath,
        changeKind: asString(change.change_kind),
        bytes: asNumber(change.bytes),
        sha256: asString(change.sha256),
        diffExcerpt: asString(change.diff_excerpt),
      })
    }
  }
  return entries
}

/** 帧里是否出现过「变更被截断」的显式告知（`file_changes_truncated`）。 */
export function fileChangesTruncated(frames: StreamFrame[]): boolean {
  return frames.some((frame) => frame.payload.file_changes_truncated === true)
}

/** 文件改动面板：虚拟路径 + 变更类型 + 字节 + 有界 diff 摘录（数据随 P2c-3 的 `fs.*` 落地）。 */
export function FileDiffPanel({ frames }: { frames: StreamFrame[] }) {
  const changes = collectFileChanges(frames)
  if (changes.length === 0) return null
  return (
    <section aria-label="文件改动">
    <Card
      size="small"
      title={
        <Space>
          <span>文件改动</span>
          <Typography.Text type="secondary">
            {changes.length} 项
            {fileChangesTruncated(frames) ? ' · 已截断' : ''}
          </Typography.Text>
        </Space>
      }
    >
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {changes.map((change) => (
          <li key={`${change.seq}:${change.virtualPath}`} style={{ marginBottom: 8 }}>
            <Space wrap size="small">
              <Typography.Text>{change.virtualPath}</Typography.Text>
              {change.changeKind && <Typography.Text type="secondary">{changeKindLabel(change.changeKind)}</Typography.Text>}
              {change.bytes !== null && <Typography.Text type="secondary">{change.bytes} B</Typography.Text>}
            </Space>
            {change.diffExcerpt && (
              <pre aria-label={`${change.virtualPath} 的 diff 摘录`} style={{ margin: 0, overflowX: 'auto' }}>
                {change.diffExcerpt}
              </pre>
            )}
          </li>
        ))}
      </ul>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
        diff 为**有界摘录**；完整内容不进入回传通道。
        {fileChangesTruncated(frames) ? '本次变更条数超过上限，已截断（仅展示前若干条）。' : ''}
      </Typography.Paragraph>
    </Card>
    </section>
  )
}
