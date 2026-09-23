/**
 * 通知（收件箱）—— 由 `admin-web/src/features/inbox/InboxPage.tsx` 合并移植到基座。
 *
 * **本轮移植口径（如实登记）**：
 *  - 业务能力**等价保留**：列表 / 「全部·未读」筛选 / 未读计数 / 单条标已读 / 全部标已读 / 四态；
 *  - 呈现层从 admin-web 的**手写组件 + 手写 CSS**（`.t3` / `.card` / `.rows` / `.btn`）换成
 *    **AntD + 项目组件库**（`PageContainer` / `DataTable` / `StatCard` / `StatusTag`），
 *    符合 ADR-0003「采纳 AntD 5 + ProComponents」与「禁止用 div 模拟按钮/表格」；
 *  - 传输层从 admin-web 的自写 `fetch` 换成全前端唯一请求层（见 `services/inboxService.ts`）；
 *  - **目标落点（2026-09-23 换壳后更新）**：完整页面（任务详情 / 运行详情）**尚未合并**，
 *    但壳有了**右栏「当前对象」**（B3 §5）⇒ 每行给出「在右栏查看」，把该对象**上报**给壳
 *    （`shellStore.showObject`，顺带把 `?object=` 写进 URL ⇒ 可分享）。
 *    **两句话同时在**：能看摘要在右栏、看全页还不行（见 `destinations.ts`）。
 *
 * 纪律：
 *  - 「全部 / 未读」是**纯前端筛选**（只作用于已加载的那一页），不改变任何服务端语义；
 *  - 「未读」档下"一条都没有"与"筛选没命中"是**两种不同空态**，文案必须分开；
 *  - 写侧（标已读）成功后**以服务端回读为准**（重新取数），不在前端拼装乐观结果；
 *  - 失败一律按四态呈现，**不得**把加载失败说成"没有通知"。
 */
import { useMemo, useState } from 'react'
import { Alert, Button, Segmented, Space, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable, PageContainer, StatCard, StatusTag } from '../../components'
import type { ContentStateKind } from '../../components'
import { formatDateTime } from '../../utils/format'
import { usePanelData } from '../../utils/panelData'
import { showObject } from '../../app/shellStore'
import { resolveInboxDestination } from './destinations'
import {
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  EMPTY_INBOX,
  INBOX_EMPTY_NOTE,
  INBOX_NO_UNREAD_NOTE,
  SAMPLE_DATA_BADGE,
  SAMPLE_DESCRIPTION,
  fetchInbox,
  isConnected,
  markAllInboxRead,
  markInboxRead,
} from './services/inboxService'
import { inboxKindLabel } from './types'
import type { InboxFilter, InboxItem } from './types'

/** 列表非就绪态的文案（唯一来源在此，组件不另写一套）。 */
const LIST_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: INBOX_EMPTY_NOTE,
  error: '通知加载失败，请稍后重试。',
  forbidden: '当前账号没有查看通知的权限。',
}

export function InboxPage() {
  const connected = isConnected()
  const [filter, setFilter] = useState<InboxFilter>('all')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [markingAll, setMarkingAll] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [writeError, setWriteError] = useState<string | null>(null)

  const inbox = usePanelData(() => fetchInbox(false), EMPTY_INBOX)
  const { state, data, reload } = inbox

  // 「未读」档只看已加载 items 里 read_at === null 的行，纯前端筛选。
  const visibleItems = useMemo(
    () => (filter === 'unread' ? data.items.filter((item) => item.read_at === null) : data.items),
    [filter, data.items],
  )

  // 空态有**两种**，必须分开：库里有通知但都被筛掉 ≠ 一条通知都没有。
  const hasNoItems = data.items.length === 0
  const filteredOut = !hasNoItems && visibleItems.length === 0
  // `DataTable` 只在 `state === 'empty'` 时才走统一空态，所以这里要把"就绪但没内容"显式转成 `empty`，
  // 否则会落到 AntD 表格自带的"暂无数据"，本页的空态文案就永远显示不出来（阶段 1 用例发现）。
  const listState: ContentStateKind | 'ready' =
    state !== 'ready' ? state : hasNoItems || filteredOut ? 'empty' : 'ready'
  const listStateDescription =
    state !== 'ready'
      ? LIST_STATE_TEXT[state as Exclude<ContentStateKind, 'loading'>]
      : hasNoItems
        ? INBOX_EMPTY_NOTE
        : INBOX_NO_UNREAD_NOTE

  const handleMarkRead = async (item: InboxItem) => {
    setBusyId(item.inbox_id)
    setNotice(null)
    setWriteError(null)
    try {
      await markInboxRead(item.inbox_id)
      setNotice('已标记为已读。')
      reload() // 以服务端回读为准，不在前端拼装乐观结果
    } catch (error) {
      setWriteError(error instanceof Error ? error.message : '标记已读失败，请稍后重试。')
    } finally {
      setBusyId(null)
    }
  }

  const handleMarkAll = async () => {
    setMarkingAll(true)
    setNotice(null)
    setWriteError(null)
    try {
      const result = await markAllInboxRead()
      setNotice(`已全部标记为已读（${result.updated} 条）。`)
      reload()
    } catch (error) {
      setWriteError(error instanceof Error ? error.message : '全部标记已读失败，请稍后重试。')
    } finally {
      setMarkingAll(false)
    }
  }

  const columns: TableColumnsType<InboxItem> = [
    {
      title: '通知',
      dataIndex: 'title',
      key: 'title',
      render: (_value, item) => {
        const destination = resolveInboxDestination(item)
        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <Typography.Text strong={item.read_at === null}>{item.title}</Typography.Text>
            {/* 两句话必须同时在：右栏**能**看摘要、完整页面**还**不行 */}
            {destination.note && <Typography.Text type="secondary">{destination.note}</Typography.Text>}
            {destination.canPreview && destination.label && (
              <Button
                size="small"
                onClick={() =>
                  // 把对象**上报**给壳（B3 §5）：右栏显示它，并把 `?object=` 写进 URL ⇒ 可分享
                  showObject(
                    {
                      id: String(item.target_id),
                      type: item.target_type ?? 'task',
                      title: item.title,
                      status: item.read_at === null ? '未读' : '已读',
                    },
                    { view: 'inbox', panel: 'brief' },
                  )
                }
              >
                {destination.label}
              </Button>
            )}
          </Space>
        )
      },
    },
    {
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      width: 160,
      render: (_value, item) => <Typography.Text>{inboxKindLabel(item.kind)}</Typography.Text>,
    },
    {
      title: '状态',
      dataIndex: 'read_at',
      key: 'read_at',
      width: 90,
      render: (_value, item) =>
        item.read_at === null ? <StatusTag tone="info">未读</StatusTag> : <StatusTag tone="neutral">已读</StatusTag>,
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value: string) => <Typography.Text type="secondary">{formatDateTime(value)}</Typography.Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_value, item) =>
        item.read_at === null ? (
          <Button
            size="small"
            loading={busyId === item.inbox_id}
            onClick={() => void handleMarkRead(item)}
          >
            标为已读
          </Button>
        ) : null,
    },
  ]

  return (
    <PageContainer
      title="通知"
      description="审批结果与运行结果会记录在这里；标记已读只影响你自己的收件箱。"
      extra={
        <Space>
          <Button onClick={reload} disabled={state === 'loading'}>
            {state === 'loading' ? '正在刷新' : '刷新'}
          </Button>
          <Button
            type="primary"
            loading={markingAll}
            disabled={state !== 'ready' || data.unread_count === 0}
            onClick={() => void handleMarkAll()}
          >
            全部标记已读
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {/* 数据来源如实标注：样例模式与已接入**互斥**显示，不含糊 */}
        {connected ? (
          <Alert type="success" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
        ) : (
          SAMPLE_DATA_BADGE !== '' && (
            <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
          )
        )}

        {notice && <Alert type="success" showIcon message={notice} closable onClose={() => setNotice(null)} />}
        {writeError && <Alert type="error" showIcon message={writeError} closable onClose={() => setWriteError(null)} />}

        <Space size="middle" wrap>
          <StatCard
            label="未读"
            value={data.unread_count}
            state={state}
            onRetry={reload}
          />
          <StatCard
            label="本页共"
            value={data.items.length}
            state={state}
            onRetry={reload}
          />
        </Space>

        <Space align="center" size="middle" wrap>
          <Segmented<InboxFilter>
            value={filter}
            onChange={setFilter}
            options={[
              { label: '全部', value: 'all' },
              { label: '未读', value: 'unread' },
            ]}
          />
          <Typography.Text type="secondary">未读通知 {data.unread_count} 条</Typography.Text>
        </Space>

        <DataTable<InboxItem>
          columns={columns}
          rows={visibleItems}
          rowKey={(row) => row.inbox_id}
          state={listState}
          stateDescription={listStateDescription}
          onRetry={reload}
        />
      </Space>
    </PageContainer>
  )
}
