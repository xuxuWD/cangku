/**
 * B3 原型 · 路由用例（规格 §8，验收 A5 的口径：可直达 / 可刷新 / 可分享）
 *
 * 规格 §8 的四条能力，在"能解析、能往返、非法值不炸"这三件事上先立住。
 */
import { buildSearch, parseRoute, routeFor } from '../router'
import { PRIMARY_NAV, MORE_NAV, SIDEBAR_ENTRY_COUNT } from '../nav'

describe('路由解析', () => {
  it('缺省（空 query）⇒ 落到对话（对话是默认主区域）', () => {
    expect(parseRoute('')).toEqual({ view: 'chat', objectId: null, panel: null, expand: false })
  })

  it('直达：view + object + panel + expand 全部解析出来', () => {
    expect(parseRoute('?view=workitems&object=task-1&panel=employee&expand=1')).toEqual({
      view: 'workitems',
      objectId: 'task-1',
      panel: 'employee',
      expand: true,
    })
  })

  it('非法 view ⇒ 回落 chat，**不抛错、不留白屏**', () => {
    expect(parseRoute('?view=不存在的页面').view).toBe('chat')
  })

  it('非法 panel ⇒ 当作没有页签（不渲染一个不存在过的页签）', () => {
    expect(parseRoute('?view=workitems&panel=xxx').panel).toBeNull()
  })
})

describe('路由往返（可分享 / 可刷新）', () => {
  it('buildSearch(parseRoute(s)) 与规范化后的 s 一致', () => {
    const search = '?view=workitems&object=task-1&panel=brief'
    expect(buildSearch(parseRoute(search))).toBe(search)
  })

  it('`expand=false` 不写进 URL（避免同一状态有两条不同 URL）', () => {
    expect(buildSearch(routeFor('chat'))).toBe('?view=chat')
    expect(buildSearch(routeFor('chat', 'task-1', 'brief', true))).toBe('?view=chat&object=task-1&panel=brief&expand=1')
  })

  it('objectId 中的特殊字符被正确编码（可分享的 URL 不能是坏的）', () => {
    const search = buildSearch(routeFor('workitems', 'task/1 号', 'brief'))
    expect(parseRoute(search).objectId).toBe('task/1 号')
  })
})

describe('侧栏收敛（验收 A1：入口数 ≤10）', () => {
  it('业务入口 = 主 5 + 更多 3 = 8，加设置弹窗共 9 ≤ 10', () => {
    expect(PRIMARY_NAV).toHaveLength(5)
    expect(MORE_NAV).toHaveLength(3)
    expect(SIDEBAR_ENTRY_COUNT).toBe(8)
    expect(SIDEBAR_ENTRY_COUNT + 1).toBeLessThanOrEqual(10)
  })

  it('主入口就是规格 §2 写的那五个，顺序也一致', () => {
    expect(PRIMARY_NAV.map((item) => item.title)).toEqual([
      '新建对话',
      '待我处理',
      '我的数字员工',
      '工作项',
      '知识库',
    ])
  })
})
