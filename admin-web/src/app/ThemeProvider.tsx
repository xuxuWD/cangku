import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { useThemeMode, type ThemeController } from './theme'

/**
 * 主题在应用级共享（外壳的外观快捷切换与设置页的「外观」分组读**同一份**状态，
 * 否则两处各自持有一份 mode，一处改了另一处不刷新）。
 * 无 Provider 时（组件单测直接渲染）自持一份，行为一致、只是不与外壳共享。
 */
const ThemeContext = createContext<ThemeController | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const value = useThemeMode()
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeController {
  const shared = useContext(ThemeContext)
  const standalone = useThemeMode()
  return shared ?? standalone
}