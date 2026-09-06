import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { componentInventory, endpointConfigurationInventory, validateComponentInventory } from '@/app/component-inventory'
import { endpointSummaryFromSpatial } from '@/components/shared/endpoint-summary-model'
import {
  DEFAULT_SPATIAL_COMPONENTS,
  SpatialComponentRegistry,
} from '@/spatial/interaction/component-registry'
import { ChangeIntentService, createActionFeedback, formatQAtoms, planSpatialQuery, transitionActionFeedback } from '@/spatial/components'
import { parseSpatialResourceSummary, SPATIAL_SCHEMA_VERSIONS } from '@/spatial/contracts'

const now = '2026-09-05T16:00:00.000Z'

function expectCode(run: () => unknown, code: string) {
  try {
    run()
    throw new Error(`expected ${code}`)
  } catch (error) {
    expect(error).toMatchObject({ code })
  }
}

describe('M10 component inventory and Registry v2', () => {
  it('assigns every current fragment exactly once and traces EndpointConfiguration', () => {
    expect(componentInventory.length).toBeGreaterThanOrEqual(15)
    expect(validateComponentInventory()).toEqual([])
    expect(endpointConfigurationInventory.reusable_boundary).toContain('EndpointConfiguration')
    expect(endpointConfigurationInventory.data_source).toContain('dashboardApi.endpoints')
  })

  it('migrates versions, falls back unsupported viewports and enforces config capabilities', () => {
    const registry = new SpatialComponentRegistry([...DEFAULT_SPATIAL_COMPONENTS, {
      component_id: 'config-test', version: '2.0.0', props_schema: z.record(z.string(), z.unknown()), data_schema: z.object({ value: z.string() }),
      supported_intents: ['change'], required_capabilities: [], allowed_actions: ['apply'],
      accessibility_contract: { role: 'region', name_required: true, keyboard_operable: true }, material_profile: 'GLASS', supported_viewports: ['DESKTOP'],
      renderers: { classic: 'config-test', spatial: 'config-test', loading: 'loading', empty: 'empty', error: 'error' },
      variants: { config: { data_schema: z.object({ value: z.string() }), required_capabilities: ['endpoint:change'] } },
      migrations: [{ from_version: '1.0.0', to_version: '2.0.0', migrate: (value) => ({ value: String((value as { old: string }).old) }) }],
    }])
    expect(registry.migrateData('config-test', '1.0.0', '2.0.0', { old: '8080' })).toEqual({ value: '8080' })
    expect(registry.resolveForViewport('config-test', 'MOBILE').fallback).toBe(true)
    expectCode(() => registry.validateVariant('config-test', '2.0.0', 'config', { value: '8080' }), 'MISSING_CAPABILITY')
    expect(registry.validateVariant('config-test', '2.0.0', 'config', { value: '8080' }, ['endpoint:change'])).toEqual({ value: '8080' })
    expectCode(() => new SpatialComponentRegistry([{ ...registry.resolve('config-test'), component_id: 'removed', deprecation: { state: 'removed' } }]).resolve('removed'), 'DEPRECATED_COMPONENT')
  })
})

describe('M10 shared EndpointSummary and Change Intent', () => {
  it('preserves the same semantic endpoint model in Spatial', () => {
    const model = endpointSummaryFromSpatial({
      schema_version: SPATIAL_SCHEMA_VERSIONS.endpointDetails, workspace_id: 'w', node_id: 'n', canonical_ref: 'endpoint:e', endpoint_id: 'e', revision: 7,
      display_name: 'Text endpoint', capability: 'llm.chat', endpoint_type: 'mediated', supported_modalities: ['text'], availability: 'AVAILABLE', surface_state: 'READY',
      freshness: { state: 'FRESH', observed_at: now, stale_after_seconds: 60, source: 'node:e' }, latency: { p50_ms: null, p95_ms: null, measured_at: null, window: null }, load: null, capacity: null,
      cost: { currency: null, unit_price: null, billing_dimension: null, minimum_charge: null }, deposit: { minimum: null, recommended: null, currency: null, escrow: null }, provider_ref: 'node:e', remote_agent_ref: null,
      validation_refs: [], input_formats: ['text/plain'], output_formats: ['text/plain'], limits: { context_tokens: null, payload_bytes: null, timeout_ms: null, streaming: null }, privacy: null, trust_summary: null, description: null, allowed_actions: [],
    })
    expect(model.canonicalRef).toBe('endpoint:e')
    expect(model.revision).toBe(7)
    expect(model.provenanceRef).toBe('node:e')
  })

  it('uses one deterministic diff for form, voice and Spatial sources and applies only explicitly', () => {
    const service = new ChangeIntentService({ idFactory: (prefix) => `${prefix}-fixed` })
    const base = { workspaceId: 'w', nodeId: 'n', target: { type: 'endpoint' as const, id: 'endpoint:e', revision: 4 }, current: { port: 8080, enabled: true }, proposed: { port: 8081, enabled: true }, fieldSchema: [{ path: 'port', type: 'integer' as const, editable: true }, { path: 'enabled', type: 'boolean' as const, editable: true }], actorRef: 'operator:a', idempotencyKey: 'change-1', currentRevision: 4 }
    const form = service.create({ ...base, source: 'form' })
    const voice = service.create({ ...base, source: 'voice', intentId: 'change-voice', naturalLanguageSummary: 'Move the port' })
    expect(form.diff).toEqual(voice.diff)
    const valid = service.validate(form, { currentRevision: 4, agentOnline: true, capabilities: ['endpoint:change'] })
    expect(valid.state).toBe('VALID')
    expectCode(() => service.apply(form, { confirm: false, validation: valid, applyCanonical: () => ({ revision: 5, resultRef: 'result:5' }) }), 'NOT_EXPLICIT')
    const applied = service.apply(form, { confirm: true, validation: valid, applyCanonical: () => ({ revision: 5, resultRef: 'result:5' }) })
    expect(applied.revision).toBe(5)
    expect(service.apply(form, { confirm: true, validation: valid, applyCanonical: () => ({ revision: 6, resultRef: 'result:6' }) }).status).toBe('duplicate')
    expect(service.validate(form, { currentRevision: 5, agentOnline: true, capabilities: ['endpoint:change'] }).state).toBe('STALE')
    expect(service.validate(form, { currentRevision: 4, agentOnline: true, capabilities: ['endpoint:change'], occupied: (path, value) => path === 'port' && value === 8081 }).state).toBe('OCCUPIED')
    expect(service.validate(form, { currentRevision: 4, agentOnline: true, capabilities: [] }).state).toBe('UNAUTHORIZED_FIELD')
    expect(service.validate(form, { currentRevision: 4, agentOnline: false, capabilities: ['endpoint:change'] }).state).toBe('AGENT_OFFLINE')
  })
})

describe('M10 query, resource and action semantics', () => {
  it('plans bounded reusable query compositions and preserves exact q_atoms', () => {
    const plan = planSpatialQuery({ intent: 'show-endpoints', viewport: 'MOBILE', registry: new SpatialComponentRegistry() })
    expect(plan.componentId).toBe('endpoint-list')
    expect(plan.virtualizationRequired).toBe(true)
    expect(new SpatialComponentRegistry().list().map((record) => record.component_id)).toEqual(expect.arrayContaining(['resource-balance', 'resource-usage', 'resource-cost-editor', 'resource-contribution-chart', 'settlement-history', 'deposit-status', 'usage-evidence', 'dispute-status']))
    expect(formatQAtoms('00042')).toBe('00042 Q')
    expect(parseSpatialResourceSummary({ schema_version: SPATIAL_SCHEMA_VERSIONS.resourceSummary, summary_id: 'summary:1', workspace_id: 'w', node_id: 'n', source_revision: 4, state: 'ZERO', balance_q_atoms: '00042', usage_q_atoms: '0', contribution_q_atoms: '12', cost_q_atoms: '0', rate_card_revision: 'rate:1', evidence_refs: [], observed_at: now }).ok).toBe(true)
  })

  it('models partial completion and attention without hidden reasoning', () => {
    const executing = createActionFeedback({ state: 'EXECUTING', summary: 'Applying endpoint change', completedRefs: [], remainingRefs: ['endpoint:e'], evidenceRefs: [], safeNextAction: null })
    const partial = transitionActionFeedback(executing, { state: 'PARTIALLY_COMPLETED', summary: 'Endpoint changed; publication remains', completedRefs: ['endpoint:e'], remainingRefs: ['publication:e'], evidenceRefs: ['result:5'], safeNextAction: 'publish-endpoint' })
    expect(partial.needsAttention).toBe(true)
    expect(() => transitionActionFeedback(partial, { state: 'PROPOSED', summary: 'bad', completedRefs: [], remainingRefs: [], evidenceRefs: [], safeNextAction: null })).toThrow()
  })
})
