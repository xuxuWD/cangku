import { Icon } from '../../components/Icon'
import type { KNOWLEDGE_BASES } from './types'
type Base = typeof KNOWLEDGE_BASES[number]
export function KnowledgeScopeRow({ item, enabled, onToggle, disabled = false }: { item: Base; enabled: boolean; onToggle: () => void; disabled?: boolean }) { return <button type="button" className={`scope-row ${enabled ? 'on' : ''}`} aria-pressed={enabled} disabled={disabled} onClick={onToggle}><span className={`scope-tile tile-${item.icon}`}><Icon name={item.icon as 'document' | 'content' | 'project' | 'geo'} /></span><span className="scope-copy"><strong>{item.name}{item.sensitive && <em>需审批</em>}</strong><small>{item.description}</small></span><span className="switch" aria-hidden="true"><span /></span></button> }
