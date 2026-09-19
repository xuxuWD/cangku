import { useEffect } from 'react'
import type { RefObject } from 'react'

/** 弹层内可聚焦元素（与浏览器默认 Tab 序一致的最小集合）。 */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * 模态弹层的键盘可达性（对应真源 §2.17 验收标准 5「焦点不丢」）：
 * ① 打开时把焦点**移入**弹层（否则屏幕阅读器与键盘用户仍在遮罩后的页面上）；
 * ② `Tab` 只在弹层内循环（`aria-modal` 的语义要求，避免焦点跑到看不见的地方）；
 * ③ 关闭后焦点**归位**到打开它的元素。
 *
 * **非模态浮层不要用**（如「?」提示）：它不该抢焦点。
 */
export function useModalFocus(open: boolean, containerRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return
    const node = containerRef.current
    if (!node) return
    const previous = document.activeElement as HTMLElement | null
    const focusables = () => Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))

    // ① 进入：优先第一个可聚焦元素；没有则聚焦容器本身（容器需 tabIndex={-1}）。
    const first = focusables()[0]
    ;(first ?? node).focus()

    // ② 循环：从首项 Shift+Tab 或从末项 Tab 时回到另一端；焦点已跑出弹层时也拉回。
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const head = items[0]
      const tail = items[items.length - 1]
      const active = document.activeElement
      const outside = !node.contains(active)
      if (event.shiftKey && (active === head || outside)) {
        event.preventDefault()
        tail.focus()
      } else if (!event.shiftKey && (active === tail || outside)) {
        event.preventDefault()
        head.focus()
      }
    }

    node.addEventListener('keydown', onKeyDown)
    return () => {
      node.removeEventListener('keydown', onKeyDown)
      // ③ 归位：仅当打开它的元素还在文档里（避免把焦点丢给已卸载的节点）。
      if (previous && document.contains(previous)) previous.focus()
    }
  }, [open, containerRef])
}