/**
 * 「数字员工绑定」块（第 9 轮）—— 把**已启用**技能绑到数字员工，并预览该员工的工具面。
 *
 * 契约：`docs/contracts/skill-bindings-api.md` §2 / §3。
 *
 * 纪律（逐条对应契约）：
 *  - **读端点仅 `super_admin`**（§1/§7）：非 `super_admin`（`ceo`）**不请求绑定数据**，
 *    只给"由超级管理员执行"的原因 + 禁用控件（不静默隐藏）；
 *  - **界面自我收敛**：技能候选**只给 `enabled`**；员工候选**只给目录**——
 *    **第 12 轮 ③A 起取消"手动录入"**（服务端要求员工键已纳管且启用，目录外的键 ⇒ `409`），
 *    目录为空时给出"先去纳管"的引导而不是留一个能输入的下拉；
 *  - **解绑走二次确认**（会立即移出工具面），绑定为新增放行、不二次确认；
 *  - 写成功只用**服务端回读值**提示；写失败**就地呈现服务端原文**并说明"没有改变任何绑定"；
 *  - 工具面「为什么空」**三种归因分开说明**（§3），不允许合并成"暂无工具"。
 */
import { useState } from 'react'
import { Alert, Button, Form, Select, Space, Tag, Typography } from 'antd'
import { DangerConfirm, DataTable, StatusTag } from '../../../components'
import type { ContentStateKind, StatusTone } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime } from '../../../utils/format'
import { usePanelData } from '../../../utils/panelData'
import {
  AGENT_CANDIDATE_EMPTY_NOTE,
  AGENT_DIRECTORY_ONLY_NOTE,
  BINDINGS_EMPTY_NOTE,
  BIND_NO_ENABLED_SKILL_NOTE,
  BIND_SKILL_HINT,
  MOCK_AGENT_TOOLS_NOTE,
  UNBIND_CONFIRM_DESCRIPTION,
  UNBIND_CONFIRM_TITLE,
  WRITE_FAILURE_HINT,
  bindAgentSkill,
  fetchAgentCandidates,
  fetchAgentTools,
  fetchBindings,
  fetchSkills,
  panelStateOfError,
  SkillError,
  unbindAgentSkill,
} from '../services/skillsService'
import {
  AGENT_TOOLS_REASON_TEXT,
  BINDING_STATUS_LABEL,
  agentToolsReason,
} from '../types'
import type { AgentCandidatePage, BindingStatus, SkillBinding, SkillBindingPage, SkillPage } from '../types'

const EMPTY_BINDINGS: SkillBindingPage = { sample: true, items: [], total: 0, limit: 0, offset: 0 }
const EMPTY_SKILLS: SkillPage = { sample: true, items: [], total: 0, limit: 0, offset: 0 }
const EMPTY_CANDIDATES: AgentCandidatePage = { sample: true, items: [], total: 0 }

/** 非 `super_admin` 的禁用原因（`ceo` 会看到；不静默隐藏控件）。 */
export const BIND_DISABLED_REASON = '绑定 / 解绑由超级管理员执行。'

/** 员工视图里的整块说明（属治理面，**不请求任何数据**）。 */
export const BINDING_GOVERNANCE_ONLY_NOTE = '技能与数字员工的绑定属治理面，仅超级管理员可用。'

/** 职责说明（页面级提示，避免把绑定误解成"授权给某人"）。 */
export const BINDING_SCOPE_NOTE =
  '绑定决定该数字员工实际可调用的工具面：只有「已启用」技能声明的工具（与执行目录取交集）才生效。'

/** 状态 → 语义色（未知状态走中性标签，不用语义色）。 */
const STATUS_TONE: Record<Exclude<BindingStatus, 'unknown'>, StatusTone> = {
  active: 'success',
  disabled: 'neutral',
}

/** 写失败提示（分类已在服务层映射；`forbidden` 单列，其余统一"没有写入任何数据"）。 */
function failureHint(error: unknown): string {
  if (error instanceof SkillError && error.kind === 'forbidden') return WRITE_FAILURE_HINT.forbidden
  if (error instanceof SkillError && error.kind === 'not_found') return WRITE_FAILURE_HINT.not_found
  return WRITE_FAILURE_HINT.failed
}

function messageOf(error: unknown): string {
  return error instanceof Error && error.message.length > 0 ? error.message : WRITE_FAILURE_HINT.failed
}

interface BindFormValues {
  /** 第 12 轮起员工键**只能从目录选**（服务端要求已纳管且启用）⇒ 单选值。 */
  agent_key?: string
  skill_key?: string
}

export interface BindingPanelProps {
  /** 是否可绑定（能力 `skill.bind`：仅 `super_admin`）。为 `false` 时**不请求绑定数据**。 */
  canBind: boolean
}

export function BindingPanel({ canBind }: BindingPanelProps) {
  const [form] = Form.useForm<BindFormValues>()
  const [notice, setNotice] = useState<string | null>(null)
  const [writeError, setWriteError] = useState<{ message: string; hint: string } | null>(null)
  const [pending, setPending] = useState(false)
  const [unbindTarget, setUnbindTarget] = useState<SkillBinding | null>(null)
  const [toolsTarget, setToolsTarget] = useState<string | null>(null)
  const [toolsFor, setToolsFor] = useState<{ agent_key: string; tools: string[] } | null>(null)
  const [toolsState, setToolsState] = useState<ContentStateKind | 'ready'>('loading')
  const [toolsNote, setToolsNote] = useState<string>('')

  /** 是否请求真实数据：`canBind` 为假时**一律不请求**（无权限的块不伪造空态）。 */
  const active = canBind

  const bindings = usePanelData(() => (active ? fetchBindings() : Promise.resolve(EMPTY_BINDINGS)), EMPTY_BINDINGS)
  const skills = usePanelData(() => (active ? fetchSkills() : Promise.resolve(EMPTY_SKILLS)), EMPTY_SKILLS)
  const candidates = usePanelData(
    () => (active ? fetchAgentCandidates() : Promise.resolve(EMPTY_CANDIDATES)),
    EMPTY_CANDIDATES,
  )

  const bindingsState: ContentStateKind | 'ready' =
    bindings.state === 'ready' && bindings.data.items.length === 0 ? 'empty' : bindings.state
  const bindingsStateText: Record<Exclude<ContentStateKind, 'loading'>, string> = {
    empty: BINDINGS_EMPTY_NOTE,
    error: '绑定关系加载失败，请稍后重试。',
    forbidden: '无权限查看绑定关系：该列表仅超级管理员可读。',
  }

  const enabledSkills = skills.data.items.filter((item) => item.status === 'enabled')

  const refresh = () => {
    bindings.reload()
    skills.reload()
  }

  const handleBind = async (values: BindFormValues) => {
    const agentKey = (values.agent_key ?? '').trim()
    setNotice(null)
    setWriteError(null)
    setPending(true)
    try {
      const result = await bindAgentSkill(values.skill_key ?? '', agentKey)
      if (result.written && result.result) {
        // 提示只用**服务端回读值**（技能键 / 员工键 / 状态都取自响应）
        setNotice(
          `已绑定：${result.result.skill_key} → ${result.result.agent_key}（状态：${BINDING_STATUS_LABEL.active}）。`,
        )
        form.resetFields()
        refresh()
      } else {
        setNotice(result.note)
      }
    } catch (error) {
      setWriteError({ message: `未能完成绑定：${messageOf(error)}`, hint: failureHint(error) })
    } finally {
      setPending(false)
    }
  }

  const openTools = async (agentKey: string) => {
    setToolsTarget(agentKey)
    setToolsFor(null)
    setToolsState('loading')
    setToolsNote('')
    try {
      const outcome = await fetchAgentTools(agentKey)
      if (outcome.sample || !outcome.tools) {
        // 样例模式：没有请求服务端 ⇒ 如实说明，**不编造工具清单**
        setToolsState('empty')
        setToolsNote(outcome.note || MOCK_AGENT_TOOLS_NOTE || '本条没有可展示的工具面。')
        setToolsFor({ agent_key: agentKey, tools: [] })
        return
      }
      setToolsFor(outcome.tools)
      setToolsState('ready')
    } catch (error) {
      setToolsState(panelStateOfError(error))
      setToolsNote(messageOf(error))
    }
  }

  const handleUnbindConfirmed = async () => {
    const target = unbindTarget
    setUnbindTarget(null)
    if (!target) return
    setNotice(null)
    setWriteError(null)
    setPending(true)
    try {
      const result = await unbindAgentSkill(target.skill_key, target.agent_key)
      if (result.written && result.result) {
        setNotice(
          `已解除：${result.result.skill_key} → ${result.result.agent_key}（状态：${BINDING_STATUS_LABEL.disabled}）。`,
        )
        refresh()
      } else {
        setNotice(result.note)
      }
    } catch (error) {
      setWriteError({ message: `未能完成解绑：${messageOf(error)}`, hint: failureHint(error) })
    } finally {
      setPending(false)
    }
  }

  /** 当前预览的工具面归因（三种空因分开；归因用真实数据算，不用猜）。 */
  const toolsReason =
    toolsFor === null
      ? null
      : agentToolsReason({
          agentKey: toolsFor.agent_key,
          bindings: bindings.data.items,
          skills: skills.data.items,
          tools: toolsFor.tools,
        })

  return (
    <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
      <div>
        <Typography.Title level={3}>数字员工绑定</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {BINDING_SCOPE_NOTE}
        </Typography.Paragraph>
      </div>

      {!canBind && <Alert type="info" showIcon message={BIND_DISABLED_REASON} />}

      {notice && <Alert type="info" showIcon message={notice} />}
      {writeError && <Alert type="error" showIcon message={writeError.message} description={writeError.hint} />}

      <Form<BindFormValues> form={form} layout="inline" disabled={!canBind || pending} onFinish={handleBind}>
        <Form.Item
          label="技能包"
          name="skill_key"
          rules={[{ required: true, message: '请选择要绑定的技能包' }]}
          extra={BIND_SKILL_HINT}
        >
          <Select
            style={{ minWidth: 240 }}
            placeholder="仅可选择「已启用」的技能包"
            options={enabledSkills.map((item) => ({
              value: item.skill_key,
              label: `${item.skill_key}@${item.version}`,
            }))}
            notFoundContent={BIND_NO_ENABLED_SKILL_NOTE}
            disabled={!canBind || pending || enabledSkills.length === 0}
          />
        </Form.Item>

        <Form.Item
          label="数字员工标识"
          name="agent_key"
          rules={[{ required: true, message: '请选择要绑定的数字员工' }]}
          extra={AGENT_DIRECTORY_ONLY_NOTE}
        >
          <Select
            style={{ minWidth: 240 }}
            placeholder="只能选择已纳管的数字员工"
            options={candidates.data.items.map((item) => ({
              value: item.agent_key,
              label: item.name ? `${item.name}（${item.agent_key}）` : item.agent_key,
            }))}
            notFoundContent={AGENT_CANDIDATE_EMPTY_NOTE}
            disabled={!canBind || pending}
          />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={pending} disabled={!canBind}>
            绑定
          </Button>
        </Form.Item>
      </Form>

      <DataTable<SkillBinding>
        columns={[
          { title: '技能包', dataIndex: 'skill_key', key: 'skill_key', width: 200 },
          { title: '数字员工', dataIndex: 'agent_key', key: 'agent_key', width: 200 },
          {
            title: '状态',
            key: 'status',
            width: 104,
            render: (_, row) =>
              row.status === 'unknown' ? (
                <StatusTag tone="neutral">未定义状态</StatusTag>
              ) : (
                <StatusTag tone={STATUS_TONE[row.status]}>{BINDING_STATUS_LABEL[row.status]}</StatusTag>
              ),
          },
          { title: '建立人', dataIndex: 'created_by', key: 'created_by', width: 160 },
          {
            title: '建立时间',
            key: 'created_at',
            width: 160,
            render: (_, row) =>
              row.created_at ? (
                formatDateTime(row.created_at)
              ) : (
                <Typography.Text type="secondary">未设置</Typography.Text>
              ),
          },
          {
            title: '操作',
            key: 'action',
            width: 200,
            render: (_, row) => (
              <Space size={tokens.spacing.sm} wrap>
                <Button size="small" onClick={() => void openTools(row.agent_key)}>
                  查看工具面
                </Button>
                <Button
                  size="small"
                  danger
                  disabled={!canBind || pending || row.status !== 'active'}
                  title={
                    !canBind
                      ? BIND_DISABLED_REASON
                      : row.status === 'active'
                        ? undefined
                        : '该绑定已解除，无需重复解绑。'
                  }
                  onClick={() => setUnbindTarget(row)}
                >
                  解绑
                </Button>
              </Space>
            ),
          },
        ]}
        rows={bindings.data.items}
        rowKey={(row) => `${row.agent_key}/${row.skill_key}`}
        state={bindingsState}
        stateDescription={
          bindingsState === 'loading' || bindingsState === 'ready' ? undefined : bindingsStateText[bindingsState]
        }
        onRetry={bindings.reload}
        loadingRows={3}
      />

      {toolsTarget !== null && (
        <div>
          <Typography.Title level={4}>工具面预览：{toolsTarget}</Typography.Title>
          {toolsState === 'loading' && <Typography.Text type="secondary">正在加载工具面…</Typography.Text>}
          {toolsState === 'error' && (
            <Alert
              type="error"
              showIcon
              message="工具面加载失败"
              description={toolsNote}
              action={<Button size="small" onClick={() => void openTools(toolsTarget)}>重试</Button>}
            />
          )}
          {toolsState === 'forbidden' && (
            <Alert type="warning" showIcon message="无权限查看工具面" description={toolsNote} />
          )}
          {toolsState === 'empty' && <Alert type="info" showIcon message={toolsNote} />}
          {toolsState === 'ready' && toolsFor && toolsReason === 'ready' && (
            <Space size={tokens.spacing.sm} wrap>
              {toolsFor.tools.map((tool) => (
                <Tag key={tool}>{tool}</Tag>
              ))}
            </Space>
          )}
          {toolsState === 'ready' && toolsReason !== null && toolsReason !== 'ready' && (
            <Alert type="info" showIcon message={AGENT_TOOLS_REASON_TEXT[toolsReason]} />
          )}
          <div style={{ marginTop: tokens.spacing.sm }}>
            <Button size="small" onClick={() => setToolsTarget(null)}>
              收起
            </Button>
          </div>
        </div>
      )}

      <DangerConfirm
        open={unbindTarget !== null}
        title={UNBIND_CONFIRM_TITLE}
        description={UNBIND_CONFIRM_DESCRIPTION}
        confirmWord="解绑"
        confirmText="确认解绑"
        onConfirm={handleUnbindConfirmed}
        onCancel={() => setUnbindTarget(null)}
      />
    </Space>
  )
}