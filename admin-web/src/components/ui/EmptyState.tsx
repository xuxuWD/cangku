import type { ReactNode } from 'react'

/**
 * 空态（UI v2 §4.2）：**自研 SVG 插画**（不引外部素材）+ 标题 + 一句解释 + 主/次按钮。
 * 纪律：空态只用真实原因解释「为什么空」，不写未实现的能力（不摆假面板）。
 */
export type EmptyIllustration = 'chat' | 'list' | 'run'

const ILLUSTRATIONS: Record<EmptyIllustration, ReactNode> = {
  chat: (
    <>
      <circle cx="38" cy="38" r="31" fill="var(--accent-soft)" />
      <rect x="20" y="24" width="36" height="24" rx="8" fill="var(--bg-card)" stroke="var(--border-strong)" strokeWidth="1.5" />
      <path d="M30 48v6l7-6" fill="var(--bg-card)" stroke="var(--border-strong)" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M28 33h20M28 39h13" stroke="var(--border-strong)" strokeWidth="1.5" strokeLinecap="round" />
    </>
  ),
  list: (
    <>
      <circle cx="38" cy="38" r="31" fill="var(--accent-soft)" />
      <rect x="20" y="22" width="36" height="32" rx="7" fill="var(--bg-card)" stroke="var(--border-strong)" strokeWidth="1.5" />
      <path d="M29 32h18M29 39h18M29 46h11" stroke="var(--border-strong)" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="24.5" cy="32" r="1.6" fill="var(--accent)" />
      <circle cx="24.5" cy="39" r="1.6" fill="var(--accent)" />
    </>
  ),
  run: (
    <>
      <circle cx="38" cy="38" r="31" fill="var(--accent-soft)" />
      <path d="M22 38h9M34 38h9M46 38h8" stroke="var(--border-strong)" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="33" cy="38" r="4.5" fill="var(--bg-card)" stroke="var(--accent)" strokeWidth="2" />
      <path d="M36.5 27v6M39.5 43v6" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <rect x="28" y="20" width="16" height="9" rx="3" fill="var(--bg-card)" stroke="var(--border-strong)" strokeWidth="1.5" />
      <rect x="28" y="47" width="16" height="9" rx="3" fill="var(--bg-card)" stroke="var(--border-strong)" strokeWidth="1.5" />
    </>
  ),
}

export function EmptyState({
  illustration = 'list',
  title,
  text,
  children,
}: {
  illustration?: EmptyIllustration
  title: string
  text?: string
  /** 主/次操作按钮（有真实动作时才给） */
  children?: ReactNode
}) {
  return (
    <div className="empty">
      <svg width="76" height="76" viewBox="0 0 76 76" fill="none" aria-hidden="true">
        {ILLUSTRATIONS[illustration]}
      </svg>
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {children && <div className="empty__actions">{children}</div>}
    </div>
  )
}