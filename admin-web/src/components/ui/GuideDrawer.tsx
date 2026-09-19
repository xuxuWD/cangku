import { useEffect, useRef } from 'react'
import type { Guide } from '../../app/guides'
import { Icon } from '../Icon'
import { useModalFocus } from '../useModalFocus'

/**
 * 「? 使用指南」抽屉（UI v2 §5）：四段骨架（⏱ 30 秒上手 / 1 这是什么 / 2 什么时候用 / 3 最短怎么用），
 * 每段结尾给退出路径。内容按**当前页面**取（见 app/guides.ts）。
 * 关闭时才卸载（打开态才进 DOM）：遮罩与 `Esc` 可关，焦点进出自 `useModalFocus` 保证。
 */
export function GuideDrawer({ open, guide, onClose }: { open: boolean; guide: Guide; onClose: () => void }) {
  const ref = useRef<HTMLElement | null>(null)
  useModalFocus(open, ref)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div className="drawer-mask" role="presentation" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={guide.title} ref={ref} tabIndex={-1}>
        <div className="drawer__head">
          <h2>{guide.title}</h2>
          <button className="icon-btn" type="button" aria-label="关闭使用指南" onClick={onClose}>
            <Icon name="close" size={16} />
          </button>
        </div>
        <div className="drawer__body">
          {guide.steps.map((step) => (
            <div className="guide-step" key={step.label}>
              <span className="guide-step__label">{step.label}</span>
              <p>{step.text}</p>
              {step.exit && <div className="guide-exit">{step.exit}</div>}
            </div>
          ))}
        </div>
      </aside>
    </>
  )
}