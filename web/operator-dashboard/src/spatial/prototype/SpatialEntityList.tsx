import { Button } from '@/spatial/primitives'

import { entityKindLabel, spatialEntities, type SpatialEntity } from './entities'

export type SpatialEntityListProps = {
  selectedEntityId: string | null
  onSelect: (entityId: string) => void
  entities?: readonly SpatialEntity[]
}

function entityLabel(entity: SpatialEntity): string {
  return `${entity.label} · ${entityKindLabel(entity.kind)}`
}

/** Keyboard-accessible semantic list; selection is presentation-only. */
export function SpatialEntityList({ selectedEntityId, onSelect, entities = spatialEntities }: SpatialEntityListProps) {
  const counts = entities.reduce((result, entity) => {
    const key = entity.kind === 'subagent' ? 'subagent' : entity.kind
    if (key in result) result[key as keyof typeof result] += 1
    result.total += 1
    return result
  }, { subagent: 0, endpoint: 0, service: 0, session: 0, artifact: 0, attention: 0, total: 0 })
  const detail = [
    `Subagents ${counts.subagent}`,
    `Endpoints ${counts.endpoint}`,
    counts.service ? `Services ${counts.service}` : null,
    counts.session ? `Sessions ${counts.session}` : null,
    `Artifacts ${counts.artifact}`,
    `Attention ${counts.attention}`,
  ].filter(Boolean).join(' · ')
  return (
    <details className="aidn-spatial-entity-list" data-aidn-entity-list>
      <summary>Keyboard entity list ({counts.total})</summary>
      <p className="aidn-spatial-control-hint">{detail}</p>
      <ul>
        {entities.map((entity) => (
          <li key={entity.id}>
            <Button
              size="sm"
              variant={selectedEntityId === entity.id ? 'solid' : 'ghost'}
              accent={entity.kind === 'endpoint' ? 'cyan' : entity.kind === 'attention' ? 'amber' : entity.kind === 'subagent' ? 'violet' : entity.kind === 'service' ? 'blue' : entity.kind === 'session' ? 'violet' : 'neutral'}
              aria-pressed={selectedEntityId === entity.id}
              data-aidn-entity-id={entity.id}
              onClick={() => onSelect(entity.id)}
            >
              <span>{entity.label}</span>
              <small>{entityKindLabel(entity.kind)}</small>
            </Button>
            <span className="aidn-spatial-entity-tooltip" role="note">{entityLabel(entity)} — {entity.description}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}
