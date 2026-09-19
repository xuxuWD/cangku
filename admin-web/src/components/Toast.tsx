/** 轻提示（Toast）：常驻 `aria-live` 区域，有消息时浮出；样式见 ui.css 的 `.toast`。 */
export function Toast({ message, actionLabel, onAction }: { message: string | null; actionLabel?: string; onAction?: () => void }) {
  return (
    <div className={`toast ${message ? 'is-open' : ''}`} role="status" aria-live="polite">
      <span>{message}</span>
      {message && actionLabel && onAction && (
        <button type="button" className="toast-action" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  )
}