/**
 * 组件样品页 —— **仅开发模式（`vite dev`）可见**，入口见 `src/app/navigation.ts` 的 `devOnly`。
 *
 * 用途：第 2 轮组件库的人工抽样审核。每个组件挂一例，顶部开关可统一切换四态。
 * 说明：页面里的数据是**演示用假数据**，不属业务；样品页与导航入口后续轮次可整体移除。
 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Form, Input, Segmented, Space, Switch, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import {
  ContentState,
  DangerConfirm,
  DataTable,
  EmptyState,
  FormDrawer,
  PageContainer,
  PermissionGuard,
  SkeletonList,
  StatCard,
  StatusTag,
} from '../../components'
import type { ContentStateKind, StatusTone } from '../../components'
import { tokens } from '../../theme/tokens'

/** `ready` = 正常渲染内容；其余四种由组件显式呈现。 */
type ViewState = 'ready' | ContentStateKind

const STATE_OPTIONS: { label: string; value: ViewState }[] = [
  { label: '正常', value: 'ready' },
  { label: '加载中', value: 'loading' },
  { label: '空', value: 'empty' },
  { label: '错误', value: 'error' },
  { label: '无权限', value: 'forbidden' },
]

/** 演示用假数据（非业务数据）。 */
interface DemoRow {
  id: string
  name: string
  status: string
  tone: StatusTone
}

const DEMO_ROWS: DemoRow[] = [
  { id: 'demo-1', name: '示例数字员工 A', status: '运行中', tone: 'success' },
  { id: 'demo-2', name: '示例数字员工 B', status: '待确认', tone: 'warning' },
  { id: 'demo-3', name: '示例数字员工 C', status: '已停用', tone: 'neutral' },
]

const DEMO_COLUMNS: TableColumnsType<DemoRow> = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  {
    title: '状态',
    key: 'status',
    render: (_, row) => <StatusTag tone={row.tone}>{row.status}</StatusTag>,
  },
]

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: tokens.spacing.lg }}>
      <Typography.Title level={3}>{title}</Typography.Title>
      {children}
    </div>
  )
}

export function ComponentsPlaygroundPage() {
  const [state, setState] = useState<ViewState>('ready')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [form] = Form.useForm()

  return (
    <PageContainer
      title="组件样品（仅开发可见）"
      description="用于人工抽样审核：顶部开关统一切换四态；hover / focus / active / disabled 由 AntD 原生提供。"
      extra={<Segmented options={STATE_OPTIONS} value={state} onChange={(value) => setState(value as ViewState)} />}
      state={state}
      stateDescription="统一四态开关当前生效（组件样品页自身也走四态）。"
      onRetry={() => setState('ready')}
    >
      <Section title="StatCard：数值与状态保真">
        <Space size={tokens.spacing.md} wrap>
          <StatCard label="本周任务完成数" value={12} unit="条" trend={{ direction: 'up', text: '较上周 +3' }} />
          <StatCard label="平均处理时长" value={undefined} unit="分钟" />
          <StatCard label="满意度评分" presence="not_configured" />
          <StatCard label="转化率" presence="insufficient_sample" />
          <StatCard label="续费率" presence="unverified" />
        </Space>
      </Section>

      <Section title="StatusTag：受控语义色（不能传颜色值）">
        <Space size={tokens.spacing.md} wrap>
          <StatusTag tone="success">成功</StatusTag>
          <StatusTag tone="warning">警告</StatusTag>
          <StatusTag tone="danger">危险</StatusTag>
          <StatusTag tone="neutral">中性</StatusTag>
          <StatusTag tone="info">信息</StatusTag>
          <StatusTag presence="unverified">这条不应出现</StatusTag>
        </Space>
      </Section>

      <Section title="DataTable：列定义泛型 + 分页 + 四态">
        <DataTable<DemoRow>
          columns={DEMO_COLUMNS}
          rows={DEMO_ROWS}
          rowKey={(row) => row.id}
          state={state}
          stateDescription="表格四态示例。"
          onRetry={() => setState('ready')}
        />
      </Section>

      <Section title="DataTable：状态保真（非数值态）">
        <DataTable<DemoRow>
          columns={DEMO_COLUMNS}
          rows={[]}
          rowKey={(row) => row.id}
          presence="insufficient_sample"
        />
      </Section>

      <Section title="SkeletonList：加载中不出现「暂无数据」">
        <SkeletonList rows={3} state={state === 'ready' ? 'loading' : state} />
      </Section>

      <Section title="EmptyState：统一空态文案 + 主操作">
        {/* 开关切到"正常"时，空态样品就展示它自己的默认态（空）。 */}
        <EmptyState
          state={state === 'ready' ? 'empty' : state}
          description="这里还没有内容，可以先创建一条。"
          actionText="新建"
          onAction={() => setState('ready')}
        />
      </Section>

      <Section title="ContentState：四态底座">
        <ContentState state={state === 'ready' ? 'empty' : state} onRetry={() => setState('ready')} />
      </Section>

      <Section title="PermissionGuard：无权限要显式呈现（不静默隐藏）">
        <PermissionGuard capability="agent.manage">
          <Typography.Paragraph>仅具备「数字员工管理」能力的角色可见的内容。</Typography.Paragraph>
        </PermissionGuard>
      </Section>

      <Section title="FormDrawer / DangerConfirm：弹层类">
        <Space size={tokens.spacing.md}>
          <Switch checked={dirty} onChange={setDirty} /> 模拟未保存改动（验证关闭前二次确认）
          <Button type="primary" onClick={() => setDrawerOpen(true)}>
            打开抽屉表单
          </Button>
          <Button danger onClick={() => setConfirmOpen(true)}>
            打开危险操作确认
          </Button>
        </Space>

        <FormDrawer
          open={drawerOpen}
          title="抽屉表单样品"
          form={form}
          dirty={dirty}
          onClose={() => setDrawerOpen(false)}
          onSubmit={() => {
            setDrawerOpen(false)
          }}
        >
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}>
            <Input placeholder="必填项，用于演示校验失败" />
          </Form.Item>
        </FormDrawer>

        <DangerConfirm
          open={confirmOpen}
          title="删除该数字员工？"
          description="删除后该员工的配置与会话记录将不可恢复。"
          confirmWord="删除"
          onConfirm={() => setConfirmOpen(false)}
          onCancel={() => setConfirmOpen(false)}
        />
      </Section>
    </PageContainer>
  )
}