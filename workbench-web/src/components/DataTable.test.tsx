import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { TableColumnsType } from 'antd'
import { DataTable } from './DataTable'

interface Row {
  id: string
  name: string
}

const COLUMNS: TableColumnsType<Row> = [{ title: '名称', dataIndex: 'name', key: 'name' }]
const ROWS: Row[] = [
  { id: 'demo-a', name: '示例甲' },
  { id: 'demo-b', name: '示例乙' },
]

describe('DataTable', () => {
  it('就绪：渲染 AntD Table 与数据行', () => {
    render(<DataTable<Row> columns={COLUMNS} rows={ROWS} rowKey={(row) => row.id} />)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('示例甲')).toBeInTheDocument()
    expect(screen.getByText('示例乙')).toBeInTheDocument()
  })

  it('loading：显示骨架行，不出现空态文案、也不冒充有数据', () => {
    const { container } = render(<DataTable<Row> columns={COLUMNS} rows={[]} rowKey={(row) => row.id} state="loading" loadingRows={4} />)
    expect(container.querySelectorAll('.ant-skeleton')).toHaveLength(4)
    expect(screen.queryByText('暂无内容。')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('empty 与 error 的文案可区分，error 可重试', async () => {
    const empty = render(<DataTable<Row> columns={COLUMNS} rows={[]} rowKey={(row) => row.id} state="empty" />)
    expect(screen.getByText('暂无内容。')).toBeInTheDocument()
    empty.unmount()

    let retried = 0
    render(
      <DataTable<Row> columns={COLUMNS} rows={[]} rowKey={(row) => row.id} state="error" onRetry={() => { retried += 1 }} />,
    )
    expect(screen.getByText('加载失败，请稍后再试。')).toBeInTheDocument()
    expect(screen.queryByText('暂无内容。')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('forbidden：渲染无权限态与原因，不渲染表格', () => {
    render(
      <DataTable<Row>
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(row) => row.id}
        state="forbidden"
        stateDescription="缺少审计日志查看权限。"
      />,
    )
    expect(screen.getByText('无访问权限')).toBeInTheDocument()
    expect(screen.getByText('缺少审计日志查看权限。')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('状态保真：未配置 / 样本不足 / 未验证如实展示，不渲染表格、不显示 0', () => {
    const cases = [
      ['not_configured', '尚未配置数据源，暂不展示统计。'],
      ['insufficient_sample', '样本不足，暂不展示统计。'],
      ['unverified', '数据未验证，暂不展示统计。'],
    ] as const

    for (const [presence, text] of cases) {
      const { unmount } = render(
        <DataTable<Row> columns={COLUMNS} rows={ROWS} rowKey={(row) => row.id} presence={presence} />,
      )
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
      expect(screen.queryByText('示例甲')).not.toBeInTheDocument()
      expect(screen.queryByText('0')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('分页：传入 pagination 时翻页只回调（服务端分页语义）', async () => {
    let changed: [number, number] | undefined
    render(
      <DataTable<Row>
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(row) => row.id}
        pagination={{ page: 1, pageSize: 10, total: 30, onChange: (page, pageSize) => { changed = [page, pageSize] } }}
      />,
    )
    await userEvent.click(screen.getByTitle('2'))
    expect(changed).toEqual([2, 10])
  })
})