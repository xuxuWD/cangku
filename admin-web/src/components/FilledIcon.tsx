export type IconName = 'home' | 'user' | 'access' | 'agent' | 'model' | 'history' | 'document' | 'content' | 'project' | 'geo' | 'warning' | 'check'
export function FilledIcon({ name, label, className = '' }: { name: IconName; label?: string; className?: string }) { return <span aria-label={label} role={label ? 'img' : undefined} className={`filled-icon icon-${name} ${className}`} /> }
