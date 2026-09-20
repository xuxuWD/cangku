/**
 * Skill & MCP（第 8 轮建立 · **按矩阵 §3「技能」两行分视图**）。
 *
 * 两块：① 技能包列表（含提交） ② MCP 说明（**后端零实现** ⇒ 如实呈现「尚未接入」）。
 * 四态：加载 / 空 / 错误（可重试）/ 无权限。
 *
 * **视图按能力分流**（口径 = `permission-matrix.md` §3；后端同口径见 `app/skills/models.py`）：
 *  - `skill.manage`（`ceo` / `super_admin`）⇒ **管理视图**：全量列表 + 审核（通过 / 退回）+ 启用 / 停用 + 详情正文；
 *  - `skill.submit`（`employee` / `department_lead`）⇒ **员工视图**：提交表单 + 本人可见的只读列表
 *    （动作用**禁用 + 原因**呈现，不静默隐藏，也不放开点击）；
 *  - 都没有（`customer_admin`）⇒ 整页无权限态 + 原因，且**不请求任何数据**。
 *
 * 纪律：
 *  - 本页**只做呈现**：隐藏 / 禁用 / 无权限态都只是体验，真正的判定在服务端（每个请求都会再判一次）；
 *  - 动作按契约 §2 的**合法前置状态**启用；不合法一律**禁用 + 给原因**，不静默隐藏；
 *  - **不能审自己的包**：按"提交人 = 当前登录账号"预置禁用 + 原因（服务端仍会再判 `403`）；
 *  - 写成功后才重新取数，且提示只用**服务端回读值**（不本地猜结果）；
 *  - 写失败就地呈现、抽屉不关闭、**不假装成功**（服务端拒绝时如实呈现其原文）。
 */
import { useState } from 'react'
import { Alert, Button, Form, Space, Typography } from 'antd'
import { hasCapability, useSession } from '../../app/session'
import { ContentState, PageContainer } from '../../components'
import type { ContentStateKind } from '../../components'
import { usePanelData } from '../../utils/panelData'
import { SAMPLE_DATA_BADGE } from '../../utils/serviceKit'
import { tokens } from '../../theme/tokens'
import { McpPanel } from './components/McpPanel'
import { BINDING_GOVERNANCE_ONLY_NOTE, BindingPanel } from './components/BindingPanel'
import { SkillDetailDrawer } from './components/SkillDetailDrawer'
import { SkillListPanel } from './components/SkillListPanel'
import { SubmitSkillDrawer } from './components/SubmitSkillDrawer'
import {
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  MY_SKILLS_EMPTY_NOTE,
  SAMPLE_DESCRIPTION,
  SKILLS_EMPTY_NOTE,
  SKILLS_LIMIT,
  SkillError,
  WRITE_FAILURE_HINT,
  disableSkill,
  enableSkill,
  fetchSkills,
  isConnected,
  reviewSkill,
  submitSkill,
  truncationNote,
} from './services/skillsService'
import {
  SKILL_ACTION_DONE_LABEL,
  SKILL_STATUS_LABEL,
  UNKNOWN_STATUS_TEXT,
  reviewApprovedValue,
} from './types'
import type { SkillAction, SkillPage, SkillStatus, SkillSummary, SubmitSkillInput } from './types'

const EMPTY_SKILLS: SkillPage = { sample: true, items: [], total: 0, limit: 0, offset: 0 }

/** 各块的非就绪文案（唯一来源在此，组件不另写一套）。 */
const SKILLS_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: SKILLS_EMPTY_NOTE,
  error: '技能包列表加载失败，请稍后重试。',
  forbidden: '无权限查看技能包列表：技能入口不向客户管理员开放。',
}

/**
 * 无权限原因（`customer_admin` 等无任何技能能力的角色）。
 * 措辞逐条对应 `permission-matrix.md` §3「技能」两行，不夸大也不含糊。
 */
export const PERMISSION_REASON =
  'Skill & MCP 不向客户管理员开放：技能包提交面向员工、部门负责人、企业负责人与超级管理员；审核与启用 / 停用仅企业负责人与超级管理员可用。'

/** 员工视图里对"复核 / 启停"的说明（动作以禁用 + 原因呈现，不静默隐藏）。 */
export const MEMBER_REVIEW_ONLY_NOTE =
  '你提交的技能包由企业负责人或超级管理员审核；审核通过并启用后才会进入数字员工的工具面。'

/** 状态标签文案（未知状态不误标）。 */
function statusLabel(status: SkillStatus): string {
  return status === 'unknown' ? UNKNOWN_STATUS_TEXT : SKILL_STATUS_LABEL[status]
}

function messageOf(error: unknown): string {
  return error instanceof Error && error.message.length > 0 ? error.message : WRITE_FAILURE_HINT.failed
}

/** 就绪 / 加载中不给说明（加载态一律走骨架屏，不显示失败或空态文案）。 */
function stateText(
  table: Record<Exclude<ContentStateKind, 'loading'>, string>,
  state: ContentStateKind | 'ready',
): string | undefined {
  if (state === 'ready' || state === 'loading') return undefined
  return table[state]
}

/** 写失败的分类提示（`forbidden` 时说明"没有写入任何数据"并给出角色线索）。 */
function failureHint(error: unknown): string {
  if (error instanceof SkillError) return WRITE_FAILURE_HINT[error.kind]
  return WRITE_FAILURE_HINT.failed
}

/**
 * 「提交技能包」块（两个视图**共用**）。
 * 成功只用**服务端回读值**提示；失败就地呈现、抽屉不关闭、不假装成功。
 */
function SubmitBlock({ onSubmitted }: { onSubmitted?: () => void }) {
  const [form] = Form.useForm<SubmitSkillInput>()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<{ message: string; hint: string } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const handleSubmit = async (input: SubmitSkillInput) => {
    setError(null)
    setNotice(null)
    try {
      const result = await submitSkill(input)
      setOpen(false)
      form.resetFields()
      if (result.written && result.skill) {
        // 提示只用**服务端回读值**（标识、版本与状态都取自响应）
        setNotice(
          `已提交：「${result.skill.skill_key}@${result.skill.version}」（当前状态：${statusLabel(result.skill.status)}）。`,
        )
        onSubmitted?.()
      } else {
        // 样例模式：没有写入任何数据，也就没有可刷新的服务端变化（如实说明，不假装已保存）
        setNotice(result.note)
      }
    } catch (caught) {
      // 失败就地呈现、抽屉留在原地（不关抽屉、不假装成功）
      setError({ message: messageOf(caught), hint: failureHint(caught) })
    }
  }

  return (
    <>
      {notice && <Alert type="info" showIcon message={notice} />}
      <div style={{ marginBottom: tokens.spacing.sm }}>
        <Button type="primary" onClick={() => setOpen(true)}>
          提交技能包
        </Button>
      </div>
      <SubmitSkillDrawer
        open={open}
        form={form}
        error={error}
        onClose={() => {
          setOpen(false)
          setError(null)
        }}
        onSubmit={handleSubmit}
      />
    </>
  )
}

/** 绑定面限定块：**只给说明，不发任何请求**（无权读的块不伪造空态，也不静默隐藏）。 */
function BindingOnlyBlock() {
  return (
    <div>
      <Typography.Title level={3}>数字员工绑定</Typography.Title>
      <ContentState state="forbidden" description={BINDING_GOVERNANCE_ONLY_NOTE} boxed={false} />
    </div>
  )
}

/** 管理视图（`skill.manage`：`ceo` / `super_admin`）。 */
function SkillsBoard({ currentUserId, canBind }: { currentUserId: string | null; canBind: boolean }) {
  const connected = isConnected()
  const skills = usePanelData(() => fetchSkills(), EMPTY_SKILLS)

  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<{ message: string; hint: string } | null>(null)
  const [pending, setPending] = useState<{ skill_key: string; version: string; action: SkillAction } | null>(null)
  const [detail, setDetail] = useState<SkillSummary | null>(null)

  const runAction = async (action: SkillAction, skill: SkillSummary) => {
    setNotice(null)
    setActionError(null)
    setPending({ skill_key: skill.skill_key, version: skill.version, action })
    try {
      const result =
        action === 'review_approve' || action === 'review_reject'
          ? await reviewSkill(skill.skill_key, skill.version, reviewApprovedValue(action))
          : action === 'enable'
            ? await enableSkill(skill.skill_key, skill.version)
            : await disableSkill(skill.skill_key, skill.version)
      if (result.written && result.skill) {
        setNotice(
          `${SKILL_ACTION_DONE_LABEL[action]}：「${result.skill.skill_key}@${result.skill.version}」（当前状态：${statusLabel(result.skill.status)}）。`,
        )
        skills.reload()
      } else {
        setNotice(result.note)
      }
    } catch (error) {
      setActionError({ message: `未能完成操作：${messageOf(error)}`, hint: failureHint(error) })
    } finally {
      setPending(null)
    }
  }

  return (
    <Space direction="vertical" size={tokens.spacing.lg} style={{ width: '100%' }}>
      {connected ? (
        <Alert type="info" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
      ) : (
        <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
      )}

      {notice && <Alert type="info" showIcon message={notice} />}
      {actionError && (
        <Alert type="error" showIcon message={actionError.message} description={actionError.hint} />
      )}

      <div>
        <SubmitBlock onSubmitted={skills.reload} />
        <SkillListPanel
          skills={skills.data.items}
          // 就绪但一行没有 ⇒ 该块进入"空"态，并由本页给出「为什么空」的说明
          state={skills.state === 'ready' && skills.data.items.length === 0 ? 'empty' : skills.state}
          stateDescription={stateText(
            SKILLS_STATE_TEXT,
            skills.state === 'ready' && skills.data.items.length === 0 ? 'empty' : skills.state,
          )}
          onRetry={skills.reload}
          onAction={(action, skill) => void runAction(action, skill)}
          onOpenDetail={setDetail}
          truncationNote={truncationNote(skills.data.total, skills.data.items.length)}
          pending={pending}
          currentUserId={currentUserId}
        />
      </div>

      <BindingPanel canBind={canBind} />

      <McpPanel />

      <SkillDetailDrawer skill={detail} onClose={() => setDetail(null)} />
    </Space>
  )
}

/**
 * 员工视图（`skill.submit`：`employee` / `department_lead`）。
 *
 * 与治理台的差异：① 列表**只读**（动作用禁用 + 原因呈现，不放开点击）；
 * ② 空态按"本人可见范围"解释；③ 不展示治理动作的完成提示（没有可执行的动作）。
 */
function SkillMemberView({ currentUserId }: { currentUserId: string | null }) {
  const connected = isConnected()
  const skills = usePanelData(() => fetchSkills({ limit: SKILLS_LIMIT }), EMPTY_SKILLS)
  const [detail, setDetail] = useState<SkillSummary | null>(null)

  const memberStateText: Record<Exclude<ContentStateKind, 'loading'>, string> = {
    empty: MY_SKILLS_EMPTY_NOTE,
    error: '技能包列表加载失败，请稍后重试。',
    forbidden: '无权限查看技能包列表。',
  }

  return (
    <Space direction="vertical" size={tokens.spacing.lg} style={{ width: '100%' }}>
      {connected ? (
        <Alert type="info" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
      ) : (
        <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
      )}

      <div>
        <SubmitBlock onSubmitted={skills.reload} />
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {MEMBER_REVIEW_ONLY_NOTE}
        </Typography.Paragraph>
      </div>

      <SkillListPanel
        skills={skills.data.items}
        // 就绪但一行没有 ⇒ 该块进入"空"态，并由本页给出「为什么空」的说明
        state={skills.state === 'ready' && skills.data.items.length === 0 ? 'empty' : skills.state}
        stateDescription={stateText(
          memberStateText,
          skills.state === 'ready' && skills.data.items.length === 0 ? 'empty' : skills.state,
        )}
        onRetry={skills.reload}
        onOpenDetail={setDetail}
        truncationNote={truncationNote(skills.data.total, skills.data.items.length)}
        currentUserId={currentUserId}
        readOnly
      />

      <BindingOnlyBlock />

      <McpPanel />

      <SkillDetailDrawer skill={detail} onClose={() => setDetail(null)} />
    </Space>
  )
}

export function SkillsMcpPage() {
  const role = useSession((state) => state.role)
  const userId = useSession((state) => state.userId)
  const canManage = hasCapability(role, 'skill.manage')
  const canSubmit = hasCapability(role, 'skill.submit')
  const canBind = hasCapability(role, 'skill.bind')

  const description = canManage
    ? '审核、启用与停用本租户的技能包，并可查看技能包正文；技能包由员工提交后进入这里。'
    : '提交你自带的技能包，并查看当前可见的技能包；审核与启用 / 停用由企业负责人或超级管理员执行。'

  return (
    <PageContainer title="Skill & MCP" description={description}>
      {canManage ? (
        <SkillsBoard currentUserId={userId} canBind={canBind} />
      ) : canSubmit ? (
        <SkillMemberView currentUserId={userId} />
      ) : (
        /* 无任何技能能力（如 customer_admin）：整页无权限态 + 原因，不请求数据、不渲染编辑控件 */
        <ContentState state="forbidden" description={PERMISSION_REASON} />
      )}
    </PageContainer>
  )
}