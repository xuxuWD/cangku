/**
 * 「MCP」块：**后端零实现** ⇒ 如实呈现「尚未接入」，不伪造服务器 / 工具清单（契约 §3 末行 / §4）。
 *
 * 为什么不在这里放任何表格 / 开关：`app/` 内没有任何 MCP 端点可接，
 * 任何"服务器列表""连通性测试""开关"都只能是编造 —— 那比空态更糟。
 */
import { Space, Typography } from 'antd'
import { ContentState } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { MCP_NOT_CONNECTED_NOTE, MCP_NOT_CONNECTED_TITLE } from '../services/skillsService'

export function McpPanel() {
  return (
    <Space direction="vertical" size={tokens.spacing.sm} style={{ width: '100%' }}>
      <Typography.Title level={3}>MCP 服务器</Typography.Title>
      <ContentState state="empty" description={`${MCP_NOT_CONNECTED_TITLE}：${MCP_NOT_CONNECTED_NOTE}`} />
    </Space>
  )
}