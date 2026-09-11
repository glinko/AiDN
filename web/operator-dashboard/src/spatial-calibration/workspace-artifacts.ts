import type { WorkspaceArtifact } from '@/spatial/contracts/workspace-chat'
import { CubeEntity, DEFAULT_CALIBRATION, type Vector3Tuple } from './model'

// Slightly denser pigments keep the small mobile cubes legible against the
// milky floor while retaining the Pearl palette.
const COLORS = ['#90b9dd', '#b99cdb', '#86c7b5', '#d6a592', '#c5ae72', '#b49ccd']

function identityHash(id: string) {
  let hash = 2166136261
  for (const character of id) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619)
  return hash >>> 0
}

export class WorkspaceArtifactEntity extends CubeEntity {
  readonly sessionId: string
  readonly order: number
  /** Zero is the foreground artifact; increasing values recede into depth. */
  depthRank: number
  depth: number
  targetDepth: number
  birthElapsed: number

  constructor(item: WorkspaceArtifact, rank: number, animateBirth: boolean) {
    const hash = identityHash(item.artifact.session_id)
    const depth = 1.5 - rank * 0.62
    const position: Vector3Tuple = [-1.1 + ((hash % 5) - 2) * 0.8, 0.62, depth]
    super({
      ...DEFAULT_CALIBRATION.cube,
      id: item.artifact.artifact_id,
      position,
      size: 0.52,
      basePitch: (hash % 17) * 0.06,
      baseYaw: (hash % 23) * 0.1,
      baseRoll: (hash % 13) * 0.05,
      material: {
        ...DEFAULT_CALIBRATION.cube.material,
        color: COLORS[hash % COLORS.length],
        attenuationColor: '#6f86aa',
        transmission: 0.84,
        envMapIntensity: 1.02,
      },
      motion: { driftAmplitude: 0.035, driftFrequency: 0.2 + (hash % 7) * 0.02,
        pitchSpeed: hash % 2 ? 0.032 : -0.028, yawSpeed: hash % 3 ? -0.043 : 0.038, rollSpeed: hash % 5 ? 0.018 : -0.021 },
    })
    this.sessionId = item.artifact.session_id
    this.order = item.order
    this.depthRank = rank
    this.depth = this.targetDepth = depth
    this.birthElapsed = animateBirth ? 0 : 2
    if (animateBirth) this.scale.fill(0.001)
  }

  advance(time: number, delta: number, paused: boolean, reducedMotion: boolean) {
    this.update(time, reducedMotion)
    if (reducedMotion) { this.depth = this.targetDepth; this.birthElapsed = 2 }
    else if (!paused) {
      const step = Math.min(delta, 0.05)
      this.depth += (this.targetDepth - this.depth) * (1 - Math.exp(-step * 0.45))
      this.birthElapsed = Math.min(2, this.birthElapsed + step)
    }
    this.position[2] += this.depth - this.basePosition[2]
    const progress = Math.min(1, Math.max(0.001, (this.birthElapsed - 0.32) / 0.9))
    const birthScale = progress * progress * (3 - 2 * progress)
    // Depth is intentionally visible as a gentle optical recession rather
    // than a hard hide: older artifacts become a little smaller and quieter.
    const depthScale = Math.max(0.76, 1 - this.depthRank * 0.035)
    this.scale.fill(birthScale * depthScale)
  }
}

/** Visual cache only. All identities, ordering and transcript truth come from MCP publications. */
export class WorkspaceArtifactField {
  private initialized = false
  private entities = new Map<string, WorkspaceArtifactEntity>()

  sync(items: readonly WorkspaceArtifact[], activeId: string | null, animate: boolean): WorkspaceArtifactEntity[] {
    const latest = Math.max(0, ...items.map(item => item.order))
    const visible = [...items].sort((a, b) => b.order - a.order).filter((item, index) => index < 32 || item.artifact.session_id === activeId)
    const ids = new Set(visible.map(item => item.artifact.artifact_id))
    for (const id of this.entities.keys()) if (!ids.has(id)) this.entities.delete(id)
    const result = visible.map(item => {
      const id = item.artifact.artifact_id
      let entity = this.entities.get(id)
      if (!entity) {
        const recent = Date.now() - Date.parse(item.artifact.created_at) < 30_000
        entity = new WorkspaceArtifactEntity(item, latest - item.order,
          animate && recent && (this.initialized || item.artifact.session_id === activeId))
        this.entities.set(id, entity)
      }
      entity.depthRank = latest - item.order
      entity.targetDepth = 1.5 - (latest - item.order) * 0.62
      return entity
    })
    this.initialized = true
    return result
  }
}
