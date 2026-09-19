import { useEffect, useRef, useState } from 'react'
import { useModalFocus } from '../components/useModalFocus'
import { START_PATHS } from './guides'

const ONBOARDING_KEY = 'workbench.onboarding.seen'

function hasSeenOnboarding(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDING_KEY) === '1'
  } catch {
    // 存储不可用（隐私模式 / 配额）⇒ 当作已看过，不反复打扰（与 theme.ts 的降级纪律一致）。
    return true
  }
}

/**
 * 首访引导（真源 §2.17.4 · 对应批 4 审计 E-02）：
 * **只在第一次打开时出现一次**，关闭后记在本地、不再打扰；`Esc` 可关。
 * 内容与「帮助与反馈」共用同一份路径文案，避免两处说法不一致。
 */
export function Onboarding({ onOpenHelp }: { onOpenHelp: () => void }) {
  const [visible, setVisible] = useState(() => !hasSeenOnboarding())
  const dialogRef = useRef<HTMLDivElement | null>(null)
  // 与帮助面板同一套焦点规则（验收标准 5）：进入即聚焦、Tab 不跑到遮罩后、关闭不丢焦点。
  useModalFocus(visible, dialogRef)

  const dismiss = () => {
    try {
      window.localStorage.setItem(ONBOARDING_KEY, '1')
    } catch {
      // 存不进就不存：本次不再显示，刷新后可能再出现一次（可接受，不阻断使用）。
    }
    setVisible(false)
  }

  useEffect(() => {
    if (!visible) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') dismiss()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // `dismiss` 只依赖 setState 与 localStorage，稳定；仅随 open 变化重挂监听。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible])

  if (!visible) return null

  return (
    <div className="onboarding" role="dialog" aria-modal="true" aria-label="欢迎使用" ref={dialogRef} tabIndex={-1}>
      <div className="onboarding__card">
        <span className="onboarding__mark" aria-hidden="true">智</span>
        <h2>欢迎使用公司数字员工工作台</h2>
        <p>你给目标，数字员工去做；过程、产出和结论都在会话里看得见。</p>
        <ul className="onboarding__paths">
          {START_PATHS.map((path) => (
            <li key={path.label}>
              <strong>{path.label}</strong>
              <span>{path.hint}</span>
            </li>
          ))}
        </ul>
        <div className="onboarding__actions">
          <button className="button" type="button" onClick={onOpenHelp}>看看快捷键与帮助</button>
          <button className="button primary" type="button" onClick={dismiss}>知道了</button>
        </div>
      </div>
    </div>
  )
}
