/**
 * 「登记知识文档」抽屉（**只登记元数据，不含正文**；正文由知识服务侧保存）。
 *
 * 口径：
 *  - 前端校验**只有**三项非空与长度上限（与后端 `max_length` 对齐）；合法性一律以服务端为准；
 *  - 登记**幂等**：同一文档标识重复登记返回既有条目（界面据此提示，不重复创建）；
 *  - 写失败**就地呈现**（服务端原文 + "没有写入任何数据"），**不关闭抽屉、不假装成功**。
 */
import { useEffect } from 'react'
import { Alert, Form, Input, Typography } from 'antd'
import { FormDrawer } from '../../../components'
import { tokens } from '../../../theme/tokens'
import type { RegisterInput } from '../types'

/** 登记失败的就地提示（文案已在服务层映射好，这里只负责渲染）。 */
export interface RegisterDrawerError {
  message: string
  hint: string
}

export interface RegisterDrawerProps {
  open: boolean
  error: RegisterDrawerError | null
  onClose: () => void
  onSubmit: (input: RegisterInput) => void | Promise<void>
}

interface RegisterFormValues {
  document_id: string
  title?: string
  owner_id?: string
  version?: string
  source_key?: string
}

/** 表单初值（与后端默认值对齐：`title` 可空、`version=1`、`source_key=manual`）。 */
const INITIAL: RegisterFormValues = { document_id: '', title: '', owner_id: '', version: '1', source_key: 'manual' }

export function RegisterDrawer({ open, error, onClose, onSubmit }: RegisterDrawerProps) {
  const [form] = Form.useForm<RegisterFormValues>()

  // 每次打开都回到初值（表单是唯一真相，不另存一份状态）
  useEffect(() => {
    if (open) form.setFieldsValue(INITIAL)
  }, [open, form])

  const handleClose = () => {
    form.resetFields()
    onClose()
  }

  const handleSubmit = () => {
    const values = form.getFieldsValue()
    return onSubmit({
      document_id: (values.document_id ?? '').trim(),
      title: (values.title ?? '').trim(),
      owner_id: (values.owner_id ?? '').trim(),
      version: (values.version ?? '').trim(),
      source_key: (values.source_key ?? '').trim(),
    })
  }

  return (
    <FormDrawer
      open={open}
      title="登记知识文档"
      form={form}
      onClose={handleClose}
      onSubmit={handleSubmit}
      submitText="提交登记"
    >
      {error && (
        <Alert
          type="error"
          showIcon
          message={`未能登记：${error.message}`}
          description={error.hint}
          style={{ marginBottom: tokens.spacing.md }}
        />
      )}

      <Typography.Paragraph type="secondary">
        本页只登记文档元数据（不含正文）；登记后以「草稿」存在，发布后才进入可检索范围。
      </Typography.Paragraph>

      <Form.Item
        name="document_id"
        label="文档标识"
        rules={[
          { required: true, message: '请填写文档标识' },
          { max: 128, message: '文档标识最长 128 个字符' },
        ]}
      >
        <Input placeholder="知识服务侧的文档标识" autoComplete="off" />
      </Form.Item>

      <Form.Item name="title" label="标题" rules={[{ max: 300, message: '标题最长 300 个字符' }]}>
        <Input placeholder="用于列表与检索结果展示" autoComplete="off" />
      </Form.Item>

      <Form.Item
        name="owner_id"
        label="负责人标识"
        rules={[{ max: 128, message: '负责人标识最长 128 个字符' }]}
        extra="发布需要指定负责人；此处可留空，发布前需补齐。"
      >
        <Input placeholder="留空表示暂未指定" autoComplete="off" />
      </Form.Item>

      <Form.Item name="version" label="版本" rules={[{ max: 32, message: '版本最长 32 个字符' }]}>
        <Input autoComplete="off" />
      </Form.Item>

      <Form.Item name="source_key" label="来源" rules={[{ max: 32, message: '来源最长 32 个字符' }]}>
        <Input autoComplete="off" />
      </Form.Item>
    </FormDrawer>
  )
}