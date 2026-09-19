/**
 * 危险操作二次确认（删除 / 导出 / 权限变更等）。
 *
 * 纪律：必须提供一种二次确认方式 —— 输入确认词（`confirmWord`）或勾选声明（`acknowledgeText`）；
 * **两种都没提供时确认按钮永远不可点**（安全默认，宁可点不动，也不要误删）。
 * 确认按钮用 AntD `Button danger`，不自造样式。
 */
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Alert, Button, Checkbox, Input, Modal, Space, Typography } from 'antd'
import { ContentState } from './ContentState'
import type { ContentStateKind } from './ContentState'

export interface DangerConfirmProps {
  open: boolean
  title: string
  /** 说明这次操作会带来什么后果。 */
  description: ReactNode
  /** 需要原样输入的确认词，例如"删除"。 */
  confirmWord?: string
  /** 勾选式声明文案（与 `confirmWord` 二选一，`confirmWord` 优先）。 */
  acknowledgeText?: string
  confirmText?: string
  cancelText?: string
  onConfirm: () => void | Promise<void>
  onCancel: () => void
  /** 默认 `ready`；非 ready 时正文改为统一四态呈现，且确认按钮不可点。 */
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
}

export function DangerConfirm({
  open,
  title,
  description,
  confirmWord,
  acknowledgeText,
  confirmText = '确认执行',
  cancelText = '取消',
  onConfirm,
  onCancel,
  state = 'ready',
  stateDescription,
  onRetry,
}: DangerConfirmProps) {
  const [typed, setTyped] = useState('')
  const [checked, setChecked] = useState(false)
  const [pending, setPending] = useState(false)

  // 每次重新打开都回到"未确认"状态，避免上次的输入被复用。
  useEffect(() => {
    if (open) {
      setTyped('')
      setChecked(false)
    }
  }, [open])

  const satisfied = confirmWord ? typed.trim() === confirmWord : acknowledgeText ? checked : false
  const usable = state === 'ready'
  const canConfirm = usable && satisfied && !pending

  const handleConfirm = async () => {
    if (!canConfirm) return
    setPending(true)
    try {
      await onConfirm()
    } finally {
      setPending(false)
    }
  }

  return (
    <Modal
      open={open}
      title={title}
      maskClosable={false}
      onCancel={onCancel}
      footer={
        <Space>
          <Button onClick={onCancel} disabled={pending}>
            {cancelText}
          </Button>
          <Button danger type="primary" disabled={!canConfirm} loading={pending} onClick={() => void handleConfirm()}>
            {confirmText}
          </Button>
        </Space>
      }
    >
      {!usable && <ContentState state={state} description={stateDescription} onRetry={onRetry} boxed={false} />}

      {usable && (
        <>
          <Typography.Paragraph>{description}</Typography.Paragraph>

          {confirmWord && (
            <Input
              value={typed}
              placeholder={`请输入「${confirmWord}」以确认`}
              aria-label={`请输入「${confirmWord}」以确认`}
              onChange={(event) => setTyped(event.target.value)}
            />
          )}

          {!confirmWord && acknowledgeText && (
            <Checkbox checked={checked} onChange={(event) => setChecked(event.target.checked)}>
              {acknowledgeText}
            </Checkbox>
          )}

          {!confirmWord && !acknowledgeText && (
            <Alert type="warning" showIcon message="未配置二次确认方式，出于安全考虑该操作不可执行。" />
          )}
        </>
      )}
    </Modal>
  )
}