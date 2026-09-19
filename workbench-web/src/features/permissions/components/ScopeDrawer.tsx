/**
 * 「编辑知识范围」抽屉：候选 = **现有绑定的并集** + **手动录入**，写入走后端 `PUT`。
 *
 * 口径（契约 §4，方案 A）：
 *  - 前端校验**只有**三件事：非空（每一项）、去重、**≤100 项**（服务端 `max_length=100`）；
 *    合法性（该库是否存在 / 是否可用）**一律以服务端为准**，前端不预设；
 *  - 留空是合法输入 = 解除该对象的全部绑定；
 *  - 写失败**就地呈现**（服务端原文 + "没有写入任何数据"），**不关闭抽屉、不假装成功**。
 */
import { useEffect } from 'react'
import { Alert, Form, Select, Typography } from 'antd'
import { FormDrawer } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { CANDIDATE_NOTE } from '../services/permissionsService'
import { BINDING_TYPE_LABEL, DIRECTORY_STATUS_LABEL, normalizeIds, validateIds } from '../types'
import type { ScopeRow } from '../types'

/** 写失败的就地提示（文案已在服务层映射好，这里只负责渲染）。 */
export interface ScopeDrawerError {
  message: string
  hint: string
}

export interface ScopeDrawerProps {
  open: boolean
  /** 正在编辑的行（含**当前绑定**，用于回填与"未保存改动"判定）。 */
  target: ScopeRow | null
  /** 候选标识（现有绑定的并集；下拉可选，也可直接手输新标识）。 */
  candidates: string[]
  error: ScopeDrawerError | null
  onClose: () => void
  /** 校验通过后回调（收到的标识已去空白、去重）。 */
  onSubmit: (ids: string[]) => void | Promise<void>
}

interface ScopeFormValues {
  knowledge_base_ids?: string[]
}

export function ScopeDrawer({ open, target, candidates, error, onClose, onSubmit }: ScopeDrawerProps) {
  const [form] = Form.useForm<ScopeFormValues>()
  const watched = Form.useWatch('knowledge_base_ids', form)
  const initial = normalizeIds(target?.knowledge_base_ids ?? [])
  const current = normalizeIds(watched ?? [])
  const dirty = JSON.stringify(current) !== JSON.stringify(initial)

  // 打开时回填当前绑定（表单是唯一真相，不另存一份状态）
  useEffect(() => {
    if (open) form.setFieldsValue({ knowledge_base_ids: target?.knowledge_base_ids ?? [] })
  }, [open, target, form])

  const handleClose = () => {
    form.resetFields()
    onClose()
  }

  const handleSubmit = () => {
    const ids = normalizeIds(form.getFieldsValue().knowledge_base_ids ?? [])
    return onSubmit(ids)
  }

  return (
    <FormDrawer
      open={open}
      title={`编辑知识范围：${target?.name ?? ''}`}
      form={form}
      dirty={dirty}
      onClose={handleClose}
      onSubmit={handleSubmit}
      submitText="保存范围"
      width={560}
    >
      {target && (
        <Typography.Paragraph type="secondary">
          {`对象：${BINDING_TYPE_LABEL[target.binding_type]}「${target.binding_key}」（${DIRECTORY_STATUS_LABEL[target.status]}）`}
        </Typography.Paragraph>
      )}

      {error && (
        <Alert
          type="error"
          showIcon
          message={`未能保存：${error.message}`}
          description={error.hint}
          style={{ marginBottom: tokens.spacing.md }}
        />
      )}

      <Alert
        type="info"
        showIcon
        message="候选标识的来源"
        description={CANDIDATE_NOTE}
        style={{ marginBottom: tokens.spacing.md }}
      />

      <Form.Item
        name="knowledge_base_ids"
        label="知识库标识"
        extra="留空表示解除该对象的全部绑定。"
        rules={[
          {
            validator: (_, value: string[] | undefined) => {
              const invalid = validateIds(value ?? [])
              return invalid === null ? Promise.resolve() : Promise.reject(new Error(invalid))
            },
          },
        ]}
      >
        <Select
          mode="tags"
          allowClear
          placeholder="从候选里选择，或直接输入新的知识库标识"
          options={candidates.map((id) => ({ value: id, label: id }))}
        />
      </Form.Item>
    </FormDrawer>
  )
}