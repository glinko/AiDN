import {
  parseSpatialViewport,
  parseSpatialWorkspace,
  spatialTimestampSchema,
  type SpatialViewportSnapshot,
  type SpatialWorkspaceSnapshot,
} from '@/spatial/contracts'

import { HOME_CAMERA, type SpatialCameraState } from '../prototype/camera'
import type { SpatialNodeScope } from '../data/scope'

export type SpatialWorkspaceModel = {
  semantic: SpatialWorkspaceSnapshot
  presentation: SpatialViewportSnapshot
}

export type SpatialWorkspaceConflictCode = 'NODE_MISMATCH' | 'STALE_REVISION' | 'CORRUPT_PRESENTATION' | 'UNAUTHORIZED' | 'AGENT_REPLACED' | 'PARTIAL_PERSISTENCE' | 'VALIDATION'

export class SpatialWorkspaceConflict extends Error {
  readonly code: SpatialWorkspaceConflictCode

  constructor(code: SpatialWorkspaceConflictCode, message: string) {
    super(message)
    this.name = 'SpatialWorkspaceConflict'
    this.code = code
  }
}

export function assertWorkspaceOwnership(snapshot: SpatialWorkspaceSnapshot, scope: SpatialNodeScope): void {
  if (snapshot.node_id !== scope.node_id) throw new SpatialWorkspaceConflict('NODE_MISMATCH', 'Workspace belongs to a different Node.')
}

export function assertPresentationOwnership(presentation: SpatialViewportSnapshot, scope: SpatialNodeScope): void {
  if (presentation.node_id !== scope.node_id) throw new SpatialWorkspaceConflict('NODE_MISMATCH', 'Presentation belongs to a different Node.')
}

export function cloneSpatialWorkspaceSnapshot(snapshot: SpatialWorkspaceSnapshot): SpatialWorkspaceSnapshot {
  return structuredClone(snapshot)
}

export function cloneSpatialViewportSnapshot(presentation: SpatialViewportSnapshot): SpatialViewportSnapshot {
  return structuredClone(presentation)
}

function cameraForPresentation(camera: SpatialCameraState): SpatialViewportSnapshot['camera'] {
  return {
    x: camera.x,
    y: camera.y,
    zoom: camera.zoom,
    focus_id: camera.focusId,
  }
}

export function createSpatialPresentationSnapshot(
  snapshot: SpatialWorkspaceSnapshot,
  deviceId: string,
  qualityProfile: SpatialViewportSnapshot['quality_profile'] = 'DESKTOP',
  now: Date = new Date(),
): SpatialViewportSnapshot {
  const updatedAt = spatialTimestampSchema.parse(now)
  return {
    schema_version: 'spatial.viewport.v1',
    workspace_id: snapshot.workspace_id,
    node_id: snapshot.node_id,
    device_id: deviceId,
    presentation_revision: 0,
    camera: cameraForPresentation(HOME_CAMERA),
    selection_ref: null,
    opened_frame_refs: [],
    temporary_focus_ref: null,
    transient_discovery_refs: [],
    quality_profile: qualityProfile,
    updated_at: updatedAt,
  }
}

export function createSpatialWorkspaceModel(
  snapshotInput: unknown,
  presentationInput: unknown,
  scope: SpatialNodeScope,
): SpatialWorkspaceModel {
  const snapshot = parseSpatialWorkspace(snapshotInput)
  if (!snapshot.ok) throw new SpatialWorkspaceConflict('NODE_MISMATCH', 'Workspace snapshot is not compatible with the typed contract.')
  const presentation = parseSpatialViewport(presentationInput)
  if (!presentation.ok) throw new SpatialWorkspaceConflict('CORRUPT_PRESENTATION', 'Presentation snapshot is not compatible with the typed contract.')
  assertWorkspaceOwnership(snapshot.data, scope)
  assertPresentationOwnership(presentation.data, scope)
  if (presentation.data.workspace_id !== snapshot.data.workspace_id) throw new SpatialWorkspaceConflict('NODE_MISMATCH', 'Workspace and presentation IDs do not match.')
  return { semantic: snapshot.data, presentation: presentation.data }
}

export function resetSpatialPresentation(
  current: SpatialViewportSnapshot,
  now: Date = new Date(),
): SpatialViewportSnapshot {
  return {
    ...cloneSpatialViewportSnapshot(current),
    presentation_revision: current.presentation_revision + 1,
    camera: cameraForPresentation(HOME_CAMERA),
    selection_ref: null,
    opened_frame_refs: [],
    temporary_focus_ref: null,
    transient_discovery_refs: [],
    updated_at: spatialTimestampSchema.parse(now),
  }
}

export function applySpatialSemanticSnapshot(
  current: SpatialWorkspaceSnapshot,
  nextInput: unknown,
  scope: SpatialNodeScope,
): SpatialWorkspaceSnapshot {
  const next = parseSpatialWorkspace(nextInput)
  if (!next.ok) throw new SpatialWorkspaceConflict('STALE_REVISION', 'Workspace update is not compatible with the typed contract.')
  assertWorkspaceOwnership(next.data, scope)
  if (next.data.workspace_id !== current.workspace_id) throw new SpatialWorkspaceConflict('NODE_MISMATCH', 'Workspace update targets a different Workspace.')
  if (next.data.semantic_revision < current.semantic_revision) throw new SpatialWorkspaceConflict('STALE_REVISION', 'Workspace revision is older than the current snapshot.')
  return cloneSpatialWorkspaceSnapshot(next.data)
}

export function workspaceSurvivesAgentChange(snapshot: SpatialWorkspaceSnapshot, agentBindingRef: string | null): { snapshot: SpatialWorkspaceSnapshot; agentBindingRef: string | null } {
  return { snapshot: cloneSpatialWorkspaceSnapshot(snapshot), agentBindingRef }
}
