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
  revision: numberValue,
  revision_of: z.string().nullable().optional(),
  bundle_hash: z.string().nullable().optional(),
  plugin_id: z.string().optional(),
  provider_type: z.string().catch('unknown'),
  workload_type: z.string().optional(),
  model_id: z.string().catch('unknown'),
  launch_mode: z.string().optional(),
  provider_api_format: z.string().nullable().optional(),
  device_affinity: z.string().optional(),
  resource_profile: unknownRecord.default({}),
  warm_policy: z.string().optional(),
  priority_class: numberValue,
  max_parallel_requests: numberValue,
  enabled: z.boolean().catch(false),
  endpoint: z.string().nullable().optional(),
  runtime_id: z.string().nullable().optional(),
  runtime_status: z.string().catch('unknown'),
  runtime_health_status: z.string().optional(),
  runtime_last_error: z.string().nullable().optional(),
  publish_status: z.string().catch('unknown'),
  bundle_readiness_status: z.string().optional(),
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
  local_agent_use: z.boolean().catch(false),
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

const walletDashboardSchema = z.object({
  owner_wallet: walletSchema,
  wallet_state: z.object({
    configured: z.boolean().catch(false),
    wallet_id: z.string().nullable().optional(),
    canonical_balance_q_atoms: numberValue,
    canonical_balance_q: numberValue,
    balance_source: z.string().catch('unknown'),
    balance_error: z.string().nullable().optional(),
    identity_state: z.string().catch('unknown'),
    identity_registration_state: z.string().catch('unknown'),
    identity: unknownRecord.nullable().optional(),
    identity_source: z.string().catch('unknown'),
    identity_error: z.string().nullable().optional(),
    identity_operation: unknownRecord.nullable().optional(),
    identity_operations: z.array(unknownRecord).catch([]),
    binding_state: z.string().catch('unknown'),
    pending_operation_count: numberValue,
    pending_transfer_q_atoms: numberValue,
  }).passthrough(),
  usage_events: z.array(unknownRecord).catch([]),
  allocation_events: z.array(unknownRecord).catch([]),
  dispute_events: z.array(unknownRecord).catch([]),
  ledger_events: z.array(unknownRecord).catch([]),
  ledger_operations: z.array(unknownRecord).catch([]),
  pending_operations: z.array(unknownRecord).catch([]),
  economics_summary: unknownRecord.default({}),
  economics_history: z.array(unknownRecord).catch([]),
  faucet_preview: unknownRecord.default({}),
}).passthrough()

const sessionDashboardSchema = z.object({
  owner_wallet: unknownRecord.optional(),
  node_identity: unknownRecord.optional(),
  summary: z.object({
    total: numberValue,
    active: numberValue,
    queued: numberValue,
    closed: numberValue,
    terminal: numberValue.optional(),
  }).passthrough(),
  items: z.array(unknownRecord).catch([]),
}).passthrough()

const marketDashboardSchema = z.object({
  query: unknownRecord.optional(),
  nodes: z.array(unknownRecord).catch([]),
  candidates: z.array(unknownRecord).catch([]),
  canonical_candidates: z.array(unknownRecord).catch([]),
  canonical_summary: unknownRecord.default({}),
  recommended_action: unknownRecord.optional(),
}).passthrough()

const remoteEndpointsDashboardSchema = z.object({
  owner_wallet: unknownRecord.optional(),
  node_identity: unknownRecord.optional(),
  summary: z.object({
    attached: numberValue,
    discovered: numberValue,
    remote_nodes: numberValue,
    model_classes: numberValue,
  }).passthrough(),
  policy: unknownRecord.optional(),
  attached: z.array(unknownRecord).catch([]),
  discovered: z.array(unknownRecord).catch([]),
  recommended_action: unknownRecord.optional(),
}).passthrough()

const cometBftDashboardSchema = z.object({
  profile: stringValue,
  configured: z.boolean().catch(false),
  enabled: z.boolean().catch(false),
  mode: stringValue,
  node_id: z.string().nullable().optional(),
  chain_id: z.string().nullable().optional(),
  rpc_endpoint: stringValue,
  rpc: unknownRecord.default({}),
  network: unknownRecord.default({}),
  management: unknownRecord.default({}),
  metrics: unknownRecord.default({}),
  protocol_authority: unknownRecord.default({}),
}).passthrough()

const cometBftInstallSchema = z.object({
  profile: stringValue,
  available: z.boolean().catch(false),
  reason: z.string().nullable().optional(),
  broker: unknownRecord.default({}),
  defaults: unknownRecord.default({}),
  current: unknownRecord.nullable().optional(),
  pending: unknownRecord.nullable().optional(),
  paths: unknownRecord.default({}),
  steps: z.array(unknownRecord).catch([]),
}).passthrough()

const runtimeOperationsSchema = z.object({
  generated_at: stringValue,
  freshness: z.object({
    source: stringValue,
    max_age_seconds: numberValue,
    runtime_health_reconciled: z.boolean().catch(false),
    installation_jobs_reconciled: z.boolean().catch(false),
    reconciliation_error: z.string().nullable().optional(),
  }).passthrough(),
  summary: z.object({
    runtime_total: numberValue,
    runtime_ready: numberValue,
    runtime_failed_or_not_ready: numberValue,
    runtime_active_tasks: numberValue,
    installation_job_total: numberValue,
    installation_job_active: numberValue,
    installation_job_failed: numberValue,
  }).passthrough(),
  runtimes: z.array(unknownRecord).catch([]),
  installation_jobs: z.array(unknownRecord).catch([]),
}).passthrough()

const resourceBrokerDashboardSchema = z.object({
  available: z.boolean().catch(false),
  generated_at: stringValue,
  reason: z.string().nullable().optional(),
  hardware: unknownRecord.default({}),
  summary: unknownRecord.default({}),
  scheduler: unknownRecord.default({}),
  leases: z.array(unknownRecord).catch([]),
  runtimes: z.array(unknownRecord).catch([]),
  runtime_summary: unknownRecord.default({}),
  metrics: unknownRecord.default({}),
}).passthrough()

const residentAgentStatusSchema = z.object({
  agent_id: stringValue,
  node_id: stringValue,
  implementation: stringValue,
  state: stringValue,
  health: stringValue,
  enabled: z.boolean().catch(false),
  execution: z.object({
    profile: stringValue,
    state: stringValue,
    inference_adapter: stringValue,
    fallback_profile: stringValue,
    vram_mb: numberValue,
    ram_budget_mb: numberValue,
    resource_lease: stringValue,
  }).passthrough().default({ profile: '', state: '', inference_adapter: '', fallback_profile: '', vram_mb: 0, ram_budget_mb: 0, resource_lease: '' }),
  model: z.object({
    repo: stringValue,
    quantization: stringValue,
    license: stringValue,
    model_card_url: z.string().optional(),
    license_url: z.string().optional(),
    path: z.string().nullable().optional(),
    path_exists: z.boolean().catch(false),
    llama_cpp_reference: stringValue,
  }).passthrough().default({ repo: '', quantization: '', license: '', path_exists: false, llama_cpp_reference: '' }),
  event_ingestion: z.object({
    subscribed: z.boolean().catch(false),
    subscription_id: z.string().nullable().optional(),
    last_event_id: z.string().nullable().optional(),
    last_event_sequence: numberValue,
    events_seen: numberValue,
    attention_events: numberValue,
    event_types: z.record(z.string(), numberValue).default({}),
  }).passthrough().default({ subscribed: false, last_event_sequence: 0, events_seen: 0, attention_events: 0, event_types: {} }),
  restart_recovery: z.object({
    last_restart_at: z.string().nullable().optional(),
    restart_count: numberValue,
    last_heartbeat_at: z.string().nullable().optional(),
  }).passthrough().default({ restart_count: 0 }),
  last_action: z.string().nullable().optional(),
  last_error: z.string().nullable().optional(),
  authority: z.record(z.string(), z.unknown()).default({}),
}).passthrough()

const stewardActionSchema = z.object({
  action: stringValue,
  label: stringValue,
  detail: stringValue,
  target_type: stringValue,
  class: stringValue,
  guard_only: z.boolean().catch(false),
  policy: stringValue,
}).passthrough()

const stewardActionPolicySchema = z.object({
  version: numberValue,
  auto_actions: z.array(z.string()).catch([]),
  approval_actions: z.array(z.string()).catch([]),
  max_actions_per_hour: numberValue,
  catalog: z.array(stewardActionSchema).catch([]),
}).passthrough()

const residentInferenceSchema = z.object({
  state: stringValue,
  profile: stringValue,
  model_path: z.string().nullable().optional(),
  provider_type: stringValue,
  plugin_id: z.string().nullable().optional(),
  lease_id: z.string().nullable().optional(),
  last_error: z.string().nullable().optional(),
  readiness: unknownRecord.default({}),
  resource_lease: unknownRecord.default({}),
  execution: unknownRecord.default({}),
  artifact: unknownRecord.default({}),
}).passthrough()

const escalationTaskSchema = z.object({
  task_id: stringValue,
  idempotency_key: stringValue,
  goal: stringValue,
  task_class: stringValue,
  data_class: stringValue,
  state: stringValue,
  created_at: stringValue,
  updated_at: stringValue,
  expires_at: z.string().nullable().optional(),
  selected_provider_id: z.string().nullable().optional(),
  route_decision: unknownRecord.default({}),
  context: unknownRecord.default({}),
  postconditions: z.array(unknownRecord).catch([]),
  plan: unknownRecord.nullable().optional(),
  plan_id: z.string().nullable().optional(),
  plan_hash: z.string().nullable().optional(),
  approval: unknownRecord.default({}),
  verification: unknownRecord.nullable().optional(),
  last_error: unknownRecord.nullable().optional(),
  correlation_id: z.string().nullable().optional(),
  causation_id: z.string().nullable().optional(),
}).passthrough()

const escalationTasksSchema = z.object({
  items: z.array(escalationTaskSchema).catch([]),
}).passthrough()

const installationWorkflowSchema = z.object({
  status: stringValue,
  checked_at: stringValue,
  plan_hash: z.string().nullable().optional(),
  stages: z.array(unknownRecord).catch([]),
  progress: unknownRecord.default({}),
  forecast: unknownRecord.nullable().optional(),
  completion: unknownRecord.nullable().optional(),
  next_action: z.object({
    id: stringValue,
    label: stringValue,
    reason: stringValue,
  }).passthrough(),
}).passthrough()

const installationPlanSchema = z.object({
  available: z.boolean().catch(false),
  status: stringValue,
  reason: z.string().nullable().optional(),
  plan_path: z.string().nullable().optional(),
  plan_hash: z.string().nullable().optional(),
  stored_plan_hash: z.string().nullable().optional(),
  integrity: stringValue,
  schema_version: numberValue,
  created_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
  applied_at: z.string().nullable().optional(),
  mode: stringValue,
  ai_assisted: z.boolean().catch(false),
  provider: stringValue,
  model: z.object({
    id: stringValue,
    source: z.string().nullable().optional(),
  }).passthrough().default({ id: '' }),
  endpoint: z.object({ requested_action: stringValue }).passthrough().default({ requested_action: 'skip' }),
  handoff: stringValue,
  next_action: stringValue,
  authority: unknownRecord.default({}),
  application: unknownRecord.nullable().optional(),
  workflow: installationWorkflowSchema.nullable().optional(),
}).passthrough()

const journalEventSchema = z.object({
  timestamp: stringValue,
  event_type: stringValue,
  message: stringValue,
  task_id: z.string().nullable().optional(),
  bundle_id: z.string().nullable().optional(),
  runtime_id: z.string().nullable().optional(),
  details: unknownRecord.default({}),
}).passthrough()

const journeyActionSchema = z.object({
  label: stringValue,
  route: z.string().nullable().optional(),
  screen: z.string().nullable().optional(),
}).passthrough()

const journeyNodeSchema = z.object({
  id: stringValue,
  type: stringValue,
  category: stringValue,
  title: stringValue,
  description: stringValue,
  state: z.enum(['ready', 'in_progress', 'not_started', 'blocked', 'warning', 'error']).catch('not_started'),
  required: z.boolean().catch(false),
  dependencies: z.array(stringValue).catch([]),
  action: journeyActionSchema.nullable().optional(),
  reason: stringValue,
  details: unknownRecord.default({}),
}).passthrough()

const journeyEdgeSchema = z.object({
  from: stringValue,
  to: stringValue,
  type: z.enum(['required', 'optional', 'dependency']).catch('required'),
}).passthrough()

const journeySchema = z.object({
  generated_at: stringValue,
  hypervisor: z.object({
    node_id: stringValue,
    state: stringValue,
    network_ready: z.boolean().catch(false),
    execution_ready: z.boolean().catch(false),
  }).partial().passthrough().default({}),
  progress: z.object({
    required_ready: numberValue,
    required_total: numberValue,
    percent: numberValue,
    optional_ready: numberValue,
    optional_total: numberValue,
  }).passthrough(),
  nodes: z.array(journeyNodeSchema).catch([]),
  edges: z.array(journeyEdgeSchema).catch([]),
  recommended_action: z.object({
    node_id: stringValue.nullable().optional(),
    title: stringValue,
    description: stringValue,
    label: stringValue,
    route: z.string().nullable().optional(),
    screen: z.string().nullable().optional(),
  }).passthrough(),
  role: stringValue,
}).passthrough()

export type DashboardHome = z.infer<typeof homeSchema>
export type Readiness = z.infer<typeof readinessSchema>
export type ReadinessStep = z.infer<typeof readinessStepSchema>
export type Fleet = z.infer<typeof fleetSchema>
export type BundlePayload = z.infer<typeof bundlePayloadSchema>
export type EndpointPayload = z.infer<typeof endpointPayloadSchema>
export type Bundle = z.infer<typeof bundleSchema>
export type Endpoint = z.infer<typeof endpointSchema>
export type WalletDashboard = z.infer<typeof walletDashboardSchema>
export type SessionDashboard = z.infer<typeof sessionDashboardSchema>
export type MarketDashboard = z.infer<typeof marketDashboardSchema>
export type RemoteEndpointsDashboard = z.infer<typeof remoteEndpointsDashboardSchema>
export type CometBftDashboard = z.infer<typeof cometBftDashboardSchema>
export type CometBftInstall = z.infer<typeof cometBftInstallSchema>
export type RuntimeOperations = z.infer<typeof runtimeOperationsSchema>
export type ResourceBrokerDashboard = z.infer<typeof resourceBrokerDashboardSchema>
export type ResidentAgentStatus = z.infer<typeof residentAgentStatusSchema>
export type StewardAction = z.infer<typeof stewardActionSchema>
export type StewardActionPolicy = z.infer<typeof stewardActionPolicySchema>
export type ResidentInference = z.infer<typeof residentInferenceSchema>
export type EscalationTask = z.infer<typeof escalationTaskSchema>
export type EscalationTasks = z.infer<typeof escalationTasksSchema>
export type InstallationPlan = z.infer<typeof installationPlanSchema>
export type AssistedInstallationAction =
  | 'prepare_review'
  | 'request_model_install'
  | 'process_model_install'
  | 'create_bundle'
  | 'create_private_endpoint'
  | 'forecast_private_endpoint'
  | 'start_private_endpoint'
export type JournalEvent = z.infer<typeof journalEventSchema>
export type JourneyGraph = z.infer<typeof journeySchema>
export type JourneyNode = z.infer<typeof journeyNodeSchema>

export const dashboardSchemas = {
  home: homeSchema,
  readiness: readinessSchema,
  fleet: fleetSchema,
  bundles: bundlePayloadSchema,
  endpoints: endpointPayloadSchema,
  wallet: walletDashboardSchema,
  sessions: sessionDashboardSchema,
  market: marketDashboardSchema,
  remoteEndpoints: remoteEndpointsDashboardSchema,
  cometbft: cometBftDashboardSchema,
  cometbftInstall: cometBftInstallSchema,
  runtimeOperations: runtimeOperationsSchema,
  resourceBroker: resourceBrokerDashboardSchema,
  residentAgent: residentAgentStatusSchema,
  stewardActionPolicy: stewardActionPolicySchema,
  residentInference: residentInferenceSchema,
  escalations: escalationTasksSchema,
  installationPlan: installationPlanSchema,
  events: z.array(journalEventSchema),
  journey: journeySchema,
}
