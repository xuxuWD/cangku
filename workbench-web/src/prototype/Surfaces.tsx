/**
 * B3 原型 · 主区域里的**非对话**页面
 *
 * 规格 §2 表：主区域「**对话常驻** / 其他页面**互斥显示**」——
 * 即这些页面与对话**不会同时出现**（对话被 `display:none`，见 `ConversationSurface`）。
 *
 * ⚠️ **如实说明**：本原型只搭**形态**，这些页面的业务内容**还没有合并进来**
 * （用户要求"不动后端"）。所以未合并的页面**直说未合并**，不摆假数据充数
 * —— 这是项目既有纪律（不摆空入口、不做假空态）。
 */
import { Alert, Button, Card, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { tokens } from '../theme/tokens'
import { OBJECT_BRIEFS, SAMPLE_ATTENTION_SORTED } from './store'
import type { AttentionItem, ObjectBrief } from './store'
import { navigate, routeFor } from './router'
import type { PrototypeView } from './nav'

function PageShell({ title, description, children }: { title: string; description: string; children?: React.ReactNode }) {
  return (
    <section
      data-testid="prototype-page"
      style={{
        height: '100%',
        overflowY: 'auto',
        background: tokens.color.cardBg,
        borderRadius: tokens.radius.card,
        padding: tokens.spacing.lg,
      }}
    >
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        {title}
      </Typography.Title>
      <Typography.Text type="secondary">{description}</Typography.Text>
      <div style={{ marginTop: tokens.spacing.md }}>{children}</div>
    </section>
  )
}

/** 未合并的页面一律**如实说明**，不摆假内容。 */
function NotMergedYet({ name, detail }: { name: string; detail: string }) {
  return (
    <Alert
      type="warning"
      showIcon
      message={`「${name}」尚未合并进本工作台`}
      description={
        <Space direction="vertical" size={2}>
          <span>{detail}</span>
          <span>
            本原型只搭 B3 的**形态**（三栏 / 对话常驻 / 路由），业务页面按 D-050⑤ 逐模块合并，尚未做完。
          </span>
        </Space>
      }
    />
  )
}

/** 待我处理 = 悬浮助手同一份数据源（规格 §13.1 V4 待裁决：是同一数据源还是合并；此处**先同一份**）。 */
export function TodoSurface() {
  const columns: TableColumnsType<AttentionItem> = [
    {
      title: '待办',
      dataIndex: 'title',
      key: 'title',
      render: (_value, item) => <Typography.Text>{item.title}</Typography.Text>,
    },
    {
      title: '类别',
      dataIndex: 'kind',
      key: 'kind',
      width: 110,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_value, item) => (
        <Button
          size="small"
          onClick={() => navigate(routeFor('workitems', item.objectId, 'brief'))}
        >
          打开
        </Button>
      ),
    },
  ]

  return (
    <PageShell
      title="待我处理"
      description="跨模块统一的待办（排序：待审批 > 待输入 > 受阻 > 失败 > 完成）。与右下角悬浮助手**同一份数据源**。"
    >
      <Table<AttentionItem> columns={columns} dataSource={[...SAMPLE_ATTENTION_SORTED]} rowKey={(row) => row.id} pagination={false} />
    </PageShell>
  )
}

export function WorkItemsSurface() {
  const rows = Object.values(OBJECT_BRIEFS)
  const columns: TableColumnsType<ObjectBrief> = [
    { title: '名称', dataIndex: 'title', key: 'title' },
    { title: '类型', dataIndex: 'kind', key: 'kind', width: 90 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_value, item) => (
        <Space>
          <Button size="small" onClick={() => navigate(routeFor('workitems', item.id, 'brief'))}>
            看简要
          </Button>
          <Button size="small" type="link" onClick={() => navigate(routeFor('workitems', item.id, 'employee'))}>
            问员工
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <PageShell
      title="工作项"
      description="任务与运行的统一入口。点一行 ⇒ 右栏出现该对象的简要信息 / 数字员工面板（规格 §5）。"
    >
      <Table<ObjectBrief> columns={columns} dataSource={rows} rowKey={(row) => row.id} pagination={false} />
      <Alert
        style={{ marginTop: tokens.spacing.md }}
        type="info"
        showIcon
        message="下钻代替入口（规格 §7 第 3 步）"
        description="运行详情（admin-web `runDetail`）不再占侧栏入口，而是从对话或工作项**下钻**进来 —— 这正是「侧栏 ≤10」的达成方式之一。"
      />
    </PageShell>
  )
}

export function AgentsSurface() {
  return (
    <PageShell title="我的数字员工" description="「下属」视角：派活给它、看它做到哪一步。">
      <NotMergedYet
        name="我的数字员工（B2 数字员工）"
        detail="该页依赖 B2 规格（Agent + Assignment 两层表、员工侧创建接口、6 类岗位模板、SOUL 层），B2 规格状态为「未评审」，故本原型未实现。"
      />
    </PageShell>
  )
}

export function KnowledgeSurface() {
  return (
    <PageShell title="知识库" description="员工可查、可登记；治理类操作收进设置弹窗。">
      <NotMergedYet
        name="知识库"
        detail="基座已有 `KnowledgePage`（399 行），但按 B3 §10 它属「保留为主界面」还是「进设置」需 B1 §4.2 逐模块归属表勾选后定稿 —— 本原型不预判。"
      />
    </PageShell>
  )
}

export function SimpleSurface({ view }: { view: PrototypeView }) {
  const NAMES: Partial<Record<PrototypeView, { title: string; detail: string }>> = {
    automation: { title: '自动化', detail: '定时与触发规则（B3 §2「更多」子项）。' },
    files: { title: '文件', detail: '产物与文件的统一入口（B3 §2「更多」子项）。' },
    extensions: { title: '扩展', detail: 'Skill & MCP 的**员工侧**入口（管理侧收进设置弹窗）。' },
  }
  const meta = NAMES[view] ?? { title: '页面', detail: '' }
  return (
    <PageShell title={meta.title} description={meta.detail}>
      <NotMergedYet name={meta.title} detail="这是 B3 目标形态里的入口位，但对应业务页面尚未合并。" />
    </PageShell>
  )
}

/** 通用卡片壳：给需要自定义内容的页面用。 */
export function PlainCard({ children }: { children: React.ReactNode }) {
  return <Card size="small">{children}</Card>
}
