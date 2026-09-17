import { useEffect, useState, type RefObject } from 'react'

/**
 * 视图槽可见性（P2c-1 §2.3「切走即断」）。
 *
 * App 外壳用 `hidden` 属性切换常驻挂载的视图槽——对话页切走后组件仍在 DOM 里，
 * 流读端必须主动断开，所以这里观察最近的 `.view-slot` 并叠加浏览器标签页可见性。
 */
export function useSlotVisible(ref: RefObject<Element | null>): boolean {
  const [visible, setVisible] = useState(true)
  useEffect(() => {
    const slot = ref.current?.closest('.view-slot')
    const update = () => {
      const slotHidden = slot instanceof HTMLElement ? slot.hasAttribute('hidden') : false
      setVisible(!slotHidden && document.visibilityState !== 'hidden')
    }
    update()
    const observer = new MutationObserver(update)
    if (slot) observer.observe(slot, { attributes: true, attributeFilter: ['hidden'] })
    document.addEventListener('visibilitychange', update)
    return () => {
      observer.disconnect()
      document.removeEventListener('visibilitychange', update)
    }
  }, [ref])
  return visible
}