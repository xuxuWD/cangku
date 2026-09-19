/**
 * 纪律守卫：设计令牌只有 `src/theme/tokens.ts` 一个来源。
 *
 * 规则：`src` 下所有 `.ts` / `.tsx`（除豁免文件外）不得出现
 *   ① 十六进制颜色字面量（#RRGGBB 等）  ② border-radius / borderRadius 的数值字面量。
 * 命中即失败，并逐条列出"文件:行 → 命中的那一行"。
 *
 * 豁免（只有这两个）：
 *   - `theme/tokens.ts`：令牌本身当然要写值；
 *   - `theme/tokens.test.ts`：必须逐字面量比对规范值，否则断言就失去意义。
 *
 * 本文件自身也必须干净，所以守卫的"违规样例"在运行时拼字符串，不写字面量；
 * 下面两条自检证明守卫能真的命中，不是恒绿的假测试。
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve, sep } from 'node:path'

/**
 * 扫描根目录：`src`。
 * 不用 `import.meta.url` 定位 —— jsdom 环境下它不是 file: 协议（形如 http://localhost/…），
 * 转路径会直接抛错。改为从当前工作目录（vitest 的 root 即本包目录）推导，
 * 并由下面的「豁免文件确实存在」用例兜底：目录推错时会立刻失败，不会静默失效。
 */
const SRC_DIR = resolve(process.cwd(), 'src')

const EXEMPT_FILES = new Set(['theme/tokens.ts', 'theme/tokens.test.ts'])

/** 十六进制颜色：#RGB / #RRGGBB / #RRGGBBAA。 */
const HEX_COLOR = /#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/
/** 圆角数值字面量：既查 CSS 写法也查内联样式写法。 */
const RADIUS_LITERAL = /(?:border-radius\s*:\s*|borderRadius\s*[:=]\s*['"]?)\d/

interface Violation {
  line: number
  kind: string
  text: string
}

/** 扫描一段源码，返回全部命中（按行）。 */
function scan(source: string): Violation[] {
  const violations: Violation[] = []
  source.split(/\r?\n/).forEach((line, index) => {
    if (HEX_COLOR.test(line)) {
      violations.push({ line: index + 1, kind: '十六进制颜色字面量', text: line.trim() })
    }
    if (RADIUS_LITERAL.test(line)) {
      violations.push({ line: index + 1, kind: '圆角数值字面量', text: line.trim() })
    }
  })
  return violations
}

/** 列出 `src` 下所有源码文件（绝对路径 + 相对 src 的 posix 路径）。 */
function listSources(): { absolute: string; relativePath: string }[] {
  return readdirSync(SRC_DIR, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name))
    .map((entry) => {
      const absolute = join(entry.parentPath, entry.name)
      return { absolute, relativePath: relative(SRC_DIR, absolute).split(sep).join('/') }
    })
}

describe('no-raw-colors（设计令牌纪律守卫）', () => {
  it('src 下除令牌文件外，没有十六进制颜色与圆角数值字面量', () => {
    const violations = listSources()
      .filter(({ relativePath }) => !EXEMPT_FILES.has(relativePath))
      .flatMap(({ absolute, relativePath }) =>
        scan(readFileSync(absolute, 'utf-8')).map(
          (hit) => `${relativePath}:${hit.line} [${hit.kind}] ${hit.text}`,
        ),
      )

    expect(violations).toEqual([])
  })

  it('守卫确实能命中（反假测试）', () => {
    // 违规样例在运行时拼出来，避免本文件自己被自己的规则命中。
    const colorSample = ['#', '1677FF'].join('')
    const radiusSample = `borderRadius: ${String(8)}`

    expect(scan(`color: ${colorSample}`)).toHaveLength(1)
    expect(scan(radiusSample)).toHaveLength(1)
    expect(scan('color: tokens.color.primary')).toEqual([])
  })

  it('豁免文件确实存在（防止豁免名单写错而静默失去约束力）', () => {
    const all = listSources().map(({ relativePath }) => relativePath)
    for (const exempt of EXEMPT_FILES) {
      expect(all).toContain(exempt)
    }
  })
})