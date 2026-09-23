/**
 * B3 原型 · 悬浮助手**规则层**用例（规格 §6 + §11 N3）
 *
 * 规格 §11 N3：「**不在悬浮助手里用 LLM 做排序/意图识别**」——
 * 所以这一层的每一条都必须是**可穷举、可复现、零模型调用**的。
 */
import { attentionBadgeText, buildAttentionItems, buildSuggestedActions, routeIntent } from '../assistantRules'
import type { AttentionItem } from '../store'

const item = (id: string, kind: AttentionItem['kind']): AttentionItem => ({ id, title: `T-${id}`, kind, objectId: `o-${id}` })

describe('待你处理：排序（规格 §6 的固定顺序）', () => {
  it('按 待审批 > 待输入 > 受阻 > 失败 > 完成 排', () => {
    const input = [item('a', '完成'), item('b', '失败'), item('c', '待审批'), item('d', '受阻'), item('e', '待输入')]
    expect(buildAttentionItems(input).map((row) => row.kind)).toEqual(['待审批', '待输入', '受阻', '失败', '完成'])
  })

  it('**稳定排序**：同类保持输入顺序（同输入必得同输出 ⇒ 可测）', () => {
    const input = [item('1', '待审批'), item('2', '待审批'), item('3', '待审批')]
    expect(buildAttentionItems(input).map((row) => row.id)).toEqual(['1', '2', '3'])
    expect(buildAttentionItems(input).map((row) => row.id)).toEqual(['1', '2', '3'])
  })

  it('不改动入参（纯函数）', () => {
    const input = [item('a', '完成'), item('b', '待审批')]
    const snapshot = input.map((row) => row.id)
    buildAttentionItems(input)
    expect(input.map((row) => row.id)).toEqual(snapshot)
  })
})

describe('条数文案', () => {
  it('0 条不说「0 条」，说「暂无」', () => {
    expect(attentionBadgeText(0)).toBe('暂无待你处理')
  })

  it('有条数时给出条数', () => {
    expect(attentionBadgeText(3)).toBe('待你处理 3 条')
  })
})

describe('跟进建议：纯规则（规格 §6）', () => {
  it('完成态**没有**建议 —— 不硬凑一条"下一步"', () => {
    expect(buildSuggestedActions('完成')).toEqual([])
  })

  it('其余四态都有非空建议', () => {
    for (const kind of ['待审批', '待输入', '受阻', '失败'] as const) {
      expect(buildSuggestedActions(kind).length).toBeGreaterThan(0)
    }
  })
})

describe('中文正则意图路由（规格 §6 给出的两条 + 新建）', () => {
  it('「派给内容岗写篇稿」⇒ delegate', () => {
    expect(routeIntent('派给内容岗写篇稿')).toEqual({ intent: 'delegate', matched: '派给' })
  })

  it('「待我批的有哪些」⇒ approvals', () => {
    expect(routeIntent('待我批的有哪些').intent).toBe('approvals')
  })

  it('「委派/交给/安排给」都算委派', () => {
    for (const text of ['委派一下', '交给剪辑岗', '安排给运营']) {
      expect(routeIntent(text).intent).toBe('delegate')
    }
  })

  it('顺序有意义：更具体的先判，避免误吃', () => {
    // 「派给审批岗」里既有"派给"也有"审批"；按规则顺序应判为委派
    expect(routeIntent('派给审批岗处理').intent).toBe('delegate')
  })

  it('匹配不到 ⇒ 如实返回 unknown（**不猜**）', () => {
    expect(routeIntent('今天天气怎么样')).toEqual({ intent: 'unknown', matched: null })
    expect(routeIntent('   ')).toEqual({ intent: 'unknown', matched: null })
  })

  it('命中时回传命中的正则原文（界面要如实说明"为什么这么理解"）', () => {
    expect(routeIntent('帮我新建对话').matched).toBe('新建对话')
  })
})
