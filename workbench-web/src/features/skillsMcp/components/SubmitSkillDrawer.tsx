/**
 * 「提交技能包」抽屉（员工视图与管理视图**共用**）。
 *
 * 纪律（与契约 §1 的三条服务端校验逐条对齐）：
 *  - 表单只做**易用性校验**（必填 / 长度 / 版本号形状 / 指纹长度形状），
 *    **不代算指纹**、**不代判工具键合法性**、**不代判语义版本递增** —— 这些一律以服务端判定为准；
 *  - 许可与工具键**只给下拉选项**（不放开自造键 / 自填许可）；
 *  - 服务端拒绝时**如实呈现服务端原文**（请求层已 sanitize），不吞掉、不改写成"提交失败"；
 *  - 提交失败就地呈现、抽屉不关闭、**不假装成功**。
 */
import { Form, Input, Select, Typography } from 'antd'
import type { FormInstance } from 'antd'
import { FormDrawer } from '../../../components'
import { tokens } from '../../../theme/tokens'
import {
  DEFAULT_SOURCE_KEY,
  LICENSE_OPTIONS,
  TOOL_KEY_HINT,
  TOOL_KEY_OPTIONS,
  looksLikeSemver,
  looksLikeSha256,
} from '../types'
import type { SubmitSkillInput } from '../types'

/** 表单取值（与后端 `SkillSubmitRequest` 逐字一致，不含任何额外键）。 */
type SubmitFormValues = SubmitSkillInput

export interface SubmitSkillDrawerProps {
  open: boolean
  form: FormInstance<SubmitFormValues>
  onClose: () => void
  onSubmit: (input: SubmitSkillInput) => void | Promise<void>
  /** 写失败的**服务端原文**与就地提示（由页面传入，抽屉只负责呈现）。 */
  error?: { message: string; hint: string } | null
}

export function SubmitSkillDrawer({ open, form, onClose, onSubmit, error = null }: SubmitSkillDrawerProps) {
  /** 提交前把表单值整理成后端请求体（去掉未填字段的空串差异，保持九个键齐全）。 */
  const handleSubmit = async () => {
    const values = form.getFieldsValue()
    await onSubmit({
      skill_key: values.skill_key?.trim() ?? '',
      version: values.version?.trim() ?? '',
      name: values.name?.trim() ?? '',
      description: values.description?.trim() ?? '',
      license: values.license,
      allowed_tools: values.allowed_tools ?? [],
      source_key: values.source_key?.trim() || DEFAULT_SOURCE_KEY,
      content_sha256: values.content_sha256?.trim() ?? '',
      content_body: values.content_body ?? '',
    })
  }

  return (
    <FormDrawer
      open={open}
      title="提交技能包"
      form={form}
      dirty={form.isFieldsTouched()}
      submitText="提交"
      onClose={onClose}
      onSubmit={handleSubmit}
      width={560}
    >
      {error && (
        <Typography.Paragraph type="danger" style={{ marginBottom: tokens.spacing.md }}>
          {error.message}
          <br />
          {error.hint}
        </Typography.Paragraph>
      )}

      <Form.Item
        label="技能包标识"
        name="skill_key"
        rules={[
          { required: true, message: '请填写技能包标识' },
          { max: 64, message: '标识最长 64 个字符' },
        ]}
        extra="小写字母、数字、点、下划线与短横线，且以字母或数字开头（服务端会再校验一次）"
      >
        <Input placeholder="例如 summarize" maxLength={64} />
      </Form.Item>

      <Form.Item
        label="版本号"
        name="version"
        rules={[
          { required: true, message: '请填写版本号' },
          { max: 32, message: '版本号最长 32 个字符' },
          {
            validator: (_, value: string) =>
              !value || looksLikeSemver(value)
                ? Promise.resolve()
                : Promise.reject(new Error('版本号须为 major.minor.patch（例如 1.0.0）')),
          },
        ]}
        extra="必须是三段式语义版本号（例如 1.0.0）；同标识的新版本必须高于已有版本"
      >
        <Input placeholder="1.0.0" maxLength={32} />
      </Form.Item>

      <Form.Item
        label="名称"
        name="name"
        rules={[
          { required: true, message: '请填写名称' },
          { max: 64, message: '名称最长 64 个字符' },
        ]}
      >
        <Input placeholder="例如 摘要助手" maxLength={64} />
      </Form.Item>

      <Form.Item
        label="描述"
        name="description"
        rules={[
          { required: true, message: '请填写描述' },
          { max: 800, message: '描述最长 800 个字符' },
        ]}
        extra="描述会被服务端做注入类内容扫描；含绕过指令的内容会被拒绝"
      >
        <Input.TextArea rows={3} maxLength={800} showCount />
      </Form.Item>

      <Form.Item label="许可" name="license" rules={[{ required: true, message: '请选择许可' }]}>
        <Select
          placeholder="请选择"
          options={LICENSE_OPTIONS.map((item) => ({ value: item, label: item }))}
        />
      </Form.Item>

      <Form.Item
        label="可调用工具"
        name="allowed_tools"
        rules={[{ required: true, message: '请至少选择一个工具' }]}
        extra={TOOL_KEY_HINT}
      >
        <Select
          mode="multiple"
          placeholder="请选择"
          options={TOOL_KEY_OPTIONS.map((item) => ({ value: item, label: item }))}
        />
      </Form.Item>

      <Form.Item
        label="来源"
        name="source_key"
        rules={[{ max: 64, message: '来源最长 64 个字符' }]}
        extra="须为部署时登记的来源；未登记的来源会被服务端拒绝（403）"
      >
        <Input placeholder={DEFAULT_SOURCE_KEY} maxLength={64} />
      </Form.Item>

      <Form.Item
        label="正文指纹（content_sha256）"
        name="content_sha256"
        rules={[
          { required: true, message: '请填写正文指纹' },
          {
            validator: (_, value: string) =>
              !value || looksLikeSha256(value)
                ? Promise.resolve()
                : Promise.reject(new Error('指纹须为 64 位十六进制字符')),
          },
        ]}
        extra="由你自己对正文计算后填入（64 位十六进制）；界面不代为计算指纹，服务端会核对是否与正文一致"
      >
        <Input placeholder="64 位十六进制指纹" maxLength={64} />
      </Form.Item>

      <Form.Item
        label="正文"
        name="content_body"
        rules={[{ required: true, message: '请填写正文' }]}
        extra="技能包正文（服务端有体积上限）；正文与指纹必须一致，否则会被拒绝"
      >
        <Input.TextArea rows={6} placeholder="# 技能说明与步骤……" />
      </Form.Item>
    </FormDrawer>
  )
}