import { z } from 'zod'

import { SPATIAL_INTENT_KINDS, type SpatialIntentKind } from '@/spatial/contracts'

export const SPATIAL_COMPONENT_IDS = [
  'text-response',
  'conversation-surface',
  'key-value-summary',
  'status-summary',
  'endpoint-summary',
  'operation-notice',
  'endpoint-list',
  'endpoint-comparison',
  'node-resource-summary',
  'agent-details',
  'session-list',
  'hook-delivery-summary',
  'action-feedback',
  'resource-balance',
  'resource-usage',
  'resource-cost-editor',
  'resource-contribution-chart',
  'settlement-history',
  'deposit-status',
  'usage-evidence',
  'dispute-status',
] as const

export type SpatialComponentId = (typeof SPATIAL_COMPONENT_IDS)[number]
export type SpatialComponentViewport = 'MOBILE' | 'TABLET' | 'DESKTOP'
export type SpatialComponentCategory = 'content' | 'status' | 'interaction' | 'topology' | 'resource' | 'configuration' | 'feedback'
export type SpatialComponentState = 'loading' | 'empty' | 'ready' | 'stale' | 'offline' | 'error' | 'disabled' | 'approval-required'

export type SpatialComponentVariant = {
  data_schema?: z.ZodType<unknown>
  props_schema?: z.ZodType<unknown>
  required_capabilities?: readonly string[]
  renderer?: string
}

export type SpatialComponentMigration = {
  from_version: string
  to_version: string
  migrate: (data: unknown) => unknown
}

export type SpatialComponentDefinition = {
  component_id: SpatialComponentId | string
  version: string
  props_schema: z.ZodType<unknown>
  data_schema: z.ZodType<unknown>
  supported_intents: readonly SpatialIntentKind[]
  required_capabilities: readonly string[]
  allowed_actions: readonly string[]
  accessibility_contract: {
    role: string
    name_required: boolean
    live_region?: 'polite' | 'assertive' | 'off'
    keyboard_operable: boolean
  }
  material_profile: 'TEXT' | 'GLASS' | 'STATUS' | 'TABLE' | 'NOTICE'
  supported_viewports: readonly SpatialComponentViewport[]
  renderers: {
    classic: string
    spatial: string
    loading: string
    empty: string
    error: string
  }
  category?: SpatialComponentCategory
  minimum_data_revision?: number
  mutation_intent_schema?: z.ZodType<unknown> | null
  capability_visibility?: Readonly<Record<string, readonly string[]>>
  variants?: Partial<Record<'compact' | 'summary' | 'detail' | 'config', SpatialComponentVariant>>
  stream_support?: 'none' | 'append' | 'replace'
  virtualization?: { required: boolean; item_budget?: number }
  viewport_constraints?: { min_width?: number; max_width?: number; allowed?: readonly SpatialComponentViewport[] }
  feature_flag?: string | null
  deprecation?: { state: 'active' | 'deprecated' | 'removed'; replacement?: string; remove_after?: string }
  supported_states?: readonly SpatialComponentState[]
  migrations?: readonly SpatialComponentMigration[]
  localization?: { label_key: string; description_key?: string }
  provenance?: { required: boolean }
}

export type SpatialComponentRecord = Omit<SpatialComponentDefinition, 'props_schema' | 'data_schema'> & {
  props_schema: z.ZodType<unknown>
  data_schema: z.ZodType<unknown>
}

export type ComponentRegistryErrorCode =
  | 'UNKNOWN_COMPONENT'
  | 'VERSION_MISMATCH'
  | 'INVALID_PROPS'
  | 'INVALID_DATA'
  | 'UNSAFE_PAYLOAD'
  | 'DUPLICATE_COMPONENT'
  | 'UNSUPPORTED_ACTION'
  | 'UNSUPPORTED_VIEWPORT'
  | 'DEPRECATED_COMPONENT'
  | 'MISSING_CAPABILITY'
  | 'MIGRATION_UNAVAILABLE'

export class ComponentRegistryError extends Error {
  readonly code: ComponentRegistryErrorCode

  constructor(code: ComponentRegistryErrorCode, message: string) {
    super(message)
    this.name = 'ComponentRegistryError'
    this.code = code
  }
}

const emptyRecordSchema = z.record(z.string().min(1).max(128), z.unknown()).default({})
const textResponseDataSchema = z.object({ text: z.string().max(32_000).default(''), citations: z.array(z.string().max(256)).max(256).default([]) }).strip()
const conversationDataSchema = z.object({ session_id: z.string().min(1).default('pending'), turn_ids: z.array(z.string().min(1)).max(10_000).default([]), streaming: z.boolean().default(false) }).strip()
const keyValueDataSchema = z.object({ entries: z.array(z.object({ key: z.string().max(240), value: z.string().max(4_000) }).strip()).max(512).default([]) }).strip()
const statusDataSchema = z.object({ state: z.string().max(96).default('UNKNOWN'), label: z.string().max(240).default('No status reported'), detail: z.string().max(2_000).optional() }).strip()
const endpointDataSchema = z.object({ endpoint_ref: z.string().min(1).default('pending'), endpoint_type: z.string().max(240).default('unknown'), status: z.string().max(96).default('UNKNOWN'), capabilities: z.array(z.string().max(128)).max(128).default([]) }).strip()
const noticeDataSchema = z.object({ severity: z.enum(['INFO', 'SUCCESS', 'WARNING', 'ERROR']).default('INFO'), message: z.string().max(2_000).default('No operation notice'), action_ref: z.string().max(128).nullable().optional() }).strip()
const listDataSchema = z.object({ items: z.array(z.record(z.string().max(128), z.unknown())).max(10_000).default([]), total: z.number().int().nonnegative().optional() }).strip()
const feedbackDataSchema = z.object({ action_id: z.string().max(128), state: z.enum(['PROPOSED', 'NEEDS_CLARIFICATION', 'AWAITING_APPROVAL', 'EXECUTING', 'PARTIALLY_COMPLETED', 'COMPLETED', 'REJECTED', 'ROLLED_BACK', 'FINALITY_PENDING']), summary: z.string().max(2_000), evidence_refs: z.array(z.string().max(256)).max(256).default([]) }).strip()

function normalizeComponentId(id: string): string {
  return id.trim().replace(/[A-Z]/g, (character) => `-${character.toLowerCase()}`).replace(/^-/, '')
}

function containsUnsafeValue(value: unknown, path = ''): string | null {
  if (typeof value === 'function' || typeof value === 'symbol' || typeof value === 'bigint') return path || '<root>'
  if (typeof value === 'string') {
    if (/<\/?(script|iframe|object|embed|style)\b/i.test(value) || /javascript\s*:/i.test(value)) return path || '<root>'
    return null
  }
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = containsUnsafeValue(value[index], `${path}[${index}]`)
      if (found) return found
    }
    return null
  }
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (/^(?:on[a-z]+|__proto__|constructor|prototype)$/i.test(key)) return path ? `${path}.${key}` : key
      const found = containsUnsafeValue(child, path ? `${path}.${key}` : key)
      if (found) return found
    }
  }
  return null
}

function builtinDefinition(
  componentId: SpatialComponentId,
  dataSchema: z.ZodType<unknown>,
  materialProfile: SpatialComponentDefinition['material_profile'],
  allowedActions: readonly string[],
  role: string,
  liveRegion: SpatialComponentDefinition['accessibility_contract']['live_region'] = 'off',
): SpatialComponentDefinition {
  return {
    component_id: componentId,
    version: '1.0.0',
    props_schema: emptyRecordSchema,
    data_schema: dataSchema,
    supported_intents: [...SPATIAL_INTENT_KINDS],
    required_capabilities: [],
    allowed_actions: allowedActions,
    accessibility_contract: { role, name_required: true, live_region: liveRegion, keyboard_operable: true },
    material_profile: materialProfile,
    supported_viewports: ['MOBILE', 'TABLET', 'DESKTOP'],
    renderers: {
      classic: componentId,
      spatial: componentId,
      loading: `${componentId}:loading`,
      empty: `${componentId}:empty`,
      error: `${componentId}:error`,
    },
    category: materialProfile === 'STATUS' ? 'status' : materialProfile === 'NOTICE' ? 'feedback' : 'content',
    stream_support: 'none',
    supported_states: ['loading', 'empty', 'ready', 'stale', 'offline', 'error', 'disabled'],
    provenance: { required: true },
  }
}

export const DEFAULT_SPATIAL_COMPONENTS: readonly SpatialComponentDefinition[] = [
  builtinDefinition('text-response', textResponseDataSchema, 'TEXT', ['copy', 'open-source'], 'article', 'polite'),
  builtinDefinition('conversation-surface', conversationDataSchema, 'GLASS', ['collapse', 'retry', 'cancel', 'branch'], 'log', 'polite'),
  builtinDefinition('key-value-summary', keyValueDataSchema, 'TABLE', ['copy'], 'table'),
  builtinDefinition('status-summary', statusDataSchema, 'STATUS', ['open-source'], 'status'),
  builtinDefinition('endpoint-summary', endpointDataSchema, 'GLASS', ['open-endpoint'], 'region'),
  builtinDefinition('operation-notice', noticeDataSchema, 'NOTICE', ['dismiss', 'retry'], 'alert', 'assertive'),
  { ...builtinDefinition('endpoint-list', listDataSchema, 'TABLE', ['inspect'], 'list'), category: 'topology', virtualization: { required: true, item_budget: 100 }, variants: { compact: { data_schema: listDataSchema }, detail: { data_schema: listDataSchema } } },
  { ...builtinDefinition('endpoint-comparison', listDataSchema, 'TABLE', ['inspect'], 'table'), category: 'topology', virtualization: { required: true, item_budget: 50 } },
  { ...builtinDefinition('node-resource-summary', listDataSchema, 'STATUS', ['inspect'], 'region'), category: 'resource' },
  { ...builtinDefinition('agent-details', keyValueDataSchema, 'GLASS', ['inspect'], 'region'), category: 'status' },
  { ...builtinDefinition('session-list', listDataSchema, 'TABLE', ['inspect'], 'list'), category: 'content', virtualization: { required: true, item_budget: 100 } },
  { ...builtinDefinition('hook-delivery-summary', listDataSchema, 'TABLE', ['inspect', 'retry'], 'region'), category: 'feedback' },
  { ...builtinDefinition('action-feedback', feedbackDataSchema, 'NOTICE', ['dismiss', 'retry'], 'status', 'polite'), category: 'feedback', supported_states: ['loading', 'ready', 'error', 'approval-required'] },
  { ...builtinDefinition('resource-balance', listDataSchema, 'STATUS', ['inspect'], 'region'), category: 'resource' },
  { ...builtinDefinition('resource-usage', listDataSchema, 'STATUS', ['inspect'], 'region'), category: 'resource' },
  { ...builtinDefinition('resource-cost-editor', listDataSchema, 'GLASS', ['propose-change'], 'form'), category: 'configuration', required_capabilities: ['resource:change'] },
  { ...builtinDefinition('resource-contribution-chart', listDataSchema, 'TABLE', ['inspect'], 'figure'), category: 'resource' },
  { ...builtinDefinition('settlement-history', listDataSchema, 'TABLE', ['inspect'], 'region'), category: 'resource', virtualization: { required: true, item_budget: 100 } },
  { ...builtinDefinition('deposit-status', statusDataSchema, 'STATUS', ['inspect'], 'status'), category: 'resource' },
  { ...builtinDefinition('usage-evidence', listDataSchema, 'TABLE', ['inspect'], 'region'), category: 'resource' },
  { ...builtinDefinition('dispute-status', statusDataSchema, 'STATUS', ['inspect'], 'status'), category: 'resource' },
]

export type ComponentRegistryAction = {
  component_id: string
  component_version: string
  action_id: string
  target_refs: readonly string[]
  operation: {
    kind: 'component-action'
    action_id: string
    component_id: string
    target_refs: readonly string[]
    payload: Record<string, unknown>
  }
}

/** Registry keeps remote payloads declarative: no executable renderers or HTML are accepted. */
export class SpatialComponentRegistry {
  private readonly records = new Map<string, SpatialComponentRecord>()

  constructor(definitions: readonly SpatialComponentDefinition[] = DEFAULT_SPATIAL_COMPONENTS) {
    definitions.forEach((definition) => this.register(definition))
  }

  register(definition: SpatialComponentDefinition): SpatialComponentRecord {
    const componentId = normalizeComponentId(definition.component_id)
    const key = `${componentId}@${definition.version}`
    if (this.records.has(key)) throw new ComponentRegistryError('DUPLICATE_COMPONENT', 'component version is already registered')
    const { props_schema: _props, data_schema: _data, mutation_intent_schema: _mutation, migrations: _migrations, variants: rawVariants, ...metadata } = definition
    const variants = rawVariants
      ? Object.fromEntries(Object.entries(rawVariants).map(([name, variant]) => {
          if (!variant) return [name, variant]
          const { data_schema: _variantData, props_schema: _variantProps, ...safeVariant } = variant
          return [name, safeVariant]
        }))
      : undefined
    const unsafe = containsUnsafeValue({ ...metadata, variants, component_id: componentId })
    if (unsafe) throw new ComponentRegistryError('UNSAFE_PAYLOAD', 'component metadata contains executable or HTML content')
    const record = { ...definition, component_id: componentId }
    this.records.set(key, record)
    return record
  }

  resolve(componentId: string, version?: string): SpatialComponentRecord {
    const normalized = normalizeComponentId(componentId)
    const candidates = [...this.records.entries()].filter(([key]) => key.startsWith(`${normalized}@`))
    if (!candidates.length) throw new ComponentRegistryError('UNKNOWN_COMPONENT', `component ${normalized} is not registered`)
    if (version) {
      const exact = this.records.get(`${normalized}@${version}`)
      if (!exact) throw new ComponentRegistryError('VERSION_MISMATCH', `component ${normalized} does not support ${version}`)
      if (exact.deprecation?.state === 'removed') throw new ComponentRegistryError('DEPRECATED_COMPONENT', `component ${normalized} has been removed`)
      return exact
    }
    const record = candidates.sort((left, right) => right[1].version.localeCompare(left[1].version))[0]![1]
    if (record.deprecation?.state === 'removed') throw new ComponentRegistryError('DEPRECATED_COMPONENT', `component ${normalized} has been removed`)
    return record
  }

  resolveForViewport(componentId: string, viewport: SpatialComponentViewport, version?: string, fallbackId = 'text-response'): { record: SpatialComponentRecord; fallback: boolean } {
    const record = this.resolve(componentId, version)
    const allowed = record.viewport_constraints?.allowed ?? record.supported_viewports
    if (allowed.includes(viewport)) return { record, fallback: false }
    if (!fallbackId || fallbackId === record.component_id) throw new ComponentRegistryError('UNSUPPORTED_VIEWPORT', `component ${record.component_id} is not available for ${viewport}`)
    return { record: this.resolve(fallbackId), fallback: true }
  }

  validateVariant(componentId: string, version: string | undefined, variant: 'compact' | 'summary' | 'detail' | 'config', data: unknown, grantedCapabilities: readonly string[] = []): unknown {
    const record = this.resolve(componentId, version)
    const selected = record.variants?.[variant]
    if (!selected) throw new ComponentRegistryError('INVALID_DATA', `component ${record.component_id} has no ${variant} variant`)
    const required = selected.required_capabilities ?? []
    if (required.some((capability) => !grantedCapabilities.includes(capability))) throw new ComponentRegistryError('MISSING_CAPABILITY', `component ${record.component_id} variant ${variant} requires a declared capability`)
    const schema = selected.data_schema ?? record.data_schema
    const parsed = schema.safeParse(data)
    if (!parsed.success) throw new ComponentRegistryError('INVALID_DATA', `component ${record.component_id} ${variant} data does not match the registered schema`)
    return parsed.data
  }

  migrateData(componentId: string, fromVersion: string, toVersion: string, data: unknown): unknown {
    if (fromVersion === toVersion) return this.validateData(componentId, toVersion, data)
    const record = this.resolve(componentId, toVersion)
    const migrations = record.migrations ?? []
    let current = fromVersion
    let value = data
    const visited = new Set<string>()
    while (current !== toVersion) {
      if (visited.has(current)) throw new ComponentRegistryError('MIGRATION_UNAVAILABLE', `migration cycle for ${componentId}`)
      visited.add(current)
      const migration = migrations.find((candidate) => candidate.from_version === current)
      if (!migration) throw new ComponentRegistryError('MIGRATION_UNAVAILABLE', `no migration from ${current} to ${toVersion}`)
      value = migration.migrate(value)
      current = migration.to_version
    }
    return this.validateData(componentId, toVersion, value)
  }

  assertActionCapability(componentId: string, version: string | undefined, actionId: string, grantedCapabilities: readonly string[] = []): SpatialComponentRecord {
    const record = this.resolve(componentId, version)
    if (!record.allowed_actions.includes(actionId)) throw new ComponentRegistryError('UNSUPPORTED_ACTION', 'component action is not allowlisted')
    const required = record.capability_visibility?.[actionId] ?? record.required_capabilities
    if (required.some((capability) => !grantedCapabilities.includes(capability))) throw new ComponentRegistryError('MISSING_CAPABILITY', `component action ${actionId} requires a declared capability`)
    return record
  }

  validateProps(componentId: string, version: string | undefined, props: unknown): unknown {
    const record = this.resolve(componentId, version)
    const unsafe = containsUnsafeValue(props)
    if (unsafe) throw new ComponentRegistryError('UNSAFE_PAYLOAD', `unsafe component props at ${unsafe}`)
    const parsed = record.props_schema.safeParse(props)
    if (!parsed.success) throw new ComponentRegistryError('INVALID_PROPS', 'component props do not match the registered schema')
    return parsed.data
  }

  validateData(componentId: string, version: string | undefined, data: unknown): unknown {
    const record = this.resolve(componentId, version)
    const unsafe = containsUnsafeValue(data)
    if (unsafe) throw new ComponentRegistryError('UNSAFE_PAYLOAD', `unsafe component data at ${unsafe}`)
    const parsed = record.data_schema.safeParse(data)
    if (!parsed.success) throw new ComponentRegistryError('INVALID_DATA', 'component data do not match the registered schema')
    return parsed.data
  }

  createActionIntent(input: {
    componentId: string
    version?: string
    actionId: string
    targetRefs?: readonly string[]
    payload?: Record<string, unknown>
    grantedCapabilities?: readonly string[]
  }): ComponentRegistryAction {
    const record = this.assertActionCapability(input.componentId, input.version, input.actionId, input.grantedCapabilities)
    const targetRefs = [...(input.targetRefs ?? [])]
    const payload = input.payload ?? {}
    const unsafe = containsUnsafeValue(payload)
    if (unsafe) throw new ComponentRegistryError('UNSAFE_PAYLOAD', `unsafe action payload at ${unsafe}`)
    return {
      component_id: record.component_id,
      component_version: record.version,
      action_id: input.actionId,
      target_refs: targetRefs,
      operation: { kind: 'component-action', action_id: input.actionId, component_id: record.component_id, target_refs: targetRefs, payload: { ...payload } },
    }
  }

  list(): SpatialComponentRecord[] {
    return [...this.records.values()]
  }

  snapshot(): Array<Omit<SpatialComponentRecord, 'props_schema' | 'data_schema'>> {
    return this.list().map(({ props_schema: _props, data_schema: _data, ...metadata }) => metadata)
  }
}

export const ComponentRegistry = SpatialComponentRegistry

export function createSpatialComponentRegistry(definitions?: readonly SpatialComponentDefinition[]): SpatialComponentRegistry {
  return new SpatialComponentRegistry(definitions)
}

export function isSpatialIntentKindSupported(record: SpatialComponentRecord, kind: SpatialIntentKind): boolean {
  return record.supported_intents.includes(kind)
}
