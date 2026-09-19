import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CreateAgentDrawer } from '../components/CreateAgentDrawer'
import { INHERIT_NOTICE } from '../components/CapabilityPack'
import { ROLE_TEMPLATES } from '../services/myAgentsService'
import type { CreateAgentInput, RoleTemplate } from '../types'

/** 选岗位：AntD Select 的选项在浮层里，用 title 定位（选项文案与 title 一致）。 */
async function pickRole(label: string): Promise<void> {
  await userEvent.click(screen.getByRole('combobox'))
  await userEvent.click(await screen.findByTitle(label))
}

describe('CreateAgentDrawer', () => {
  it('预览的 6 项继承字段取自**所选模板对象**，且标注"能力自动继承自岗位，不可放大"', async () => {
    // 故意改掉模板的 Skill / 自治档 / 预算：若预览是硬编码，下面三条断言就会挂
    const patched: RoleTemplate = {
      ...ROLE_TEMPLATES[4], // ops
      skills: ['content.topic_plan', 'content.draft', 'content.review', 'content.extra_probe'],
      autonomy_level: 'approval_for_all',
      budget_cents: 12345,
    }
    render(<CreateAgentDrawer open templates={[patched]} onClose={() => {}} onSubmit={() => {}} />)

    await pickRole(`运营（${patched.role_key}）`)

    expect(screen.getByText('默认 Skill')).toBeInTheDocument()
    expect(screen.getByText(patched.skills.join('、'))).toBeInTheDocument()
    expect(screen.getByText('自治档')).toBeInTheDocument()
    expect(screen.getByText('谨慎（approval_for_all）')).toBeInTheDocument()
    expect(screen.getByText('单任务预算上限')).toBeInTheDocument()
    expect(screen.getByText('¥123.45')).toBeInTheDocument()

    // 6 项继承字段齐备（契约 §1 去掉岗位键 / 使命 / org_ref 后的字段）
    for (const label of ['默认 Skill', '工具 / MCP 面', '知识库范围', '记忆策略', '自治档', '单任务预算上限']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText(INHERIT_NOTICE)).toBeInTheDocument()
  })

  it('提交：名称与模板键交回调用方；未选模板 / 未填名称时先校验拦截', async () => {
    const submitted: CreateAgentInput[] = []
    render(
      <CreateAgentDrawer
        open
        templates={ROLE_TEMPLATES}
        onClose={() => {}}
        onSubmit={(input) => {
          submitted.push(input)
        }}
      />,
    )

    // 什么都没填就提交 ⇒ 校验失败，不回调
    await userEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(await screen.findByText('请先修正表单中的错误，再提交。')).toBeInTheDocument()
    expect(submitted).toHaveLength(0)

    await pickRole('财务（finance）')
    await userEvent.type(screen.getByLabelText('名称'), '财务核对助手')
    await userEvent.type(screen.getByLabelText('工作范围'), '负责对账口径核对说明。')
    await userEvent.click(screen.getByRole('button', { name: /创\s*建/ }))

    expect(submitted).toHaveLength(1)
    expect(submitted[0]).toEqual({
      name: '财务核对助手',
      role_key: 'finance',
      description: '负责对账口径核对说明。',
    })
  })

  it('岗位模板为空（如加载中）：提交被校验拦截，不产生回调', async () => {
    let submitted = 0
    render(<CreateAgentDrawer open templates={[]} state="loading" onClose={() => {}} onSubmit={() => { submitted += 1 }} />)

    // 加载态下正文是统一四态，不做成"空表单"骗人
    expect(await screen.findByText('正在加载，请稍候…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /创\s*建/ })).not.toBeInTheDocument()
    expect(submitted).toBe(0)
  })
})