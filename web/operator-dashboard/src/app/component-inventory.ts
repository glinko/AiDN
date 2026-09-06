/**
 * M10.1 inventory of the current Classic surface.
 *
 * This is deliberately data-only: it describes ownership and seams without
 * importing renderers or generated dashboard assets.  A fragment is the
 * smallest current UI responsibility that can be assigned to the shared
 * Component Registry during progressive decomposition.
 */
export type ComponentInventoryDomain =
  | 'node-overview'
  | 'journey'
  | 'agents'
  | 'bundles'
  | 'providers-runtimes-models'
  | 'endpoints'
  | 'sessions'
  | 'resources-wallet-q'
  | 'network-consensus'
  | 'validation'
  | 'settings-updates'
  | 'hooks'
  | 'logs-events'

export type ComponentInventoryRecord = {
  fragment_id: string
  domain_group: ComponentInventoryDomain
  canonical_entity: string
  data_source: string
  query_key: string
  mutations: readonly string[]
  states: readonly string[]
  current_location: string
  reusable_boundary: string
  candidate_registry_id: string
  ownership: 'shared' | 'classic-only'
  accessibility_gaps: readonly string[]
  test_coverage: readonly string[]
  migration_priority: 'now' | 'next' | 'later'
}

const commonStates = ['loading', 'empty', 'ready', 'error', 'stale', 'offline'] as const

export const componentInventory: readonly ComponentInventoryRecord[] = [
  { fragment_id: 'node-overview', domain_group: 'node-overview', canonical_entity: 'node', data_source: 'dashboardApi.home/readiness', query_key: 'home', mutations: ['refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:OverviewWorkspace', reusable_boundary: 'NodeStatusSummary', candidate_registry_id: 'node-status-summary', ownership: 'shared', accessibility_gaps: ['status changes should announce revision'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
  { fragment_id: 'journey', domain_group: 'journey', canonical_entity: 'journey', data_source: 'dashboardApi.journey', query_key: 'journey', mutations: ['refresh'], states: commonStates, current_location: 'src/components/journey/JourneyPage.tsx', reusable_boundary: 'JourneySummary', candidate_registry_id: 'journey-summary', ownership: 'classic-only', accessibility_gaps: ['graph relationships need text alternative'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'later' },
  { fragment_id: 'agents', domain_group: 'agents', canonical_entity: 'agent', data_source: 'dashboardApi.home/agentConversation', query_key: 'home', mutations: ['send-message', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:OperationsWorkspace', reusable_boundary: 'AgentDetails', candidate_registry_id: 'agent-details', ownership: 'shared', accessibility_gaps: ['streaming state needs live-region policy'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
  { fragment_id: 'bundles', domain_group: 'bundles', canonical_entity: 'bundle', data_source: 'dashboardApi.bundles', query_key: 'bundles', mutations: ['create-bundle', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:BundlesWorkspace', reusable_boundary: 'BundleList', candidate_registry_id: 'bundle-list', ownership: 'classic-only', accessibility_gaps: ['dense controls need grouped labels'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'later' },
  { fragment_id: 'providers-runtimes-models', domain_group: 'providers-runtimes-models', canonical_entity: 'provider-runtime-model', data_source: 'dashboardApi.providers/runtimeOperations', query_key: 'providers', mutations: ['install', 'start', 'stop', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:ProviderWorkspaceScreen/ModelsWorkspace', reusable_boundary: 'ProviderRuntimeSummary', candidate_registry_id: 'provider-runtime-summary', ownership: 'classic-only', accessibility_gaps: ['operation progress should expose phase'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'later' },
  { fragment_id: 'endpoints', domain_group: 'endpoints', canonical_entity: 'endpoint', data_source: 'dashboardApi.endpoints', query_key: 'endpoints', mutations: ['create', 'publish', 'validate', 'disable', 'unpublish', 'retire', 'remove', 'toggle-local-agent-use'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:EndpointsScreen/EndpointTable/EndpointDraftControl', reusable_boundary: 'EndpointSummary + EndpointConfiguration', candidate_registry_id: 'endpoint-summary', ownership: 'shared', accessibility_gaps: ['table row actions need target context in announcement'], test_coverage: ['classic-dashboard.spec.ts', 'spatial-prototype.spec.ts'], migration_priority: 'now' },
  { fragment_id: 'sessions', domain_group: 'sessions', canonical_entity: 'workspace-session', data_source: 'dashboardApi.session', query_key: 'sessions', mutations: ['refresh', 'archive'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:OperationsWorkspace', reusable_boundary: 'SessionList', candidate_registry_id: 'session-list', ownership: 'shared', accessibility_gaps: ['session state should be filterable without color'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
  { fragment_id: 'resources', domain_group: 'resources-wallet-q', canonical_entity: 'resource-accounting', data_source: 'dashboardApi.resourceBroker/wallet', query_key: 'resource-broker', mutations: ['configure-cost', 'refresh'], states: commonStates, current_location: 'src/components/resources/ResourceBrokerWorkspace.tsx', reusable_boundary: 'ResourceBalance + ResourceUsage', candidate_registry_id: 'node-resource-summary', ownership: 'shared', accessibility_gaps: ['resource quantities need exact text alternative'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
  { fragment_id: 'wallet', domain_group: 'resources-wallet-q', canonical_entity: 'resource-contribution', data_source: 'dashboardApi.wallet', query_key: 'wallet', mutations: ['refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:WalletWorkspace', reusable_boundary: 'ContributionSummary', candidate_registry_id: 'resource-contribution-chart', ownership: 'shared', accessibility_gaps: ['chart requires a tabular alternative'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
  { fragment_id: 'network-consensus', domain_group: 'network-consensus', canonical_entity: 'network-consensus', data_source: 'dashboardApi.cometbft', query_key: 'cometbft', mutations: ['install', 'start', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:OperationsWorkspace', reusable_boundary: 'ConsensusStatus', candidate_registry_id: 'status-summary', ownership: 'classic-only', accessibility_gaps: ['peer health should not rely on color'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'later' },
  { fragment_id: 'validation', domain_group: 'validation', canonical_entity: 'validation-run', data_source: 'dashboardApi.endpointValidation', query_key: 'endpoints', mutations: ['validate', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:EndpointTable', reusable_boundary: 'ValidationSummary', candidate_registry_id: 'operation-notice', ownership: 'shared', accessibility_gaps: ['validation errors need field-level association'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
  { fragment_id: 'settings-updates', domain_group: 'settings-updates', canonical_entity: 'operator-settings', data_source: 'dashboardApi.settings/updates', query_key: 'settings', mutations: ['save', 'update', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:SettingsWorkspace', reusable_boundary: 'SettingsSummary', candidate_registry_id: 'settings-summary', ownership: 'classic-only', accessibility_gaps: ['unsaved state needs persistent announcement'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'later' },
  { fragment_id: 'hooks', domain_group: 'hooks', canonical_entity: 'hook-delivery', data_source: 'dashboardApi.hooks', query_key: 'hooks', mutations: ['retry', 'disable', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:OperationsWorkspace', reusable_boundary: 'HookDeliverySummary', candidate_registry_id: 'hook-delivery-summary', ownership: 'shared', accessibility_gaps: ['delivery failures need actionable text'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
  { fragment_id: 'logs-events', domain_group: 'logs-events', canonical_entity: 'journal-event', data_source: 'dashboardApi.journal/events', query_key: 'journal', mutations: ['refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:OperationsWorkspace', reusable_boundary: 'EventLog', candidate_registry_id: 'event-log', ownership: 'classic-only', accessibility_gaps: ['long event rows need a condensed accessible name'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'later' },
  { fragment_id: 'catalog-market', domain_group: 'providers-runtimes-models', canonical_entity: 'catalog-offer', data_source: 'dashboardApi.market/catalog', query_key: 'market', mutations: ['attach', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:MarketWorkspace', reusable_boundary: 'EndpointComparison', candidate_registry_id: 'endpoint-comparison', ownership: 'classic-only', accessibility_gaps: ['comparison columns need headers on narrow screens'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'later' },
  { fragment_id: 'operations', domain_group: 'logs-events', canonical_entity: 'operation', data_source: 'dashboardApi.runtimeOperations', query_key: 'runtime-operations', mutations: ['start', 'stop', 'refresh'], states: commonStates, current_location: 'src/app/classic-dashboard.tsx:OperationsWorkspace', reusable_boundary: 'ActionFeedback', candidate_registry_id: 'action-feedback', ownership: 'shared', accessibility_gaps: ['partial completion needs explicit next action'], test_coverage: ['classic-dashboard.spec.ts'], migration_priority: 'next' },
] as const

export const endpointConfigurationInventory = componentInventory.find((record) => record.fragment_id === 'endpoints')!

export function inventoryForScreen(screen: string): ComponentInventoryRecord[] {
  const normalized = screen.trim().toLowerCase()
  return componentInventory.filter((record) => record.fragment_id === normalized || record.domain_group === normalized)
}

export function validateComponentInventory(records: readonly ComponentInventoryRecord[] = componentInventory): string[] {
  const errors: string[] = []
  const ids = new Set<string>()
  for (const record of records) {
    if (ids.has(record.fragment_id)) errors.push(`duplicate fragment ownership: ${record.fragment_id}`)
    ids.add(record.fragment_id)
    if (!record.current_location || record.current_location.includes('static/react-dashboard')) errors.push(`invalid current location: ${record.fragment_id}`)
    if (!record.candidate_registry_id) errors.push(`missing registry candidate: ${record.fragment_id}`)
  }
  return errors
}
