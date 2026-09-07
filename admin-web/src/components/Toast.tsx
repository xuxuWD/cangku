export function Toast({ message, actionLabel, onAction }: { message: string | null; actionLabel?: string; onAction?: () => void }) {
  return <div className={`toast ${message ? 'show' : ''}`} role="status" aria-live="polite"><span>{message}</span>{message && actionLabel && onAction && <button type="button" className="toast-action" onClick={onAction}>{actionLabel}</button>}</div>
}
