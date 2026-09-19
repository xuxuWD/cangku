import { antdTheme, tokens } from './tokens'

/**
 * 逐值比对设计规范：这里的期望值就是规范原文，任何一项对不上都视为令牌漂移。
 * 说明：本文件需要写规范给定的颜色字面量，因此被 `no-raw-colors.test.ts` 显式豁免。
 */
describe('设计令牌（逐值比对规范）', () => {
  it('颜色：主色只作底色，正文 / 链接用加深色', () => {
    expect(tokens.color).toEqual({
      primary: '#1677FF',
      primaryText: '#0958D9',
      contentBg: '#F5F7FA',
      cardBg: '#FFFFFF',
      border: '#E5E7EB',
      textSecondary: '#6B7280',
    })
  })

  it('圆角：卡片 8 / 按钮 6 / 标签 4', () => {
    expect(tokens.radius).toEqual({ card: 8, button: 6, tag: 4 })
  })

  it('阴影：0 1px 2px rgba(16,24,40,.04)', () => {
    expect(tokens.shadow.card).toBe('0 1px 2px rgba(16,24,40,.04)')
  })

  it('间距只用 8 的倍数（8/16/24/32）', () => {
    expect(tokens.spacing).toEqual({ sm: 8, md: 16, lg: 24, xl: 32 })
    for (const value of Object.values(tokens.spacing)) {
      expect(value % 8).toBe(0)
    }
  })

  it('字号梯度 12/14/16/20/24，行高 1.5，标题字重 600', () => {
    expect(tokens.fontSize).toEqual({ xs: 12, sm: 14, md: 16, lg: 20, xl: 24 })
    expect(tokens.lineHeight).toBe(1.5)
    expect(tokens.fontWeight.heading).toBe(600)
  })

  it('布局：导航 240 / 顶栏 56 / 内边距 24 / 最大宽度 1440', () => {
    expect(tokens.layout).toEqual({
      siderWidth: 240,
      headerHeight: 56,
      contentPadding: 24,
      contentMaxWidth: 1440,
    })
  })

  it('AntD 主题真的取自令牌（防两处漂移）', () => {
    expect(antdTheme.token?.colorPrimary).toBe(tokens.color.primary)
    expect(antdTheme.token?.colorText).toBe(tokens.color.primaryText)
    expect(antdTheme.token?.colorLink).toBe(tokens.color.primaryText)
    expect(antdTheme.token?.colorTextSecondary).toBe(tokens.color.textSecondary)
    expect(antdTheme.token?.colorBgLayout).toBe(tokens.color.contentBg)
    expect(antdTheme.token?.colorBgContainer).toBe(tokens.color.cardBg)
    expect(antdTheme.token?.colorBorder).toBe(tokens.color.border)
    expect(antdTheme.token?.borderRadius).toBe(tokens.radius.button)
    expect(antdTheme.token?.borderRadiusLG).toBe(tokens.radius.card)
    expect(antdTheme.token?.borderRadiusSM).toBe(tokens.radius.tag)
    expect(antdTheme.token?.fontSize).toBe(tokens.fontSize.sm)
    expect(antdTheme.token?.fontWeightStrong).toBe(tokens.fontWeight.heading)
    expect(antdTheme.token?.lineHeight).toBe(tokens.lineHeight)
    expect(antdTheme.token?.boxShadowTertiary).toBe(tokens.shadow.card)

    expect(antdTheme.components?.Layout?.siderBg).toBe(tokens.color.cardBg)
    expect(antdTheme.components?.Layout?.headerBg).toBe(tokens.color.cardBg)
    expect(antdTheme.components?.Layout?.bodyBg).toBe(tokens.color.contentBg)
    expect(antdTheme.components?.Layout?.headerHeight).toBe(tokens.layout.headerHeight)
    expect(antdTheme.components?.Menu?.itemBorderRadius).toBe(tokens.radius.tag)
    expect(antdTheme.components?.Button?.borderRadius).toBe(tokens.radius.button)
    expect(antdTheme.components?.Tag?.borderRadiusSM).toBe(tokens.radius.tag)
  })
})