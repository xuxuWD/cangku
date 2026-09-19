#!/usr/bin/env node
// UI 文案体检（UI v2 · M3 收口）：扫出**用户可见文案里的开发术语**。
//
// 纪律（v2 设计 §5 / D-01）：
// - 用户可见文案一律业务语言：不出现「桩 / 后端 / 接口 / 端点 / 字段 / 幂等 / 数据模型 / 422 …」；
// - 生产分支尤其重要：`import.meta.env.DEV` 里的开发态文案允许保留，按行尾 `ui-copy:dev-only` 标记豁免；
// - 本脚本只做**机检**（粗筛）；注释与测试文件不参与（注释不是文案，测试可自由使用术语）。
//
// 用法：`npm run check:ui-copy`（零命中退出码 0；命中逐条打印文件:行号并退出 1）。

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..')
const srcDir = join(root, 'src')

// 开发术语清单：中文开发词 + 少数英文开发词（**只挑在文案里一定是开发腔的词**；
// api / payload / stub / db 这类在代码里到处都是，作为标识符不算文案问题，故不纳入）。
const DEV_WORDS = /桩|后端|端点|接口|字段|幂等|数据模型|报文|落库|入参|出参|熔断|422|truncated|traceback|SQL/i

// 代码行（不是文案）：导入导出语句、状态码比较（`=== 422` 是分支判断，不是给用户看的字）。
const CODE_LINE = /^\s*(import|export)\b|(===|==)\s*422\b/

const SKIP_FILE = /\.(test|spec)\.[cm]?[jt]sx?$|\.d\.ts$/
const IGNORE_MARK = 'ui-copy:dev-only'

/** 去掉块注释与行注释（粗粒度足够：只减少命中，不制造命中）。 */
function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ' '))
    .replace(/\/\/[^\n]*/g, '')
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      walk(full, out)
      continue
    }
    if (/\.(ts|tsx)$/.test(name) && !SKIP_FILE.test(name)) out.push(full)
  }
  return out
}

/**
 * 提取这一行里**可能给人看的字**：
 * ① 字符串字面量的内容；② JSX 文本（去掉标签与 `{…}` 表达式容器后剩下的字）。
 * 这样 `truncated: boolean` 这类标识符不会被当成文案。
 */
function copyCandidates(line) {
  const parts = []
  const withoutStrings = line.replace(/'([^'\\]|\\.)*'|"([^"\\]|\\.)*"|`([^`\\]|\\.)*`/g, (match) => {
    parts.push(match.slice(1, -1))
    return ' '
  })
  const jsxText = withoutStrings.replace(/<[^>]*>/g, ' ').replace(/\{[^{}]*\}/g, ' ')
  if (/[\u4e00-\u9fff]/.test(jsxText)) parts.push(jsxText)
  return parts.join(' ')
}

const findings = []

for (const file of walk(srcDir)) {
  const raw = readFileSync(file, 'utf8')
  const lines = raw.split(/\r?\n/)
  const stripped = stripComments(raw).split(/\r?\n/)
  stripped.forEach((line, index) => {
    if (lines[index].includes(IGNORE_MARK)) return
    if (CODE_LINE.test(line)) return
    const copy = copyCandidates(line)
    if (!copy || !DEV_WORDS.test(copy)) return
    findings.push({ file: relative(root, file).replace(/\\/g, '/'), line: index + 1, text: lines[index].trim() })
  })
}

if (findings.length > 0) {
  console.error(`用户可见文案里发现开发术语：${findings.length} 处\n`)
  for (const item of findings) console.error(`  ${item.file}:${item.line}  ${item.text}`)
  console.error('\n请改成业务语言；确属开发态专属（仅 DEV 分支）的文案，在该行尾加 `// ui-copy:dev-only`。')
  process.exit(1)
}

console.log('UI 文案体检通过：用户可见文案未命中开发术语。')