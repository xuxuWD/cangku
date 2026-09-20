/**
 * 「技能包列表」块：状态标签 + 版本 + 许可 + 工具键 + 提交人 / 审核人 + 管理动作 + 详情。
 *
 * 纪律：
 *  - 四态由 `DataTable` 统一呈现（加载 = 骨架屏，不出现"暂无数据"）；
 *  - 空态文案**必须解释为什么空**（由调用方传入），不显示"0 个"冒充内容；
 *  - 动作按契约 §2 的**合法前置状态**启用；不合法一律 `disabled` + `title` 给原因
 *    （**不静默隐藏**）——`rejected` 是终态，三动作全部不可执行；
 *  - **不能审自己的包**：按「提交人 = 当前登录账号」预置禁用 + 给原因（服务端仍会再判一次 `403`）；
 *  - 未知状态**不误标**成已知状态（中性标签 + "未定义状态"），且动作全部禁用；
 *  - 员工视图（`readOnly`）：四个动作**全部禁用**并给出"由谁执行"的原因 ——
 *    既满足契约 §3「列表只读」，也满足"不静默隐藏"。
 */
import { Button, Space, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable, StatusTag } from '../../../components'
import type { ContentStateKind, StatusTone } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime } from '../../../utils/format'
import {
  SKILL_ACTION_LABEL,
  SKILL_STATUS_LABEL,
  SOURCE_KEY_LABEL,
  UNKNOWN_STATUS_TEXT,
  actionDisabledReason,
} from '../types'
import type { SkillAction, SkillStatus, SkillSummary } from '../types'

/** 状态 → 语义色（未知状态走中性标签，不用语义色）。 */
const STATUS_TONE: Record<Exclude<SkillStatus, 'unknown'>, StatusTone> = {
  submitted: 'info',
  approved: 'success',
  rejected: 'danger',
  enabled: 'success',
  disabled: 'neutral',
}

/** 行内四个管理动作（顺序即展示顺序）。 */
const ROW_ACTIONS: readonly SkillAction[] = ['review_approve', 'review_reject', 'enable', 'disable']

/** 员工视图里每个动作的禁用原因（说明"由谁执行"，不静默隐藏按钮）。 */
export const READ_ONLY_REASON = '复核与启用 / 停用由企业负责人或超级管理员执行；该列表对你只读。'

/** 尚未审核时的如实文案（**不编造审核人**）。 */
export const NOT_REVIEWED_TEXT = '尚未审核'

export interface SkillListPanelProps {
  skills: SkillSummary[]
  state: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry: () => void
  /** 管理视图：动作回调；员工视图（`readOnly`）不传。 */
  onAction?: (action: SkillAction, skill: SkillSummary) => void
  /** 打开详情（按需拉取正文）。 */
  onOpenDetail: (skill: SkillSummary) => void
  /** 列表被单页上限截断时的如实说明。 */
  truncationNote?: string
  /** 正在提交的动作（该行按钮进入 loading / 防重复点击）。 */
  pending?: { skill_key: string; version: string; action: SkillAction } | null
  /** 当前登录账号标识（用于"提交人 = 自己 ⇒ 不能自审"的预置禁用）。 */
  currentUserId?: string | null
  /** 员工视图：整列动作为只读（禁用 + 原因）。 */
  readOnly?: boolean
}

function statusTag(status: SkillStatus) {
  if (status === 'unknown') return <StatusTag tone="neutral">{UNKNOWN_STATUS_TEXT}</StatusTag>
  return <StatusTag tone={STATUS_TONE[status]}>{SKILL_STATUS_LABEL[status]}</StatusTag>
}

/** 单个动作的禁用原因（`null` = 可点击）。 */
export function disabledReasonFor(
  action: SkillAction,
  skill: SkillSummary,
  options: { readOnly: boolean; currentUserId?: string | null },
): string | null {
  if (options.readOnly) return READ_ONLY_REASON
  const stateReason = actionDisabledReason(action, skill.status)
  if (stateReason !== null) return stateReason
  // 生成者 ≠ 评审者：提交人不能审自己的包（服务端 403 的界面预置，口径见契约 §2 / §3）
  if ((action === 'review_approve' || action === 'review_reject') && options.currentUserId) {
    if (skill.owner_id === options.currentUserId) return '不能审核自己提交的技能包（请由其他管理角色审核）。'
  }
  return null
}

export function SkillListPanel({
  skills,
  state,
  stateDescription,
  onRetry,
  onAction,
  onOpenDetail,
  truncationNote,
  pending = null,
  currentUserId = null,
  readOnly = false,
}: SkillListPanelProps) {
  const columns: TableColumnsType<SkillSummary> = [
    {
      title: '技能包',
      key: 'skill_key',
      width: 220,
      render: (_, row) => `${row.skill_key}@${row.version}`,
    },
    { title: '名称', dataIndex: 'name', key: 'name', width: 160 },
    { title: '状态', key: 'status', width: 104, render: (_, row) => statusTag(row.status) },
    {
      title: '许可',
      key: 'license',
      width: 112,
      // 未知许可**原样显示**（不编造含义）
      render: (_, row) => <Tag>{row.license || '—'}</Tag>,
    },
    {
      title: '可调用工具',
      key: 'allowed_tools',
      width: 220,
      render: (_, row) =>
        row.allowed_tools.length === 0 ? (
          <Typography.Text type="secondary">—</Typography.Text>
        ) : (
          <Space size={tokens.spacing.sm} wrap>
            {row.allowed_tools.map((tool) => (
              <Tag key={tool}>{tool}</Tag>
            ))}
          </Space>
        ),
    },
    {
      title: '来源',
      key: 'source_key',
      width: 112,
      // 已知来源给中文标签，未知取值**原样显示**（不编造含义）
      render: (_, row) => <Tag>{SOURCE_KEY_LABEL[row.source_key] ?? row.source_key ?? '—'}</Tag>,
    },
    { title: '提交人', dataIndex: 'owner_id', key: 'owner_id', width: 140 },
    {
      title: '审核人',
      key: 'reviewed_by',
      width: 140,
      render: (_, row) =>
        row.reviewed_by ? row.reviewed_by : <Typography.Text type="secondary">{NOT_REVIEWED_TEXT}</Typography.Text>,
    },
    {
      title: '更新时间',
      key: 'updated_at',
      width: 160,
      render: (_, row) =>
        row.updated_at ? formatDateTime(row.updated_at) : <Typography.Text type="secondary">未设置</Typography.Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      render: (_, row) => {
        const busy = pending?.skill_key === row.skill_key && pending?.version === row.version
        return (
          <Space size={tokens.spacing.sm} wrap>
            <Button size="small" onClick={() => onOpenDetail(row)}>
              详情
            </Button>
            {ROW_ACTIONS.map((action) => {
              const reason = disabledReasonFor(action, row, { readOnly, currentUserId })
              return (
                <Button
                  key={action}
                  size="small"
                  disabled={reason !== null || busy}
                  // 禁用原因必须可见（原生提示），不静默隐藏按钮
                  title={reason ?? undefined}
                  loading={busy && pending?.action === action}
                  onClick={() => onAction?.(action, row)}
                >
                  {SKILL_ACTION_LABEL[action]}
                </Button>
              )
            })}
          </Space>
        )
      },
    },
  ]

  // 就绪但一行没有 ⇒ 交给统一的空态（带"为什么空"的说明），不渲染空表格
  const tableState: ContentStateKind | 'ready' = state === 'ready' && skills.length === 0 ? 'empty' : state

  return (
    <div>
      <Typography.Title level={3}>技能包列表</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        提交后以「已提交」存在；审核通过并启用后才会进入数字员工的工具面（每一步以服务端判定为准）。
      </Typography.Paragraph>
      {truncationNote && (
        <Typography.Paragraph type="secondary" style={{ marginTop: tokens.spacing.sm, marginBottom: 0 }}>
          {truncationNote}
        </Typography.Paragraph>
      )}
      <DataTable<SkillSummary>
        columns={columns}
        rows={skills}
        rowKey={(row) => `${row.skill_key}@${row.version}`}
        state={tableState}
        // 加载态一律用组件的骨架屏：绝不把失败说明用在加载态上
        stateDescription={tableState === 'loading' ? undefined : stateDescription}
        onRetry={onRetry}
        loadingRows={4}
      />
    </div>
  )
}