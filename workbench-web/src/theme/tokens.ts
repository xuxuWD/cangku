/**
 * 设计令牌唯一来源（Design Token Single Source of Truth）。
 *
 * 纪律：`src` 下任何组件都不得写颜色 / 圆角 / 间距 / 字号字面量，一律从这里取；
 * 该纪律由 `src/theme/no-raw-colors.test.ts` 自动守卫（扫描十六进制颜色与 border-radius 数值）。
 *
 * 主色与正文色的取舍（规范硬性要求，必须记录在此）：
 * - 主色 `#1677FF` 与白色背景的对比度约 3.68:1，**不满足** WCAG AA 对正文 4.5:1 的要求，
 *   因此它只作**组件底色**（按钮背景、选中态底色、进度填充等大面积色块），不用于文字。
 * - 正文文字、链接、可点击文字一律使用加深后的 `#0958D9`（对白色背景约 5.17:1，满足 4.5:1）。
 *   该值通过 ConfigProvider 的 `colorText` / `colorLink` 下发，组件里不允许再写死颜色。
 */
import type { ThemeConfig } from 'antd'

/** 颜色令牌。 */
export const color = {
  /** 品牌主色：只作组件底色。 */
  primary: '#1677FF',
  /** 正文 / 链接色：主色加深版，满足 4.5:1 对比度。 */
  primaryText: '#0958D9',
  /** 内容区背景。 */
  contentBg: '#F5F7FA',
  /** 卡片 / 容器背景。 */
  cardBg: '#FFFFFF',
  /** 边框与分割线。 */
  border: '#E5E7EB',
  /** 辅助文字（对白底 4.83:1，满足 4.5:1）。 */
  textSecondary: '#6B7280',
} as const

/** 圆角令牌。 */
export const radius = { card: 8, button: 6, tag: 4 } as const

/** 阴影令牌。 */
export const shadow = { card: '0 1px 2px rgba(16,24,40,.04)' } as const

/** 间距令牌：只用 8 的倍数。 */
export const spacing = { sm: 8, md: 16, lg: 24, xl: 32 } as const

/** 字号梯度。 */
export const fontSize = { xs: 12, sm: 14, md: 16, lg: 20, xl: 24 } as const

/** 行高与标题字重。 */
export const lineHeight = 1.5
export const fontWeight = { heading: 600 } as const

/** 布局尺寸。 */
export const layout = {
  /** 左侧导航宽度。 */
  siderWidth: 240,
  /** 顶栏高度。 */
  headerHeight: 56,
  /** 内容区内边距。 */
  contentPadding: 24,
  /** 内容区最大宽度。 */
  contentMaxWidth: 1440,
} as const

/** 全部令牌（按分类聚合，便于一次性引用）。 */
export const tokens = { color, radius, shadow, spacing, fontSize, lineHeight, fontWeight, layout } as const

export type Tokens = typeof tokens

/** 落地到 AntD 的主题配置：组件里不再出现任何颜色 / 圆角字面量。 */
export const antdTheme: ThemeConfig = {
  token: {
    // 颜色
    colorPrimary: color.primary,
    colorLink: color.primaryText,
    colorText: color.primaryText,
    colorTextSecondary: color.textSecondary,
    colorBgLayout: color.contentBg,
    colorBgContainer: color.cardBg,
    colorBorder: color.border,
    colorBorderSecondary: color.border,
    colorSplit: color.border,
    // 圆角
    borderRadius: radius.button,
    borderRadiusLG: radius.card,
    borderRadiusSM: radius.tag,
    // 字号 / 行高 / 字重
    fontSize: fontSize.sm,
    fontSizeSM: fontSize.xs,
    fontSizeLG: fontSize.md,
    fontSizeHeading1: fontSize.xl,
    fontSizeHeading2: fontSize.lg,
    fontSizeHeading3: fontSize.md,
    fontSizeHeading4: fontSize.sm,
    fontSizeHeading5: fontSize.sm,
    fontWeightStrong: fontWeight.heading,
    lineHeight,
    // 阴影
    boxShadowTertiary: shadow.card,
    wireframe: false,
  },
  components: {
    Layout: {
      siderBg: color.cardBg,
      headerBg: color.cardBg,
      bodyBg: color.contentBg,
      headerHeight: layout.headerHeight,
      headerPadding: `0 ${spacing.lg}px`,
    },
    Menu: {
      itemBorderRadius: radius.tag,
      itemHeight: 40,
      itemMarginInline: spacing.sm,
      itemMarginBlock: spacing.sm,
      itemSelectedBg: color.contentBg,
      subMenuItemBg: color.cardBg,
    },
    Card: {
      borderRadiusLG: radius.card,
      paddingLG: spacing.lg,
    },
    Button: {
      borderRadius: radius.button,
    },
    Tag: {
      borderRadiusSM: radius.tag,
    },
  },
}