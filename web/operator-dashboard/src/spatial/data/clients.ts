import { z } from 'zod'

import {
  parseSpatialEntity,
  parseSpatialNodeStatus,
  parseSpatialRecoveryCommand,
  parseSpatialRecoveryResult,
  parseSpatialEndpointProvenance,
  parseSpatialRemoteResult,
  parseSpatialEndpointTestFrame,
  parseSpatialResourceAccounting,
  parseSpatialRelation,
  parseSpatialWorkspace,
  spatialIdSchema,
  spatialRevisionSchema,
  type SpatialCanonicalEntity,
  type SpatialNodeStatus,
  type SpatialRecoveryCommand,
  type SpatialRecoveryResult,
  type SpatialEndpointProvenance,
  type SpatialRemoteRequest,
  type SpatialRemoteResult,
  type SpatialEndpointTestFrame,
  type SpatialResourceAccounting,
  type SpatialRelationContract,
  type SpatialWorkspaceSnapshot,
} from '@/spatial/contracts'

import { spatialEventEnvelopeSchema, type SpatialEventEnvelope } from './events'
import { assertSpatialScope, SpatialApiError, type SpatialTransport } from './transport'
import type { SpatialNodeScope } from './scope'

const collectionSchema = z.object({
  schema_version: z.string().min(1),
  node_id: spatialIdSchema,
  revision: spatialRevisionSchema,
  items: z.array(z.unknown()),
}).strip()

const resourceSummarySchema = z.object({
  schema_version: z.string().min(1),
  node_id: spatialIdSchema,
  revision: spatialRevisionSchema,
  state: z.string().min(1),
  freshness: z.object({ state: z.string().min(1) }).passthrough(),
  cpu: z.number().nonnegative().optional(),
  ram_mb: z.number().nonnegative().optional(),
  vram_mb: z.number().nonnegative().optional(),
}).strip()

export type SpatialResourceSummary = z.infer<typeof resourceSummarySchema>

const hookSummarySchema = z.object({
  hook_id: spatialIdSchema,
  node_id: spatialIdSchema,
  state: z.string().min(1),
  revision: spatialRevisionSchema,
}).strip()

export type SpatialHookSummary = z.infer<typeof hookSummarySchema>

function malformed(path: string): SpatialApiError {
  return new SpatialApiError('malformed', 'Spatial response did not match its typed contract.', path)
}

function parseCollection<T>(raw: unknown, path: string, parseItem: (value: unknown) => { ok: true; data: T } | { ok: false }): { nodeId: string; revision: number; items: T[] } {
  const collection = collectionSchema.safeParse(raw)
  if (!collection.success) throw malformed(path)
  const items: T[] = []
  for (const item of collection.data.items) {
    const parsed = parseItem(item)
    if (!parsed.ok) throw malformed(path)
    items.push(parsed.data)
  }
  return { nodeId: collection.data.node_id, revision: collection.data.revision, items }
}

function parseEventCollection(raw: unknown, path: string): { nodeId: string; cursor: string | null; items: SpatialEventEnvelope[] } {
  const envelope = z.object({
    schema_version: z.string().min(1),
    node_id: spatialIdSchema,
    cursor: z.string().nullable().optional(),
    items: z.array(z.unknown()),
  }).strip().safeParse(raw)
  if (!envelope.success) throw malformed(path)
  const items: SpatialEventEnvelope[] = []
  for (const item of envelope.data.items) {
    const parsed = spatialEventEnvelopeSchema.safeParse(item)
    if (!parsed.success) throw malformed(path)
    items.push(parsed.data)
  }
  return { nodeId: envelope.data.node_id, cursor: envelope.data.cursor ?? null, items }
}

export type SpatialDomainClients = {
  nodeStatus: { get: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialNodeStatus> }
  agents: { list: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<{ nodeId: string; revision: number; items: SpatialCanonicalEntity[] }> }
  endpoints: { list: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<{ nodeId: string; revision: number; items: SpatialCanonicalEntity[] }> }
  sessions: { list: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<{ nodeId: string; revision: number; items: SpatialCanonicalEntity[] }> }
  resources: { get: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialResourceSummary> }
  events: { history: (scope: SpatialNodeScope, cursor?: string | null, signal?: AbortSignal) => Promise<{ nodeId: string; cursor: string | null; items: SpatialEventEnvelope[] }> }
  hooks: { list: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialHookSummary[]> }
  workspace: { get: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialWorkspaceSnapshot> }
  relation: { get: (scope: SpatialNodeScope, relationRef: string, signal?: AbortSignal) => Promise<SpatialRelationContract> }
  recovery: {
    plan: (scope: SpatialNodeScope, command: SpatialRecoveryCommand, signal?: AbortSignal) => Promise<SpatialRecoveryCommand>
    apply: (scope: SpatialNodeScope, command: SpatialRecoveryCommand, confirmed: boolean, signal?: AbortSignal) => Promise<SpatialRecoveryResult>
  }
  remoteMediation: {
    provenance: (scope: SpatialNodeScope, endpointRef: string, signal?: AbortSignal) => Promise<SpatialEndpointProvenance>
    plan: (scope: SpatialNodeScope, frame: SpatialEndpointTestFrame, signal?: AbortSignal) => Promise<SpatialEndpointTestFrame>
    submit: (scope: SpatialNodeScope, request: SpatialRemoteRequest, signal?: AbortSignal) => Promise<{ result: SpatialRemoteResult; accounting: SpatialResourceAccounting }>
    cancel: (scope: SpatialNodeScope, requestId: string, signal?: AbortSignal) => Promise<SpatialEndpointTestFrame>
  }
}

export function createSpatialDomainClients(transport: SpatialTransport): SpatialDomainClients {
  async function request(path: string, scope: SpatialNodeScope, signal?: AbortSignal, method: 'GET' | 'POST' | 'PUT' = 'GET', body?: unknown): Promise<unknown> {
    return transport.request({ path, scope, signal, method, body })
  }

  async function getEntityCollection(path: string, scope: SpatialNodeScope, kind: SpatialCanonicalEntity['kind'], signal?: AbortSignal) {
    const raw = await request(path, scope, signal)
    const parsed = parseCollection(raw, path, parseSpatialEntity)
    assertSpatialScope(scope, parsed.nodeId)
    if (parsed.items.some((item) => item.kind !== kind)) throw malformed(path)
    return parsed
  }

  return {
    nodeStatus: {
      async get(scope, signal) {
        const raw = await request('/operators/spatial/status', scope, signal)
        const parsed = parseSpatialNodeStatus(raw)
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Spatial Node status contract rejected.', '/operators/spatial/status', undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
    },
    agents: { list: (scope, signal) => getEntityCollection('/operators/spatial/agents', scope, 'agent', signal) },
    endpoints: { list: (scope, signal) => getEntityCollection('/operators/spatial/endpoints', scope, 'endpoint', signal) },
    sessions: { list: (scope, signal) => getEntityCollection('/operators/spatial/sessions', scope, 'session', signal) },
    resources: {
      async get(scope, signal) {
        const path = '/operators/spatial/resources'
        const raw = await request(path, scope, signal)
        const parsed = resourceSummarySchema.safeParse(raw)
        if (!parsed.success) throw malformed(path)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
    },
    events: {
      async history(scope, cursor, signal) {
        const path = cursor ? `/operators/spatial/events?after=${encodeURIComponent(cursor)}` : '/operators/spatial/events'
        const parsed = parseEventCollection(await request(path, scope, signal), path)
        assertSpatialScope(scope, parsed.nodeId)
        return parsed
      },
    },
    hooks: {
      async list(scope, signal) {
        const path = '/operators/spatial/hooks'
        const raw = await request(path, scope, signal)
        const envelope = z.object({ node_id: spatialIdSchema, items: z.array(z.unknown()) }).strip().safeParse(raw)
        if (!envelope.success) throw malformed(path)
        assertSpatialScope(scope, envelope.data.node_id)
        return envelope.data.items.map((item) => {
          const parsed = hookSummarySchema.safeParse(item)
          if (!parsed.success) throw malformed(path)
          return parsed.data
        })
      },
    },
    workspace: {
      async get(scope, signal) {
        const path = '/operators/spatial/workspace'
        const parsed = parseSpatialWorkspace(await request(path, scope, signal))
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Spatial Workspace contract rejected.', path, undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
    },
    relation: {
      async get(scope, relationRef, signal) {
        const path = `/operators/spatial/relations/${encodeURIComponent(relationRef)}`
        const parsed = parseSpatialRelation(await request(path, scope, signal))
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Spatial relation contract rejected.', path, undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
    },
    recovery: {
      async plan(scope, command, signal) {
        const path = '/operators/spatial/recovery/plan'
        const parsed = parseSpatialRecoveryCommand(await request(path, scope, signal, 'POST', command))
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Spatial recovery plan contract rejected.', path, undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
      async apply(scope, command, confirmed, signal) {
        const path = '/operators/spatial/recovery/apply'
        const parsed = parseSpatialRecoveryResult(await request(path, scope, signal, 'POST', { command, confirmed }))
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Spatial recovery result contract rejected.', path, undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
    },
    remoteMediation: {
      async provenance(scope, endpointRef, signal) {
        const path = `/operators/spatial/endpoints/${encodeURIComponent(endpointRef)}/provenance`
        const parsed = parseSpatialEndpointProvenance(await request(path, scope, signal))
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Endpoint provenance contract rejected.', path, undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
      async plan(scope, frame, signal) {
        const path = '/operators/spatial/endpoint-tests/plan'
        const parsed = parseSpatialEndpointTestFrame(await request(path, scope, signal, 'POST', frame))
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Endpoint test frame contract rejected.', path, undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
      async submit(scope, remoteRequest, signal) {
        const path = '/operators/spatial/endpoint-tests/submit'
        const envelope = z.object({ result: z.unknown(), accounting: z.unknown() }).strip().safeParse(await request(path, scope, signal, 'POST', remoteRequest))
        if (!envelope.success) throw malformed(path)
        const result = parseSpatialRemoteResult(envelope.data.result)
        const accounting = parseSpatialResourceAccounting(envelope.data.accounting)
        if (!result.ok || !accounting.ok) throw malformed(path)
        assertSpatialScope(scope, result.data.provenance.node_id)
        return { result: result.data, accounting: accounting.data }
      },
      async cancel(scope, requestId, signal) {
        const path = '/operators/spatial/endpoint-tests/cancel'
        const parsed = parseSpatialEndpointTestFrame(await request(path, scope, signal, 'POST', { request_id: requestId }))
        if (!parsed.ok) throw new SpatialApiError(parsed.diagnostic.code === 'INCOMPATIBLE_SCHEMA_VERSION' ? 'incompatible' : 'malformed', 'Endpoint test cancellation contract rejected.', path, undefined, parsed.diagnostic.contract)
        assertSpatialScope(scope, parsed.data.node_id)
        return parsed.data
      },
    },
  }
}
