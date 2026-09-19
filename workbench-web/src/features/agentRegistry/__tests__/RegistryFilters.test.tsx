import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RegistryFilters } from '../components/RegistryFilters'
import { ROLE_TEMPLATES } from '../../myAgents/services/myAgentsService'
import type { RegistryFilters as RegistryFiltersValue } from '../types'
import { NO_FILTERS } from '../types'

/** 选下拉：先点开，再选项（AntD 选项的 title 与文案一致）。 */
async function pick(label: string, option: string): Promise<void> {
  await userEvent.click(screen.getByLabelText(label))
  await userEvent.click(await screen.findByTitle(option))
}

describe('RegistryFilters', () => {
  it('渲染 4 个筛选控件与 查询 / 重置（岗位选项来自 6 个岗位模板）', async () => {
    render(<RegistryFilters filters={NO_FILTERS} templates={ROLE_TEMPLATES} onChange={() => {}} onReset={() => {}} />)

    expect(screen.getByLabelText('岗位')).toBeInTheDocument()
    expect(screen.getByLabelText('状态')).toBeInTheDocument()
    expect(screen.getByLabelText('创建者')).toBeInTheDocument()
    expect(screen.getByLabelText('名称')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /查\s*询/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重\s*置/ })).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('岗位'))
    for (const template of ROLE_TEMPLATES) {
      expect(await screen.findByTitle(`${template.name}（${template.role_key}）`)).toBeInTheDocument()
    }
  })

  it('筛选条件**整体透传**（岗位 / 状态 / 创建者 / 名称一次提交，不做前端过滤）', async () => {
    const changes: RegistryFiltersValue[] = []
    render(
      <RegistryFilters filters={NO_FILTERS} templates={ROLE_TEMPLATES} onChange={(next) => changes.push(next)} onReset={() => {}} />,
    )

    await pick('岗位', '运营（ops）')
    await pick('状态', '草稿')
    await userEvent.type(screen.getByLabelText('创建者'), '示例创建者 01')
    await userEvent.type(screen.getByLabelText('名称'), '助手')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))

    expect(changes).toHaveLength(1)
    expect(changes[0]).toEqual({
      role_key: 'ops',
      status: 'draft',
      created_by: '示例创建者 01',
      keyword: '助手',
    })
  })

  it('未填的条件按"未筛选"处理（undefined），不把空串发给服务端', async () => {
    const changes: RegistryFiltersValue[] = []
    render(
      <RegistryFilters filters={NO_FILTERS} templates={ROLE_TEMPLATES} onChange={(next) => changes.push(next)} onReset={() => {}} />,
    )

    // 只在创建者里输入空格
    await userEvent.type(screen.getByLabelText('创建者'), '   ')
    await userEvent.click(screen.getByRole('button', { name: /查\s*询/ }))

    expect(changes[0]).toEqual({
      role_key: undefined,
      status: undefined,
      created_by: undefined,
      keyword: undefined,
    })
  })

  it('重置：清空表单并回调（页面据此回到第 1 页重新取数）', async () => {
    let resets = 0
    render(
      <RegistryFilters
        filters={{ role_key: 'ops', keyword: '助手' }}
        templates={ROLE_TEMPLATES}
        onChange={() => {}}
        onReset={() => {
          resets += 1
        }}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /重\s*置/ }))
    expect(resets).toBe(1)
  })

  it('非就绪态（如岗位字典加载中）：整条筛选栏换成统一四态，不渲染任何控件', () => {
    render(
      <RegistryFilters filters={NO_FILTERS} templates={[]} state="loading" onChange={() => {}} onReset={() => {}} />,
    )

    expect(screen.getByText('正在加载，请稍候…')).toBeInTheDocument()
    expect(screen.queryByLabelText('岗位')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /查\s*询/ })).not.toBeInTheDocument()
  })
})