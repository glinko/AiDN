import { describe, expect, it } from 'vitest'

import {
  SPATIAL_SCHEMA_VERSIONS,
  normalizeSpatialFreshness,
  normalizeSpatialTimestamp,
  parseSpatialContract,
  parseSpatialEntity,
  parseSpatialNodeStatus,
  parseSpatialPrimaryAgentGrant,
  parseSpatialPrimaryAgentSlot,
  parseSpatialPrimaryAgentState,
  parseSpatialRelation,
  parseSpatialViewport,
  parseSpatialWorkspace,
  spatialContractSchemas,
} from '@/spatial/contracts'
import { spatialContractFixtures } from '@/spatial/contracts/fixtures'

describe('Spatial M2.1 shared contract boundary', () => {
  it('accepts a compatible additive payload while normalizing ids, revisions, and timestamps', () => {
    const result = parseSpatialEntity(spatialContractFixtures.goodAgent)
    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.data.kind).toBe('agent')
    expect(result.data.revision).toBe(7)
    expect(result.data.state).toBe('READY')
    expect(result.data.availability).toBe('AVAILABLE')
    expect(result.data.freshness.observed_at).toBe('2026-09-05T16:00:00.000Z')
    expect('additive_dashboard_field' in result.data).toBe(false)
  })

  it('derives STALE once a fresh record crosses its explicit TTL', () => {
    const result = parseSpatialEntity(spatialContractFixtures.staleEndpoint)
    expect(result.ok).toBe(true)
    if (!result.ok) return

    const freshness = normalizeSpatialFreshness(result.data.freshness, new Date('2026-09-05T12:10:00Z'))
    expect(freshness.state).toBe('STALE')
    expect(freshness.age_seconds).toBe(7800)
  })

  it('keeps partial and unknown evidence explicit instead of inferring online', () => {
    const result = parseSpatialNodeStatus(spatialContractFixtures.partialStatus)
    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.data.state).toBe('DEGRADED')
    expect(result.data.freshness.state).toBe('PARTIAL')
    expect(result.data.components[1]?.state).toBe('UNKNOWN')
    expect(result.data.components[1]?.freshness.state).toBe('UNKNOWN')
  })

  it('rejects malformed payloads before they can reach a store', () => {
    const result = parseSpatialRelation(spatialContractFixtures.malformedRelation)
    expect(result).toMatchObject({
      ok: false,
      diagnostic: {
        code: 'MALFORMED_PAYLOAD',
        contract: SPATIAL_SCHEMA_VERSIONS.relation,
      },
    })
    if (result.ok) return
    expect(result.diagnostic.path).toMatch(/relation_id|created_at/)
    expect(JSON.stringify(result.diagnostic)).not.toContain('not-a-timestamp')
    expect(JSON.stringify(result.diagnostic)).not.toContain('fixture-secret')
  })

  it('returns an explicit incompatible state for a breaking schema version', () => {
    const result = parseSpatialEntity(spatialContractFixtures.incompatibleEntityVersion)
    expect(result).toMatchObject({
      ok: false,
      diagnostic: {
        code: 'INCOMPATIBLE_SCHEMA_VERSION',
        contract: SPATIAL_SCHEMA_VERSIONS.entity,
        expected_version: SPATIAL_SCHEMA_VERSIONS.entity,
        received_version: 'spatial.entity.v2',
        path: 'schema_version',
      },
    })
  })

  it('normalizes equivalent timestamps in one shared helper', () => {
    expect(normalizeSpatialTimestamp('2026-09-05T12:00:00-04:00')).toBe('2026-09-05T16:00:00.000Z')
    expect(normalizeSpatialTimestamp(new Date('2026-09-05T16:00:00Z'))).toBe('2026-09-05T16:00:00.000Z')
    expect(normalizeSpatialTimestamp('not-a-timestamp')).toBeNull()
  })

  it('exposes the typed contracts without importing renderer modules', () => {
    expect(Object.keys(spatialContractSchemas)).toEqual(['entity', 'relation', 'status', 'workspace', 'viewport', 'primaryAgentSlot', 'primaryAgentGrant', 'primaryAgentState'])
    expect(spatialContractSchemas.entity).toBeTruthy()
    expect(spatialContractSchemas.relation).toBeTruthy()
    expect(spatialContractSchemas.status).toBeTruthy()
    expect(spatialContractSchemas.workspace).toBeTruthy()
    expect(spatialContractSchemas.viewport).toBeTruthy()
    expect(spatialContractSchemas.primaryAgentSlot).toBeTruthy()
    expect(spatialContractSchemas.primaryAgentGrant).toBeTruthy()
    expect(spatialContractSchemas.primaryAgentState).toBeTruthy()

    const generic = parseSpatialContract(
      SPATIAL_SCHEMA_VERSIONS.entity,
      spatialContractSchemas.entity,
      spatialContractFixtures.goodAgent,
    )
    expect(generic.ok).toBe(true)
  })

  it('keeps semantic Workspace and device-local viewport contracts separate', () => {
    const workspace = parseSpatialWorkspace(spatialContractFixtures.goodWorkspace)
    const viewport = parseSpatialViewport(spatialContractFixtures.goodViewport)
    expect(workspace.ok).toBe(true)
    expect(viewport.ok).toBe(true)
    if (!workspace.ok || !viewport.ok) return
    expect(workspace.data.semantic_revision).toBe(21)
    expect(viewport.data.presentation_revision).toBe(3)
    expect(viewport.data.workspace_id).toBe(workspace.data.workspace_id)
    expect(workspace.data.cluster_membership).toEqual({})
    expect('presentation_revision' in workspace.data).toBe(false)
    expect('semantic_revision' in viewport.data).toBe(false)
  })

  it('parses the Node-owned Primary Agent Slot contract', () => {
    const slot = parseSpatialPrimaryAgentSlot(spatialContractFixtures.unassignedPrimaryAgentSlot)
    expect(slot).toMatchObject({ ok: true })
    if (!slot.ok) return
    expect(slot.data.lifecycle_state).toBe('UNASSIGNED')
    expect(slot.data.current_binding_id).toBeNull()
  })

  it('parses grant and operational-state records without credential material', () => {
    const grant = parseSpatialPrimaryAgentGrant({ ...spatialContractFixtures.primaryAgentGrant, token: 'never-accepted' })
    const state = parseSpatialPrimaryAgentState(spatialContractFixtures.primaryAgentState)
    expect(grant).toMatchObject({ ok: true })
    expect(state).toMatchObject({ ok: true })
    if (!grant.ok || !state.ok) return
    expect(grant.data.categories).toEqual(['read', 'action'])
    expect('token' in grant.data).toBe(false)
    expect(state.data.state).toBe('READY')
  })
})
