#!/usr/bin/env node
// 对比度体检（UI v2 · M3 收口）：按 WCAG 2.1 计算关键「前景 / 底色」组合的对比度。
//
// 纪律（v2 设计 §5 / 无障碍）：
// - 正文类文本（`--text-body` / `--text-aux` / `--text-micro` 三档都用到的组合）**不得低于 4.5:1**；
// - 行内状态色（成功 / 警示 / 危险）配各自的淡底同样按 4.5:1 要求（它们承载成败信息）；
// - 非文字元素（描边、分隔线）按 3:1 记录，仅提示不判定。
//
// 用法：`npm run check:contrast`（不达标退出码 1）。数值逐条打印，便于归档。

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..')
const css = readFileSync(join(root, 'src/styles/tokens.css'), 'utf8')

/** 取某个选择器块里的令牌值（只认直接写颜色的那些；别名令牌视为 CSS 变量引用，不做展开）。 */
function readTokens(selector) {
  const start = css.indexOf(selector)
  if (start < 0) throw new Error(`tokens.css 里找不到选择器 ${selector}`)
  const open = css.indexOf('{', start)
  const close = css.indexOf('}', open)
  const block = css.slice(open + 1, close)
  const tokens = {}
  for (const match of block.matchAll(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    tokens[match[1]] = match[2]
  }
  return tokens
}

const THEMES = {
  light: readTokens(':root {'),
  dark: readTokens(":root[data-theme='dark']"),
}

function channel(value) {
  const v = value / 255
  return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
}

function luminance(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

function ratio(foreground, background) {
  const a = luminance(foreground)
  const b = luminance(background)
  const [high, low] = a > b ? [a, b] : [b, a]
  return (high + 0.05) / (low + 0.05)
}

// [前景, 底色, 最低要求（4.5 = 正文级；0 = 仅记录数值，不做判定）]
// 说明：分隔线 / 描边（`border-strong`）只记录不判定——v2 的控件靠标签与填充识别，
// 1px 描边是视觉分隔而非控件边界，强行拉到 3:1 会把整套界面变成「重边框」。
const PAIRS = [
  ['fg-primary', 'bg-app', 4.5],
  ['fg-primary', 'bg-card', 4.5],
  ['fg-secondary', 'bg-app', 4.5],
  ['fg-secondary', 'bg-card', 4.5],
  ['fg-secondary', 'bg-subtle', 4.5],
  ['fg-secondary', 'bg-sidebar', 4.5],
  ['fg-muted', 'bg-card', 4.5],
  ['fg-muted', 'bg-subtle', 4.5],
  ['accent-fg', 'accent', 4.5],
  ['accent', 'bg-card', 4.5],
  ['accent', 'accent-soft', 4.5],
  ['success', 'success-soft', 4.5],
  ['success', 'bg-card', 4.5],
  ['warning', 'warning-soft', 4.5],
  ['warning', 'bg-card', 4.5],
  ['danger', 'danger-soft', 4.5],
  ['danger', 'bg-card', 4.5],
  ['info', 'info-soft', 4.5],
  ['border-strong', 'bg-card', 0],
]

const failures = []

for (const [themeName, tokens] of Object.entries(THEMES)) {
  console.log(`\n${themeName === 'light' ? '浅色' : '深色'}（${themeName}）：`)
  for (const [fgKey, bgKey, min] of PAIRS) {
    const fg = tokens[fgKey]
    const bg = tokens[bgKey]
    if (!fg || !bg) {
      failures.push({ themeName, fgKey, bgKey, min, value: null })
      console.log(`  ${fgKey} / ${bgKey}：令牌缺失`)
      continue
    }
    const value = ratio(fg, bg)
    const ok = min === 0 ? true : value >= min
    const requirement = min === 0 ? '仅记录' : `要求 ≥${min}`
    console.log(`  ${ok ? '✓' : '✗'} ${fgKey}(${fg}) / ${bgKey}(${bg}) = ${value.toFixed(2)}:1（${requirement}）`)
    if (!ok) failures.push({ themeName, fgKey, bgKey, min, value })
  }
}

if (failures.length > 0) {
  console.error(`\n对比度不达标：${failures.length} 组`)
  process.exit(1)
}

console.log('\n对比度体检通过：关键组合全部达标。')