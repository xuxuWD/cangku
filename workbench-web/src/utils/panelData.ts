/**
 * 面板取数 hook（跨模块共享）：把「加载中 / 就绪 / 失败」收敛成一份状态。
 *
 * - 失败按 `panelStateOfError` 分成 `error` / `forbidden` 两种四态，不静默当成空数据；
 * - 用 `active` 标记丢弃过期结果，避免卸载后回写 state；
 * - `reload()` 供四态里的"重试"使用；
 * - `deps`：**取数依赖**（如筛选条件 / 分页），变化即重新取数。传模块级稳定函数时可省略。
 */
import { useEffect, useState } from 'react'
import type { ContentStateKind } from '../components'
import { panelStateOfError } from './serviceKit'

export type PanelViewState = ContentStateKind | 'ready'

export interface PanelData<T> {
  state: PanelViewState
  data: T
  reload: () => void
}

/** 稳定的空依赖（保持 deps 数组长度与内容恒定，避免每次渲染都重新取数）。 */
const NO_DEPS: readonly unknown[] = []

export function usePanelData<T>(
  loader: () => Promise<T>,
  fallback: T,
  deps: readonly unknown[] = NO_DEPS,
): PanelData<T> {
  const [state, setState] = useState<PanelViewState>('loading')
  const [data, setData] = useState<T>(fallback)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setState('loading')
    loader()
      .then((next) => {
        if (!active) return
        setData(next)
        setState('ready')
      })
      .catch((error: unknown) => {
        if (!active) return
        setState(panelStateOfError(error))
      })
    return () => {
      active = false
    }
    // 何时重新取数由调用方通过 `deps` 声明；`loader` 多为内联函数（每次渲染都是新引用），故不进依赖。
  }, [attempt, ...deps])

  return { state, data, reload: () => setAttempt((value) => value + 1) }
}