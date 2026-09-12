/** 线性图标：内联 SVG，继承 currentColor，不引入任何图标库依赖。 */
export type IconName =
  | 'home'
  | 'sparkle'
  | 'chat'
  | 'bell'
  | 'user'
  | 'access'
  | 'agent'
  | 'model'
  | 'history'
  | 'project'
  | 'check'
  | 'document'
  | 'content'
  | 'geo'
  | 'warning'
  | 'send'
  | 'plus'
  | 'chevron'

const PATHS: Record<IconName, React.ReactNode> = {
  home: (
    <>
      <path d="M4 10.5 12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19z" />
      <path d="M9.5 20.5v-6h5v6" />
    </>
  ),
  sparkle: (
    <>
      <path d="M11 3.5l1.9 5.1 5.1 1.9-5.1 1.9L11 17.5 9.1 12.4 4 10.5l5.1-1.9z" />
      <path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" />
    </>
  ),
  chat: (
    <>
      <path d="M5.2 5.6h13.6a1.6 1.6 0 0 1 1.6 1.6v8.2a1.6 1.6 0 0 1-1.6 1.6h-6.6L7.6 20.2v-3.2H5.2a1.6 1.6 0 0 1-1.6-1.6V7.2a1.6 1.6 0 0 1 1.6-1.6Z" />
      <path d="M8.8 11.6h.01M12 11.6h.01M15.2 11.6h.01" />
    </>
  ),
  bell: (
    <>
      <path d="M18 9.8a6 6 0 1 0-12 0c0 3.9-1.4 5.4-1.4 5.4h14.8S18 13.7 18 9.8Z" />
      <path d="M10.3 18.6a2 2 0 0 0 3.4 0" />
    </>
  ),
  user: (
    <>
      <path d="M12 12.6a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
      <path d="M4.6 20.5c1.6-3.3 4.2-5 7.4-5s5.8 1.7 7.4 5" />
    </>
  ),
  access: (
    <>
      <path d="M12 3.2 19 6v6.2c0 3.9-2.9 6.9-7 8.6-4.1-1.7-7-4.7-7-8.6V6z" />
      <path d="M9.4 12.1l1.9 1.9 3.4-3.6" />
    </>
  ),
  agent: (
    <>
      <path d="M5 9.6h14a1.6 1.6 0 0 1 1.6 1.6v5.6A1.6 1.6 0 0 1 19 18.4H5a1.6 1.6 0 0 1-1.6-1.6v-5.6A1.6 1.6 0 0 1 5 9.6Z" />
      <path d="M12 9.6V6.9" />
      <path d="M12 5.7a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z" />
      <path d="M9.2 14h.01M14.8 14h.01" />
    </>
  ),
  model: (
    <>
      <path d="M7.6 7.6h8.8v8.8H7.6z" />
      <path d="M10.4 4.2v3.4M13.6 4.2v3.4M10.4 16.4v3.4M13.6 16.4v3.4" />
      <path d="M4.2 10.4h3.4M4.2 13.6h3.4M16.4 10.4h3.4M16.4 13.6h3.4" />
    </>
  ),
  history: (
    <>
      <path d="M3.9 12a8.1 8.1 0 1 0 2.5-5.8" />
      <path d="M3.6 4.4v4.2h4.2" />
      <path d="M12 7.9V12l3 1.8" />
    </>
  ),
  project: (
    <>
      <path d="M3.6 7.6A1.6 1.6 0 0 1 5.2 6h3.6l2 2.6h7.9A1.6 1.6 0 0 1 20.4 10v7.4a1.6 1.6 0 0 1-1.6 1.6H5.2a1.6 1.6 0 0 1-1.6-1.6z" />
    </>
  ),
  check: (
    <>
      <path d="m5 12.9 4.2 4.2L19 6.9" />
    </>
  ),
  document: (
    <>
      <path d="M14 3.6H7.6A1.6 1.6 0 0 0 6 5.2v13.6a1.6 1.6 0 0 0 1.6 1.6h8.8a1.6 1.6 0 0 0 1.6-1.6V7.6z" />
      <path d="M14 3.6v4H18" />
      <path d="M9 12.4h6M9 15.8h4" />
    </>
  ),
  content: (
    <>
      <path d="M12 7.3C10.4 6 8.4 5.3 6 5.3H4v12.4h2c2.4 0 4.4.7 6 2 1.6-1.3 3.6-2 6-2h2V5.3h-2c-2.4 0-4.4.7-6 2Z" />
      <path d="M12 7.3v12.4" />
    </>
  ),
  geo: (
    <>
      <path d="M12 3.6a8.4 8.4 0 1 0 0 16.8 8.4 8.4 0 0 0 0-16.8Z" />
      <path d="M3.6 12h16.8" />
      <path d="M12 3.6c2.2 2.3 3.3 5.1 3.3 8.4s-1.1 6.1-3.3 8.4c-2.2-2.3-3.3-5.1-3.3-8.4s1.1-6.1 3.3-8.4Z" />
    </>
  ),
  warning: (
    <>
      <path d="M12 4.3 20.8 19.6H3.2z" />
      <path d="M12 10v4.2" />
      <path d="M12 17.1h.01" />
    </>
  ),
  send: (
    <>
      <path d="M12 19.2V5.4" />
      <path d="m5.8 11.6 6.2-6.2 6.2 6.2" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5.6v12.8M5.6 12h12.8" />
    </>
  ),
  chevron: (
    <>
      <path d="m6.5 9.8 5.5 5.4 5.5-5.4" />
    </>
  ),
}

export function Icon({
  name,
  label,
  className = '',
  size = 18,
}: {
  name: IconName
  label?: string
  className?: string
  size?: number
}) {
  return (
    <svg
      className={`icon ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {PATHS[name]}
    </svg>
  )
}
