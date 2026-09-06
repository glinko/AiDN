import {
  parseSpatialAuditRecord,
  parseSpatialAuthorizationDecision,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialAuditRecord,
  type SpatialAuditResult,
  type SpatialAuthorizationDecisionRecord,
} from '@/spatial/contracts'

export type SpatialAuthorizationRequest = {
  workspaceId: string
  nodeId: string
  actorRef: string
  targetRef: string
  targetType?: string
  actionId: string
  requiredCapabilities: readonly string[]
  grantedCapabilities: readonly string[]
  targetRevision: number
  currentRevision: number
  correlationId?: string | null
  now?: string | Date
}

/** Capability vocabulary reviewed at the M11 boundary. Presentation IDs are
 * intentionally absent; a renderer can only display the result of these
 * Node/Primary-Agent grants. */
export const SPATIAL_AUTHORIZATION_CAPABILITY_MATRIX = {
  browserSession: ['workspace:read', 'workspace:view'],
  primaryAgent: ['agent:grant', 'agent:rebind'],
  mcpTools: ['mcp:invoke'],
  hooks: ['hooks:subscribe', 'hooks:retry'],
  workspaceMutations: ['workspace:mutate'],
  remoteMediation: ['remote:submit'],
  recoveryActions: ['recovery:execute'],
  resourceActions: ['resource:inspect', 'resource:submit'],
  shareView: ['share:accept', 'share:leave'],
} as const

export type SpatialAuthorizationServiceOptions = {
  workspaceId: string
  nodeId: string
  currentRevision?: number
  revokedCapabilities?: Readonly<Record<string, readonly string[]>>
  now?: () => string
  idFactory?: (prefix: string) => string
}

export type SpatialAuthorizationOutcome = {
  decision: SpatialAuthorizationDecisionRecord
  allowed: boolean
}

const DEFAULT_ID = (prefix: string): string => `${prefix}:${cryptoSafeRandom()}`

function cryptoSafeRandom(): string {
  // Avoid a browser fingerprint in records while keeping IDs unique enough for
  // a session-local audit stream. The service accepts an injected factory in
  // tests and in Node-owned adapters.
  return Math.random().toString(36).slice(2, 12)
}

function isoNow(now?: string | Date): string {
  if (now instanceof Date) return now.toISOString()
  if (typeof now === 'string' && Number.isFinite(Date.parse(now))) return new Date(now).toISOString()
  return new Date().toISOString()
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))]
}

function capabilitySet(values: readonly string[]): Set<string> {
  return new Set(unique(values))
}

/**
 * Presentation state is never a capability source. This boundary only accepts
 * a Node/Primary-Agent supplied grant and evaluates it against the request.
 */
export class SpatialAuthorizationService {
  private readonly workspaceId: string
  private readonly nodeId: string
  private readonly currentRevision?: number
  private readonly now: () => string
  private readonly idFactory: (prefix: string) => string
  private readonly revokedCapabilities = new Map<string, Set<string>>()

  public constructor(options: SpatialAuthorizationServiceOptions) {
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.currentRevision = options.currentRevision
    this.now = options.now ?? (() => new Date().toISOString())
    this.idFactory = options.idFactory ?? DEFAULT_ID
    for (const [actorRef, capabilities] of Object.entries(options.revokedCapabilities ?? {})) {
      this.revokedCapabilities.set(actorRef, capabilitySet(capabilities))
    }
  }

  /** Propagates a Node/Primary-Agent revocation to subsequent decisions. */
  public revoke(actorRef: string, capabilities: readonly string[]): void {
    const revoked = this.revokedCapabilities.get(actorRef) ?? new Set<string>()
    for (const capability of capabilities) revoked.add(capability.trim())
    this.revokedCapabilities.set(actorRef, revoked)
  }

  public clearRevocation(actorRef: string, capabilities: readonly string[] = []): void {
    if (capabilities.length === 0) {
      this.revokedCapabilities.delete(actorRef)
      return
    }
    const revoked = this.revokedCapabilities.get(actorRef)
    if (!revoked) return
    for (const capability of capabilities) revoked.delete(capability.trim())
    if (revoked.size === 0) this.revokedCapabilities.delete(actorRef)
  }

  public authorize(request: SpatialAuthorizationRequest): SpatialAuthorizationOutcome {
    const targetRevision = Math.max(0, Math.trunc(request.targetRevision))
    const currentRevision = Math.max(0, Math.trunc(request.currentRevision ?? this.currentRevision ?? targetRevision))
    const requiredCapabilities = unique(request.requiredCapabilities)
    const revoked = this.revokedCapabilities.get(request.actorRef) ?? new Set<string>()
    const grantedCapabilities = unique(request.grantedCapabilities).filter((capability) => !revoked.has(capability))
    const granted = capabilitySet(grantedCapabilities)
    const missing = requiredCapabilities.filter((capability) => !granted.has(capability))
    const revokedRequired = requiredCapabilities.some((capability) => revoked.has(capability))
    const scopeMismatch = request.workspaceId !== this.workspaceId || request.nodeId !== this.nodeId
    const stale = targetRevision !== currentRevision
    const decision = scopeMismatch
      ? 'DENY'
      : stale
        ? 'STALE'
        : missing.length > 0
          ? 'DENY'
          : 'ALLOW'
    const reasonCode = scopeMismatch
      ? 'SCOPE_MISMATCH'
      : stale
        ? 'STALE_REVISION'
        : missing.length > 0
          ? revokedRequired ? 'CAPABILITY_REVOKED' : 'MISSING_CAPABILITY'
          : 'CAPABILITIES_GRANTED'

    const parsed = parseSpatialAuthorizationDecision({
      schema_version: SPATIAL_SCHEMA_VERSIONS.authorizationDecision,
      decision_id: this.idFactory('decision'),
      workspace_id: request.workspaceId,
      node_id: request.nodeId,
      actor_ref: request.actorRef,
      target_ref: request.targetRef,
      action_id: request.actionId,
      required_capabilities: requiredCapabilities,
      granted_capabilities: grantedCapabilities,
      decision,
      reason_code: reasonCode,
      target_revision: targetRevision,
      current_revision: currentRevision,
      correlation_id: request.correlationId ?? null,
      created_at: isoNow(request.now ?? this.now()),
    })
    if (!parsed.ok) throw new Error(`invalid authorization decision: ${parsed.diagnostic.path}`)
    return { decision: parsed.data, allowed: parsed.data.decision === 'ALLOW' }
  }
}

export const SENSITIVE_AUDIT_KEYS = [
  'secret',
  'token',
  'password',
  'credential',
  'private_key',
  'prompt',
  'transcript',
  'content',
] as const

function isSensitiveKey(key: string): boolean {
  const normalized = key.toLowerCase().replace(/[-\s]/g, '_')
  return SENSITIVE_AUDIT_KEYS.some((candidate) => normalized.includes(candidate))
}

export type RedactionResult = {
  value: unknown
  redactedFields: string[]
}

/** Remove sensitive values before diagnostic or audit data is persisted. */
export function redactSensitiveKeys(value: unknown, path = ''): RedactionResult {
  const redactedFields: string[] = []
  const visit = (current: unknown, currentPath: string): unknown => {
    if (Array.isArray(current)) return current.map((item, index) => visit(item, `${currentPath}[${index}]`))
    if (current && typeof current === 'object') {
      const output: Record<string, unknown> = {}
      for (const [key, child] of Object.entries(current)) {
        const childPath = currentPath ? `${currentPath}.${key}` : key
        if (isSensitiveKey(key)) {
          redactedFields.push(childPath)
          output[key] = '[REDACTED]'
        } else {
          output[key] = visit(child, childPath)
        }
      }
      return output
    }
    return current
  }
  return { value: visit(value, path), redactedFields }
}

export function assertNoSensitivePayload(value: unknown): void {
  const result = redactSensitiveKeys(value)
  if (result.redactedFields.length > 0) throw new Error(`sensitive audit payload: ${result.redactedFields.join(',')}`)
}

export type SpatialAuditInput = Omit<SpatialAuditRecord, 'schema_version' | 'audit_id' | 'occurred_at'> & {
  auditId?: string
  occurredAt?: string | Date
}

export type SpatialAuditServiceOptions = {
  retentionMs?: number
  now?: () => string
  idFactory?: (prefix: string) => string
}

/**
 * Append-only, idempotent audit storage for operator actions. It stores
 * references, revisions and decisions only; payload content must remain at
 * the Node-owned evidence boundary.
 */
export class SpatialAuditService {
  private readonly retentionMs: number
  private readonly now: () => string
  private readonly idFactory: (prefix: string) => string
  private readonly records = new Map<string, SpatialAuditRecord>()
  private readonly idempotency = new Map<string, string>()

  public constructor(options: SpatialAuditServiceOptions = {}) {
    this.retentionMs = Math.max(0, options.retentionMs ?? 30 * 24 * 60 * 60 * 1000)
    this.now = options.now ?? (() => new Date().toISOString())
    this.idFactory = options.idFactory ?? DEFAULT_ID
  }

  public append(input: SpatialAuditInput): SpatialAuditRecord {
    const existingId = this.idempotency.get(input.idempotency_key)
    if (existingId) return this.records.get(existingId) as SpatialAuditRecord
    const parsed = parseSpatialAuditRecord({
      schema_version: SPATIAL_SCHEMA_VERSIONS.auditRecord,
      audit_id: input.auditId ?? this.idFactory('audit'),
      workspace_id: input.workspace_id,
      node_id: input.node_id,
      actor_ref: input.actor_ref,
      target_ref: input.target_ref,
      target_type: input.target_type,
      action_id: input.action_id,
      decision: input.decision,
      result: input.result,
      target_revision: input.target_revision ?? null,
      resulting_revision: input.resulting_revision ?? null,
      idempotency_key: input.idempotency_key,
      correlation_id: input.correlation_id ?? null,
      redacted_fields: unique(input.redacted_fields ?? []),
      evidence_refs: unique(input.evidence_refs ?? []),
      occurred_at: input.occurredAt ?? this.now(),
    })
    if (!parsed.ok) throw new Error(`invalid audit record: ${parsed.diagnostic.path}`)
    if (parsed.data.redacted_fields.length === 0) {
      // An empty list is valid for references-only records. Raw content cannot
      // enter this API because the input type has no payload field.
    }
    this.records.set(parsed.data.audit_id, parsed.data)
    this.idempotency.set(parsed.data.idempotency_key, parsed.data.audit_id)
    return parsed.data
  }

  public recordDecision(
    decision: SpatialAuthorizationDecisionRecord,
    result: SpatialAuditResult = decision.decision === 'ALLOW' ? 'ACCEPTED' : 'REJECTED',
    options: { idempotencyKey: string; targetType?: string; evidenceRefs?: readonly string[]; resultingRevision?: number | null } = { idempotencyKey: decision.decision_id },
  ): SpatialAuditRecord {
    return this.append({
      workspace_id: decision.workspace_id,
      node_id: decision.node_id,
      actor_ref: decision.actor_ref,
      target_ref: decision.target_ref,
      target_type: options.targetType ?? 'resource',
      action_id: decision.action_id,
      decision: decision.decision,
      result,
      target_revision: decision.target_revision,
      resulting_revision: options.resultingRevision ?? null,
      idempotency_key: options.idempotencyKey,
      correlation_id: decision.correlation_id,
      redacted_fields: [],
      evidence_refs: [...(options.evidenceRefs ?? [])],
    })
  }

  public list(): SpatialAuditRecord[] {
    return [...this.records.values()].sort((left, right) => left.occurred_at.localeCompare(right.occurred_at))
  }

  public purgeExpired(now = this.now()): number {
    const cutoff = Date.parse(now) - this.retentionMs
    let removed = 0
    for (const [id, record] of this.records) {
      if (Date.parse(record.occurred_at) < cutoff) {
        this.records.delete(id)
        this.idempotency.delete(record.idempotency_key)
        removed += 1
      }
    }
    return removed
  }
}
