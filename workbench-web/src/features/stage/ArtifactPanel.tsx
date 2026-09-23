/**
 * 舞台「产物登记」面板（P2c-3 §2.7）：只读元数据（虚拟路径 / 变更类型 / 字节 / sha256）。
 *
 * **来源**：由 `admin-web/src/features/stage/ArtifactPanel.tsx` 合并移植（行为等价）。
 * 呈现层从手写 CSS（17 处 className）换成 **AntD `Card` + 项目组件库**，符合 ADR-0003。
 *
 * **纪律（原实现，重写后由用例保证）**：
 * - **四态齐备**：加载 / 空 / 错误（可重试）/ **无运行不渲染**（不摆假面板、也不发请求）；
 * - **只渲染白名单字段**（`useRunArtifacts` 已逐条投影），**不渲染内容 / `tenant_id` / 宿主路径**；
 * - **保留期如实告知**：只展示服务端返回的条目（过期条目服务端已不再返回）。
 */
import { Button, Card, Space, Typography } from 'antd'
import { EmptyState, SkeletonList, StatusTag } from '../../components'
import { changeKindLabel } from '../runDetail/types'
import type { RunArtifactsState } from './useRunArtifacts'

export function ArtifactPanel({
  runId,
  artifacts,
  onOpenRunDetail,
}: {
  runId?: string
  artifacts: RunArtifactsState
  onOpenRunDetail?: (runId: string) => void
}) {
  if (!runId) return null
  const { items, loading, error } = artifacts

  return (
    // ⚠️ 外层必须是 `<section aria-label>`：用例按 `role=region` 取本面板，
    // 而 AntD `Card` 渲染的是 `<div>`（拿不到 region 角色）。
    <section aria-label="产物登记">
      <Card
        size="small"
        title={
          <Space>
            <span>产物登记</span>
            {items.length > 0 && <Typography.Text type="secondary">{`${items.length} 项`}</Typography.Text>}
          </Space>
        }
      >
        {loading && items.length === 0 && <SkeletonList rows={2} state="loading" boxed={false} />}

        {!loading && error && (
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <Typography.Text strong>产物登记加载失败</Typography.Text>
            <Typography.Text type="secondary">{error.message}</Typography.Text>
            {/* 只有**可重试**的失败才给按钮（403 之类重试也不会变） */}
            {error.retryable && (
              <Button size="small" onClick={artifacts.reload}>
                重新尝试
              </Button>
            )}
          </Space>
        )}

        {!loading && !error && items.length === 0 && (
          <EmptyState
            boxed={false}
            description="本次运行没有登记产物"
            action={
              <Typography.Text type="secondary">
                只有真正写文件的工具（新建 / 覆盖 / 删除）才会登记产物。
              </Typography.Text>
            }
          />
        )}

        {!error && items.length > 0 && (
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {items.map((item) => (
                <li key={item.artifact_id}>
                  <Space wrap size="small">
                    <Typography.Text>{item.virtual_path}</Typography.Text>
                    <StatusTag tone="neutral">{changeKindLabel(item.change_kind)}</StatusTag>
                    <Typography.Text type="secondary">{`${item.bytes} B`}</Typography.Text>
                    <Typography.Text type="secondary" title={item.sha256}>
                      {`${item.sha256.slice(0, 19)}…`}
                    </Typography.Text>
                  </Space>
                </li>
              ))}
            </ul>
            <Typography.Text type="secondary">
              只登记元数据（虚拟路径 / 类型 / 字节 / 摘要），**不含文件内容**；过期后不再返回。
            </Typography.Text>
          </Space>
        )}

        {onOpenRunDetail && (
          <Button type="link" size="small" onClick={() => onOpenRunDetail(runId)}>
            在运行详情中打开
          </Button>
        )}
      </Card>
    </section>
  )
}
