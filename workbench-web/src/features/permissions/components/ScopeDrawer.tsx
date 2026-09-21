/**
 * 「编辑知识范围」抽屉：候选 = **知识库清单**（`GET /api/v1/knowledge/bases`）+ **手动录入**，写入走后端 `PUT`。
 *
 * 口径（契约 §4 第 15 轮修订 / `permissions-fake-entry-plan.md` §9.3）：
 *  - 前端校验**只有**三件事：非空（每一项）、去重、**≤100 项**（服务端 `max_length=100`）；
 *    合法性（该库是否存在 / 是否可用）**一律以服务端为准**，前端不预设、也**不阻断**；
 *  - 留空是合法输入 = 解除该对象的全部绑定；
 *  - **手输保留**：候选只来自"现有绑定"时，从未绑定过的租户会死锁（永远无法完成第一次绑定），
 *    故**不取消手输**；改为对"不在清单里的标识"给**黄色提醒**（提示，不阻断）；
 *  - 清单**没取到**时如实说"没取到"（**绝不**说"没有知识库"），且不再对手输值做判断（无从判断，不能误报）；
 *  - 写失败**就地呈现**（服务端原文 + "没有写入任何数据"），**不关闭抽屉、不假装成功**。
 */
import { useEffect } from 'react'
import { Alert, Form, Select, Typography } from 'antd'
import { FormDrawer } from '../../../components'
import { tokens } from '../../../theme/tokens'
import {
  CANDIDATE_ERROR_NOTE,
  CANDIDATE_LOADING_NOTE,
  CANDIDATE_NOTE,
  CANDIDATE_UNAVAILABLE_NOTE,
  CANDIDATE_UNKNOWN_NOTE,
} from '../services/permissionsService'
import {
  BINDING_TYPE_LABEL,
  DIRECTORY_STATUS_LABEL,
  normalizeIds,
  unknownCandidateIds,
  validateIds,
} from '../types'
import type { CandidateView, ScopeRow } from '../types'

/** 写失败的就地提示（文案已在服务层映射好，这里只负责渲染）。 */
export interface ScopeDrawerError {
  message: string
  hint: string
}

export interface ScopeDrawerProps {
  open: boolean
  /** 正在编辑的行（含**当前绑定**，用于回填与"未保存改动"判定）。 */
  target: ScopeRow | null
  /** 候选视图（含加载 / 降级 / 取不到三态；由页面注入）。 */
  candidates: CandidateView
  error: ScopeDrawerError | null
  onClose: () => void
  /** 校验通过后回调（收到的标识已去空白、去重）。 */
  onSubmit: (ids: string[]) => void | Promise<void>
}

interface ScopeFormValues {
  knowledge_base_ids?: string[]
}

/** 候选项显示名：有名称用名称，**没有名称回落显示标识**（不编造名称）。 */
function optionLabel(item: CandidateView['items'][number]): string {
  return item.name && item.name.length > 0 ? item.name : item.knowledge_base_id
}

/** 候选来源说明（三态各不相同；**降级与失败都不说"没有知识库"**）。 */
function candidateDescription(candidates: CandidateView): string {
  if (candidates.state === 'loading') return CANDIDATE_LOADING_NOTE
  if (candidates.state === 'error') return CANDIDATE_ERROR_NOTE
  if (!candidates.upstreamAvailable) return candidates.note ?? CANDIDATE_UNAVAILABLE_NOTE
  return CANDIDATE_NOTE
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

  // 只有"清单真的取到"时才可能判断某个标识不在清单里（取不到 ⇒ 无从判断，不能误报）
  const unknown =
    candidates.state === 'ready' && candidates.upstreamAvailable
      ? unknownCandidateIds(current, candidates.items)
      : []

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
        type={candidates.state === 'error' ? 'warning' : 'info'}
        showIcon
        message="候选标识的来源"
        description={candidateDescription(candidates)}
        style={{ marginBottom: tokens.spacing.md }}
      />

      {unknown.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message={`以下标识未出现在知识库清单中：${unknown.join('、')}`}
          description={CANDIDATE_UNKNOWN_NOTE}
          style={{ marginBottom: tokens.spacing.md }}
        />
      )}

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
          placeholder="从候选里选择，或直接输入知识库标识"
          options={candidates.items.map((item) => ({
            value: item.knowledge_base_id,
            label: optionLabel(item),
            title: item.knowledge_base_id,
          }))}
        />
      </Form.Item>
    </FormDrawer>
  )
}