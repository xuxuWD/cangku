import { useCallback, useEffect, useState } from 'react'

/** 主题模式：跟随系统 / 强制浅色 / 强制深色。 */
export type ThemeMode = 'light' | 'dark' | 'system'
/** 解析后的实际主题；CSS 只认这个值（写在 <html data-theme>）。 */
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'workbench.theme'
export const THEME_MODES: readonly ThemeMode[] = ['light', 'dark', 'system']

export const THEME_LABELS: Record<ThemeMode, string> = {
  light: '浅色',
  dark: '深色',
  system: '跟随系统',
}

export function isThemeMode(value: unknown): value is ThemeMode {
  return typeof value === 'string' && (THEME_MODES as readonly string[]).includes(value)
}

/** 读取持久化的主题模式；读不到、值非法或存储不可用时一律回落「跟随系统」。 */
export function readStoredMode(storage?: Pick<Storage, 'getItem'> | null): ThemeMode {
  try {
    const raw = storage?.getItem(THEME_STORAGE_KEY)
    return isThemeMode(raw) ? raw : 'system'
  } catch {
    return 'system'
  }
}

/** 持久化主题模式；存储不可用（隐私模式/配额满）时静默降级，不阻断界面。 */
export function writeStoredMode(mode: ThemeMode, storage?: Pick<Storage, 'setItem'> | null): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    /* 存储不可用时只影响下次启动的默认值，不影响本次切换 */
  }
}

/** 把模式解析成实际主题。 */
export function resolveTheme(mode: ThemeMode, prefersDark: boolean): ResolvedTheme {
  if (mode === 'system') return prefersDark ? 'dark' : 'light'
  return mode
}

/** 把实际主题写到 <html data-theme> 上，CSS 变量据此切换。 */
export function applyTheme(theme: ResolvedTheme, root?: HTMLElement | null): void {
  const target = root ?? (typeof document === 'undefined' ? null : document.documentElement)
  if (!target) return
  target.dataset.theme = theme
}

function systemPrefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** 订阅系统配色变化；环境不支持 matchMedia（如测试环境）时返回空取消函数。 */
function subscribeSystemTheme(onChange: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {}
  const query = window.matchMedia('(prefers-color-scheme: dark)')
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

export interface ThemeController {
  mode: ThemeMode
  resolved: ResolvedTheme
  setMode: (mode: ThemeMode) => void
}

/** 主题状态：读初始值 → 落盘 → 应用到 <html>；跟随系统时监听系统切换。 */
export function useThemeMode(): ThemeController {
  const storage = typeof window === 'undefined' ? null : window.localStorage
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode(storage))
  const [prefersDark, setPrefersDark] = useState<boolean>(() => systemPrefersDark())

  const resolved = resolveTheme(mode, prefersDark)

  useEffect(() => {
    applyTheme(resolved)
  }, [resolved])

  useEffect(() => {
    if (mode !== 'system') return
    return subscribeSystemTheme(() => setPrefersDark(systemPrefersDark()))
  }, [mode])

  const setMode = useCallback(
    (next: ThemeMode) => {
      setModeState(next)
      writeStoredMode(next, storage)
      setPrefersDark(systemPrefersDark())
    },
    [storage],
  )

  return { mode, resolved, setMode }
}
