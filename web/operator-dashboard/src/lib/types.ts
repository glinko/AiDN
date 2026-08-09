import { z } from 'zod'

const numberValue = z.coerce.number().catch(0)
const stringValue = z.string().catch('')
const unknownRecord = z.record(z.string(), z.unknown())

const actionSchema = z.object({
  kind: stringValue,
  label: stringValue,
  detail: stringValue,
  screen: z.string().optional(),
}).passthrough()

const nodeIdentitySchema = z.object({
  node_id: z.string().optional(),
  operator_id: z.string().optional(),
  base_url: z.string().optional(),
  owner_wallet_id: z.string().optional(),
  ownership_configured: z.boolean().optional(),
}).passthrough()

const walletSchema = z.object({
  configured: z.boolean().catch(false),
  wallet_id: z.string().optional(),
  public_key: z.string().optional(),
  label: z.string().optional(),
}).passthrough()

export const bundleSchema = z.object({
  bundle_id: stringValue,
  plugin_id: z.string().optional(),
  provider_type: z.string().catch('unknown'),
  workload_type: z.string().optional(),
  model_id: z.string().catch('unknown'),
  enabled: z.boolean().catch(false),
  endpoint: z.string().nullable().optional(),
  runtime_status: z.string().catch('unknown'),
  publish_status: z.string().catch('unknown'),
  inventory_status: z.string().optional(),
  registry_status: z.string().optional(),
  drain_mode: z.boolean().optional(),
  endpoint_relationship: z.object({ state: z.string().optional() }).passthrough().optional(),
}).passthrough()

export const endpointSchema = z.object({
  endpoint_id: stringValue,
  display_name: z.string().nullable().optional(),
  bundle_id: z.string().nullable().optional(),
  model_class: z.string().nullable().optional(),
  capabilities: z.array(z.string()).catch([]),
  visibility: z.string().nullable().optional(),
  publication_status: z.string().catch('unknown'),
  publication_sync_status: z.string().optional(),
  runtime_status: z.string().catch('unknown'),
  publication_ready: z.boolean().optional(),
  validation: unknownRecord.optional(),
  validation_summary: unknownRecord.optional(),
}).passthrough()

const homeSchema = z.object({
  bootstrap: z.object({
    wallet_ready: z.boolean().catch(false),
    owner_wallet: walletSchema.optional(),
    node_identity: nodeIdentitySchema.optional(),
    provider_count: numberValue,
    bundle_count: numberValue,
    endpoint_count: numberValue,
    items: z.array(endpointSchema).catch([]),
  }).passthrough(),
}).passthrough()

const readinessStepSchema = z.object({
  key: stringValue,
  title: stringValue,
  status: z.string().catch('unknown'),
  summary: z.string().catch(''),
  detail: z.string().catch(''),
  blocking: z.boolean().catch(false),
  action: actionSchema.optional(),
  evidence: unknownRecord.optional(),
}).passthrough()

const readinessSchema = z.object({
  profile: z.string().optional(),
  overall_state: z.string().catch('unknown'),
  execution_ready: z.boolean().catch(false),
  network_ready: z.boolean().catch(false),
  progress: z.object({
    ready: numberValue,
    total: numberValue,
    percent: numberValue,
  }).passthrough(),
  next_action: actionSchema,
  steps: z.array(readinessStepSchema).catch([]),
}).passthrough()

const resourceSetSchema = z.object({
  cpu: numberValue,
  ram_mb: numberValue,
  vram_mb: numberValue,
}).passthrough()

const fleetSchema = z.object({
  node: nodeIdentitySchema.optional(),
  resources: z.object({
    total: resourceSetSchema,
    reserved: resourceSetSchema,
    free: resourceSetSchema,
    probe: unknownRecord.optional(),
  }).passthrough(),
  queue: z.object({
    queued: numberValue,
    active: numberValue,
    completed: numberValue,
    failed: numberValue,
  }).passthrough(),
  bundles: z.array(bundleSchema).catch([]),
}).passthrough()

const bundlePayloadSchema = z.object({
  summary: z.object({
    total: numberValue,
    enabled: numberValue,
    ready_to_publish: numberValue,
    first_endpoint_candidates: numberValue,
  }).passthrough(),
  items: z.array(bundleSchema).catch([]),
}).passthrough()

const endpointPayloadSchema = z.object({
  summary: z.object({
    total: numberValue,
    published: numberValue,
    configured: numberValue,
    validation_requested: numberValue,
    private: numberValue,
    shared: numberValue,
    public: numberValue,
  }).passthrough(),
  items: z.array(endpointSchema).catch([]),
}).passthrough()

export type DashboardHome = z.infer<typeof homeSchema>
export type Readiness = z.infer<typeof readinessSchema>
export type ReadinessStep = z.infer<typeof readinessStepSchema>
export type Fleet = z.infer<typeof fleetSchema>
export type BundlePayload = z.infer<typeof bundlePayloadSchema>
export type EndpointPayload = z.infer<typeof endpointPayloadSchema>
export type Bundle = z.infer<typeof bundleSchema>
export type Endpoint = z.infer<typeof endpointSchema>

export const dashboardSchemas = {
  home: homeSchema,
  readiness: readinessSchema,
  fleet: fleetSchema,
  bundles: bundlePayloadSchema,
  endpoints: endpointPayloadSchema,
}
