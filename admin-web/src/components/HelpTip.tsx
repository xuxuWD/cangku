import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * 「?」功能提示（真源 §2.17.4 · 对应批 4 审计 E-03）：
 * 关键区域标题旁的一句话解释 + 常见操作。点开、`Esc` 可关、点外部关闭。
 * 提示内容一律业务语言，不出现开发术语。
 */
export function HelpTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('mousedown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('mousedown', onPointerDown)
    }
  }, [open])

  return (
    <span className="help-tip" ref={rootRef}>
      <button
        type="button"
        className="help-tip__button"
        aria-label={`关于「${label}」的说明`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        ?
      </button>
      {open && (
        <span className="help-tip__popover" role="dialog" aria-label={`${label} 说明`}>
          {children}
        </span>
      )}
    </span>
  )
}
