import { useEffect, useState, type RefObject } from 'react'

/**
 * **来源**：由 `admin-web/src/features/conversation/useSlotVisible.ts` 合并移植（逐字）。
 *
 * ⚠️ **依赖一个基座壳里还不存在的标记**：它靠 `closest('.view-slot')` 找常驻视图槽
 * （B3 §4「对话常驻」的宿主）。**基座壳目前是"逐页挂载"，没有 `.view-slot`** ⇒
 * `closest` 返回 `null` ⇒ `slotHidden` 恒为 `false` ⇒ 只按**浏览器标签页可见性**判断。
 * 这是**优雅降级**（不会误判为"不可见"而断流），不是坏掉；等 §4 的常驻槽落地后自动生效。
 *
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