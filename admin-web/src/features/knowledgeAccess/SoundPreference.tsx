import { playUiSound } from './sound'

export function SoundPreference({ enabled, onChange }: { enabled: boolean; onChange: (enabled: boolean) => void }) {
  const toggle = () => {
    const next = !enabled
    onChange(next)
    if (next) playUiSound('toggle')
  }
  return <div className="sound-card"><div><strong>交互提示音</strong><small>短促 · 可关闭</small></div><button className="sound-switch" type="button" aria-pressed={enabled} onClick={toggle}>{enabled ? '开' : '关'}</button></div>
}
