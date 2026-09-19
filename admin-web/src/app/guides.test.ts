import { describe, expect, it } from 'vitest'

import { GUIDES } from './guides'

/**
 * 使用指南文案与「已交付能力」的一致性守护（2026-09-19）。
 *
 * **为什么需要**：`guides.ts` 是**用户可见文案**，而它曾出现「比实际能力少说」的漂移 ——
 * 运行详情指南写着「验收确认与沉淀功能尚未交付，本页只做展示」，但 S2 早已把
 * 「确认完成 / 打回重做 / 存成任务」交付上线（`features/runDetail/AcceptanceDecisionPanel.tsx`）
 * ⇒ 用户读了指南会**以为功能不存在而不去用**。
 *
 * **为什么现有机制守不住**：`npm run check:ui-copy` 只查开发术语泄漏，`tsc` 只保证每个页面
 * 都有一份指南（`Record<AppView, Guide>`），**都不校验「指南说的能力」与「实际交付的能力」是否一致**。
 *
 * 本用例只钉**已确认的那一处漂移类别**（把已交付的验收能力说成未交付），不追求覆盖全部文案。
 */

function guideText(view: keyof typeof GUIDES): string {
  const guide = GUIDES[view]
  return [guide.title, ...guide.steps.flatMap((step) => [step.label, step.text, step.exit ?? ''])].join('\n')
}

describe('使用指南与已交付能力的一致性', () => {
  it('运行详情指南必须提到已交付的三个验收动作', () => {
    const text = guideText('run')

    // 标签与 `AcceptanceDecisionPanel.tsx` 里的按钮文案逐字一致（改按钮就得同步改指南）。
    expect(text).toContain('确认完成')
    expect(text).toContain('打回重做')
    expect(text).toContain('存成任务')
  })

  it('运行详情指南不得把已交付的验收能力说成未交付', () => {
    const text = guideText('run')

    // 缺陷类别：句子同时出现「验收」与「尚未交付」。未交付的是「设为自动化」（定时调度），
    // 它可以在指南里出现，但不得与「验收」同句绑定。
    expect(text).not.toMatch(/验收[^。]*尚未交付/)
    expect(text).not.toMatch(/尚未交付[^。]*验收/)
  })

  it('每份指南都是完整四段（⏱ 30 秒上手 + 1/2/3）', () => {
    for (const [view, guide] of Object.entries(GUIDES)) {
      expect(guide.steps, `${view} 的指南段数不足`).toHaveLength(4)
      expect(guide.steps[0].label, `${view} 缺少「30 秒上手」段`).toContain('30 秒上手')
    }
  })

  it('不再断言个别页的过期承诺（本轮 2026-09-19 逐份复核修正的锚点）', () => {
    const all = Object.entries(GUIDES).map(([view, guide]) => ({
      view,
      text: [guide.title, ...guide.steps.flatMap((step) => [step.label, step.text, step.exit ?? ''])].join('\n'),
    }))

    // billing：提到了已交付的数据导出能力，且不再说"没有明细分页"（如实）。
    const billing = all.find((item) => item.view === 'billing')!.text
    expect(billing).toContain('数据导出')
    expect(billing).toContain('申请导出')

    // knowledge：不再承诺"改完立即生效"（实际需点保存）。
    expect(all.find((item) => item.view === 'knowledge')!.text).not.toContain('立即生效')

    // crmProgress：提到了已交付的"我的 / 全量"范围切换。
    expect(all.find((item) => item.view === 'crmProgress')!.text).toContain('我的 / 全量')

    // audit：不再承诺不存在的"点开一条看明细"交互（明细就在行内）。
    expect(all.find((item) => item.view === 'audit')!.text).not.toContain('点开一条看明细')

    // settings：不再承诺"帮助与反馈里说一声"这个并不存在的反馈入口。
    expect(all.find((item) => item.view === 'settings')!.text).not.toContain('说一声')

    // conversation：提到了归档 / 导出 / 删除。
    expect(all.find((item) => item.view === 'conversation')!.text).toContain('删除')
    expect(all.find((item) => item.view === 'conversation')!.text).toContain('导出')
  })
})
