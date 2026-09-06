export const SPATIAL_UI_FEATURE_FLAG = 'spatial_ui_enabled' as const
export const SPATIAL_WORKSPACE_PERSISTENCE_FEATURE_FLAG = 'spatial_workspace_persistence_enabled' as const
export const SPATIAL_INTERACTION_FEATURE_FLAG = 'spatial_interaction_enabled' as const
export const SPATIAL_TOPOLOGY_FEATURE_FLAG = 'spatial_topology_enabled' as const
export const SPATIAL_STATUS_FEATURE_FLAG = 'spatial_status_enabled' as const
/** Remote work remains opt-in; this is presentation rollout, never authority. */
export const SPATIAL_REMOTE_MEDIATION_FEATURE_FLAG = 'spatial_remote_mediation_enabled' as const
/** Long-lived history stays opt-in while the M8 memory projection is validated. */
export const SPATIAL_MEMORY_FEATURE_FLAG = 'spatial_memory_enabled' as const
/** M9 sync is an opt-in presentation/demo boundary; Node remains authoritative. */
export const SPATIAL_MULTI_DEVICE_SYNC_FEATURE_FLAG = 'spatial_multi_device_sync_enabled' as const
/** M10 shared components and Change Intent remain opt-in during migration. */
export const SPATIAL_CHANGE_INTENT_FEATURE_FLAG = 'spatial_change_intent_enabled' as const
/** M11 operator preview is a rollout control, never an authorization source. */
export const SPATIAL_OPERATOR_PREVIEW_FEATURE_FLAG = 'spatial_operator_preview_enabled' as const

export type FeatureFlagName = typeof SPATIAL_UI_FEATURE_FLAG | typeof SPATIAL_WORKSPACE_PERSISTENCE_FEATURE_FLAG | typeof SPATIAL_INTERACTION_FEATURE_FLAG | typeof SPATIAL_TOPOLOGY_FEATURE_FLAG | typeof SPATIAL_STATUS_FEATURE_FLAG | typeof SPATIAL_REMOTE_MEDIATION_FEATURE_FLAG | typeof SPATIAL_MEMORY_FEATURE_FLAG | typeof SPATIAL_MULTI_DEVICE_SYNC_FEATURE_FLAG | typeof SPATIAL_CHANGE_INTENT_FEATURE_FLAG | typeof SPATIAL_OPERATOR_PREVIEW_FEATURE_FLAG

declare global {
  interface Window {
    /** Optional server-rendered rollout hints; never an authorization source. */
    __AIDN_FEATURE_FLAGS__?: Partial<Record<FeatureFlagName, boolean>>
  }
}

function parseBoolean(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value !== 'string') return false
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase())
}

/**
 * Read a rollout flag without treating it as a capability or permission.
 * The Node/API authorization boundary remains authoritative for every request.
 */
export function isFeatureFlagEnabled(name: FeatureFlagName): boolean {
  if (typeof window !== 'undefined') {
    const serverValue = window.__AIDN_FEATURE_FLAGS__?.[name]
    if (typeof serverValue === 'boolean') return serverValue
  }

  if (name === SPATIAL_UI_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_UI_ENABLED)
  }
  if (name === SPATIAL_WORKSPACE_PERSISTENCE_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_WORKSPACE_PERSISTENCE_ENABLED)
  }
  if (name === SPATIAL_INTERACTION_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_INTERACTION_ENABLED)
  }
  if (name === SPATIAL_TOPOLOGY_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_TOPOLOGY_ENABLED)
  }
  if (name === SPATIAL_STATUS_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_STATUS_ENABLED)
  }
  if (name === SPATIAL_REMOTE_MEDIATION_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_REMOTE_MEDIATION_ENABLED)
  }
  if (name === SPATIAL_MEMORY_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_MEMORY_ENABLED)
  }
  if (name === SPATIAL_MULTI_DEVICE_SYNC_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_MULTI_DEVICE_SYNC_ENABLED)
  }
  if (name === SPATIAL_CHANGE_INTENT_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_CHANGE_INTENT_ENABLED)
  }
  if (name === SPATIAL_OPERATOR_PREVIEW_FEATURE_FLAG) {
    return parseBoolean(import.meta.env.VITE_SPATIAL_OPERATOR_PREVIEW_ENABLED)
  }
  return false
}

export function isSpatialUiEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_UI_FEATURE_FLAG)
}

export function isSpatialWorkspacePersistenceEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_WORKSPACE_PERSISTENCE_FEATURE_FLAG)
}

export function isSpatialInteractionEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_INTERACTION_FEATURE_FLAG)
}

export function isSpatialTopologyEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_TOPOLOGY_FEATURE_FLAG)
}

/** Status is a Node-owned safety surface; Spatial UI enablement implies it. */
export function isSpatialStatusEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_STATUS_FEATURE_FLAG) || isSpatialUiEnabled()
}

/** Remote mediation is deliberately stricter than the general Spatial flag. */
export function isSpatialRemoteMediationEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_REMOTE_MEDIATION_FEATURE_FLAG)
}

/** M8 remains a presentation-only projection; Node authorization is unchanged. */
export function isSpatialMemoryEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_MEMORY_FEATURE_FLAG)
}

/** M9 multi-device sync is presentation-only until the Node transport is enabled. */
export function isSpatialMultiDeviceSyncEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_MULTI_DEVICE_SYNC_FEATURE_FLAG)
}

export function isSpatialChangeIntentEnabled(): boolean {
  return isFeatureFlagEnabled(SPATIAL_CHANGE_INTENT_FEATURE_FLAG)
}

export function isSpatialOperatorPreviewEnabled(): boolean {
  if (typeof window !== 'undefined' && window.__AIDN_FEATURE_FLAGS__ && SPATIAL_OPERATOR_PREVIEW_FEATURE_FLAG in window.__AIDN_FEATURE_FLAGS__) {
    return Boolean(window.__AIDN_FEATURE_FLAGS__[SPATIAL_OPERATOR_PREVIEW_FEATURE_FLAG])
  }
  const buildValue = import.meta.env.VITE_SPATIAL_OPERATOR_PREVIEW_ENABLED
  // Keep the existing opt-in Spatial UI compatible when the new M11 rollout
  // hint is not supplied; an explicit false still disables the preview.
  return typeof buildValue === 'string' ? parseBoolean(buildValue) : isSpatialUiEnabled()
}
