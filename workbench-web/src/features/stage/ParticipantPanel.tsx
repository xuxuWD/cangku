/**
 * 参与者与分享（P2c-6 §2.16 呈现层，纯展示 + 本地表单态）：
 * **参与者名单 + 最近活动时间**（＝会话 `updated_at`，**非实时在线态**）。
 *
 * **来源**：由 `admin-web/src/features/stage/ParticipantPanel.tsx` 合并移植（行为等价）。
 * 呈现层从手写 CSS（18 处 className）+ **裸 `input` / `select`**，换成
 * **AntD `Input` / `Select` / `Button` / `StatusTag`** —— ADR-0003 禁止自造表单控件。
 *
 * **纪律（原实现，保留）**：
 *  * 名单数据**一律来自服务端**（`GET .../members`），**不在前端造名字**；
 *  * 只有**发起人**（`is_owner` 且成员号＝当前账号）能增删成员 —— 被分享者是只读视角；
 *  * 「**已读内容不可撤回**」必须如实告知（撤销只影响对方**新**的读取 / 发言请求）；
 *  * 分页口径：只显示本页时**如实标注**「已显示前 N 人」，不静默截断、不谎报为全部。
 */
import { useState } from 'react'
import { Button, Card, Input, Select, Space, Typography } from 'antd'
import { EmptyState, StatusTag } from '../../components'
import { formatDateTime } from '../../utils/format'
import { isConversationOwner, memberPermissionLabel } from '../conversation/types'
import type { ConversationMember, MemberPermission } from '../conversation/types'

export interface CollaborationPanelState {
  items: ConversationMember[]
  /** 服务端返回的**命中总数**（`> items.length` ⇒ 本页之外还有成员，如实告知）。 */
  total: number
  lastActivityAt: string | null
  loading: boolean
  error: string | null
  sharing: boolean
  onAdd: (memberId: string, permission: MemberPermission) => void
  onRemove: (memberId: string) => void
}

export function ParticipantPanel({ collaboration }: { collaboration: CollaborationPanelState }) {
  const [memberId, setMemberId] = useState('')
  const [permission, setPermission] = useState<MemberPermission>('read')
  const { items, total, lastActivityAt, loading, error, sharing, onAdd, onRemove } = collaboration
  const canShare = isConversationOwner(items)
  const owner = items.find((item) => item.is_owner)
  const knownTotal = Math.max(total, items.length)

  return (
    // ⚠️ 外层必须是 `<section aria-label>`（与产物登记面板同一原因：AntD `Card` 渲染 div，拿不到 region 角色）
    <section aria-label="参与者与分享">
      <Card
        size="small"
        title={
          <Space>
            <span>参与者</span>
            <Typography.Text type="secondary">
              {`${knownTotal} 人`}
              {items.length < knownTotal ? `（已显示前 ${items.length} 人）` : ''}
            </Typography.Text>
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          {`最近活动：${lastActivityAt ? formatDateTime(lastActivityAt) : '—'}`}
          <br />
          参与者名单与「最近活动」都是非实时快照（不做实时在线态，也不做协同编辑）。
        </Typography.Paragraph>

        {loading && items.length === 0 && <Typography.Text type="secondary">正在加载参与者…</Typography.Text>}
        {error && (
          <Typography.Paragraph type="danger">
            <strong>参与者加载失败</strong>
            {` ${error}`}
          </Typography.Paragraph>
        )}

        {items.length === 0 && !loading && !error && (
          <EmptyState boxed={false} description="暂无参与者信息。" />
        )}

        {items.map((item) => (
          <Space key={item.member_id} wrap style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space wrap size="small">
              <Typography.Text strong>{item.display_name}</Typography.Text>
              <StatusTag tone={item.is_owner ? 'info' : 'success'}>
                {memberPermissionLabel(item.permission)}
              </StatusTag>
              {item.role && <Typography.Text type="secondary">{item.role}</Typography.Text>}
              {!item.is_owner && item.created_at && (
                <Typography.Text type="secondary">{`加入于 ${formatDateTime(item.created_at)}`}</Typography.Text>
              )}
            </Space>
            {canShare && !item.is_owner && (
              <Button
                type="link"
                size="small"
                disabled={sharing}
                aria-label={`撤销 ${item.display_name}`}
                onClick={() => onRemove(item.member_id)}
              >
                撤销
              </Button>
            )}
          </Space>
        ))}

        {canShare ? (
          <Space direction="vertical" size="small" style={{ width: '100%', marginTop: 8 }}>
            <Typography.Text>成员账号</Typography.Text>
            <Input
              value={memberId}
              maxLength={128}
              placeholder="输入对方账号 ID（本租户已审批账号）"
              onChange={(event) => setMemberId(event.target.value)}
            />
            <Typography.Text>成员权限</Typography.Text>
            <Select<MemberPermission>
              aria-label="成员权限"
              value={permission}
              onChange={setPermission}
              options={[
                { value: 'read', label: '仅查看（read）' },
                { value: 'write', label: '可发言（write）' },
              ]}
            />
            <Button
              type="primary"
              disabled={sharing || memberId.trim().length === 0}
              onClick={() => onAdd(memberId.trim(), permission)}
            >
              添加成员
            </Button>
            <Typography.Text type="secondary">
              仅按账号 ID 点名（本租户、已审批、非客户管理员）；被分享者只能读，授予「可发言」后才能发言，
              且一律以其本人身份走既有权限与审批闸门。撤销后对方**新的**读取会被拒绝；**已读内容不可撤回**。
            </Typography.Text>
          </Space>
        ) : (
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            {`你正在查看${owner ? `由 ${owner.display_name} 分享` : '他人分享'}的会话：只有发起人可以增删成员。`}
          </Typography.Paragraph>
        )}
      </Card>
    </section>
  )
}
