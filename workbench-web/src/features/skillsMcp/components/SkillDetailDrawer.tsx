/**
 * 「技能包详情」抽屉：元数据只读呈现 + **正文按需拉取**（列表不返回正文，避免大响应）。
 *
 * 纪律：
 *  - 正文读取失败**如实呈现**（`404` = 不存在或当前不可见；`403` = 无权限），不拿列表数据凑数；
 *  - 样例模式**不伪造正文**（后端没被请求，就没有正文可展示）；
 *  - 正文为空的历史记录给"没有登记正文"的如实文案，不显示空白区域。
 */
import { useEffect, useState } from 'react'
import { Form, Input, Typography } from 'antd'
import { FormDrawer } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime } from '../../../utils/format'
import {
  EMPTY_CONTENT_NOTE,
  SAMPLE_DATA_BADGE,
  fetchSkillContent,
  isConnected,
  panelStateOfError,
} from '../services/skillsService'
import { SKILL_STATUS_LABEL, SOURCE_KEY_LABEL, UNKNOWN_STATUS_TEXT } from '../types'
import type { SkillSummary } from '../types'

type DetailState = ContentStateKind | 'ready'

export interface SkillDetailDrawerProps {
  skill: SkillSummary | null
  onClose: () => void
}

export function SkillDetailDrawer({ skill, onClose }: SkillDetailDrawerProps) {
  const [form] = Form.useForm()
  const [state, setState] = useState<DetailState>('loading')
  const [contentBody, setContentBody] = useState<string>('')
  const [stateDescription, setStateDescription] = useState<string | undefined>(undefined)
  const [attempt, setAttempt] = useState(0)

  const open = skill !== null
  const skillKey = skill?.skill_key ?? ''
  const version = skill?.version ?? ''

  useEffect(() => {
    if (!open) return
    let active = true
    setState('loading')
    setStateDescription(undefined)
    setContentBody('')
    fetchSkillContent(skillKey, version)
      .then((outcome) => {
        if (!active) return
        if (outcome.sample || !outcome.content) {
          // 样例模式：没有请求服务端 ⇒ 如实说明"没有可展示的正文"，**不伪造**
          setContentBody(outcome.note || EMPTY_CONTENT_NOTE)
        } else {
          setContentBody(outcome.content.content_body || EMPTY_CONTENT_NOTE)
        }
        setState('ready')
      })
      .catch((error: unknown) => {
        if (!active) return
        // 失败分类：`403` ⇒ 无权限态；其余（`404` 不可见 / 网络 / 5xx）⇒ 错误态 + 可重试
        setState(panelStateOfError(error))
        setStateDescription(error instanceof Error ? error.message : '正文加载失败，请稍后重试。')
      })
    return () => {
      active = false
    }
  }, [open, skillKey, version, attempt])

  return (
    <FormDrawer
      open={open}
      title={skill ? `技能包详情：${skill.skill_key}@${skill.version}` : '技能包详情'}
      form={form}
      readOnly
      onClose={onClose}
      onSubmit={() => undefined}
      width={640}
      state={state}
      stateDescription={stateDescription}
      onRetry={() => setAttempt((value) => value + 1)}
    >
      {skill && (
        <>
          {!isConnected() && (
            <Typography.Paragraph type="warning" style={{ marginBottom: tokens.spacing.md }}>
              {SAMPLE_DATA_BADGE}
            </Typography.Paragraph>
          )}

          <Form.Item label="名称">
            <Input value={skill.name || '—'} readOnly />
          </Form.Item>
          <Form.Item label="描述">
            <Input.TextArea value={skill.description || '—'} readOnly autoSize={{ minRows: 2, maxRows: 6 }} />
          </Form.Item>
          <Form.Item label="状态">
            <Input
              value={skill.status === 'unknown' ? UNKNOWN_STATUS_TEXT : SKILL_STATUS_LABEL[skill.status]}
              readOnly
            />
          </Form.Item>
          <Form.Item label="许可">
            <Input value={skill.license || '—'} readOnly />
          </Form.Item>
          <Form.Item label="可调用工具">
            <Input value={skill.allowed_tools.join('、') || '—'} readOnly />
          </Form.Item>
          <Form.Item label="来源">
            <Input value={SOURCE_KEY_LABEL[skill.source_key] ?? skill.source_key ?? '—'} readOnly />
          </Form.Item>
          <Form.Item label="提交人">
            <Input value={skill.owner_id || '—'} readOnly />
          </Form.Item>
          <Form.Item label="审核人">
            <Input value={skill.reviewed_by ?? '尚未审核'} readOnly />
          </Form.Item>
          <Form.Item label="更新时间">
            <Input value={skill.updated_at ? formatDateTime(skill.updated_at) : '未设置'} readOnly />
          </Form.Item>
          <Form.Item label="正文">
            <Input.TextArea value={contentBody} readOnly autoSize={{ minRows: 6, maxRows: 16 }} />
          </Form.Item>
        </>
      )}
    </FormDrawer>
  )
}