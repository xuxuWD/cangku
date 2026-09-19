/**
 * 抽屉表单：提交 / 取消 / 校验失败 / 提交中（提交中按钮 disabled，防重复提交）；
 * 关闭前若存在未保存改动，先二次确认。
 *
 * 四态：`state` 非 `ready` 时，抽屉正文改为统一四态呈现，且**不提供提交按钮**
 * （加载中、加载失败、无权限时都不该让人提交）。empty 表示"没有可提交的内容"。
 *
 * 只读态（`readOnly`）：用于"查看详情"，表单整体禁用、只留"关闭"，关闭前不做未保存确认。
 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Alert, Button, Drawer, Form, Modal, Space } from 'antd'
import type { FormInstance } from 'antd'
import { ContentState } from './ContentState'
import type { ContentStateKind } from './ContentState'
import { tokens } from '../theme/tokens'

export interface FormDrawerProps {
  open: boolean
  title: string
  /** 表单实例由调用方持有，便于打开时回填。 */
  form: FormInstance
  /** 表单内容（`Form.Item` 列表），`Form` 外壳由本组件提供。 */
  children: ReactNode
  /** 提交回调；返回 Promise 期间视为"提交中"。只读态不会被调用。 */
  onSubmit: () => void | Promise<void>
  onClose: () => void
  /** 是否有未保存改动（为 true 时关闭会二次确认；只读态忽略此项）。 */
  dirty?: boolean
  submitText?: string
  cancelText?: string
  /** 只读态：表单禁用、不渲染提交按钮（查看详情用）。 */
  readOnly?: boolean
  /** 默认 `ready`。 */
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
  width?: number
}

export function FormDrawer({
  open,
  title,
  form,
  children,
  onSubmit,
  onClose,
  dirty = false,
  submitText = '提交',
  cancelText = '取消',
  readOnly = false,
  state = 'ready',
  stateDescription,
  onRetry,
  width = 480,
}: FormDrawerProps) {
  const [pending, setPending] = useState(false)
  const [invalid, setInvalid] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const usable = state === 'ready'

  const handleSubmit = async () => {
    setInvalid(false)
    try {
      await form.validateFields()
    } catch {
      // 校验失败：留在原地并显式提示（字段级错误由 Form 自己展示）。
      setInvalid(true)
      return
    }
    setPending(true)
    try {
      await onSubmit()
    } finally {
      setPending(false)
    }
  }

  const requestClose = () => {
    if (pending) return
    // 只读态没有"未保存的改动"，不需要二次确认。
    if (dirty && !readOnly) {
      setConfirmOpen(true)
      return
    }
    onClose()
  }

  return (
    <>
      <Drawer
        open={open}
        title={title}
        width={width}
        onClose={requestClose}
        maskClosable={false}
        footer={
          usable && !readOnly ? (
            <Space>
              <Button onClick={requestClose} disabled={pending}>
                {cancelText}
              </Button>
              <Button type="primary" loading={pending} disabled={pending} onClick={() => void handleSubmit()}>
                {submitText}
              </Button>
            </Space>
          ) : (
            <Button onClick={onClose}>关闭</Button>
          )
        }
      >
        {!usable && <ContentState state={state} description={stateDescription} onRetry={onRetry} boxed={false} />}

        {usable && !readOnly && invalid && (
          <Alert type="error" showIcon message="请先修正表单中的错误，再提交。" style={{ marginBottom: tokens.spacing.md }} />
        )}

        {usable && (
          <Form form={form} layout="vertical" disabled={pending || readOnly}>
            {children}
          </Form>
        )}
      </Drawer>

      <Modal
        open={confirmOpen}
        title="放弃未保存的改动？"
        okText="放弃并关闭"
        cancelText="继续编辑"
        okButtonProps={{ danger: true }}
        onOk={() => {
          setConfirmOpen(false)
          onClose()
        }}
        onCancel={() => setConfirmOpen(false)}
      >
        关闭后本次填写的内容不会保存。
      </Modal>
    </>
  )
}