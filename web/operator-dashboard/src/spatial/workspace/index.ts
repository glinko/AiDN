export { SpatialCanvas, type SpatialCanvasProps } from './SpatialCanvas'
export { SpatialDomOverlay, SpatialInteractive, type SpatialDomOverlayProps, type SpatialInteractiveProps } from './SpatialDomOverlay'
export { SpatialRendererErrorBoundary, type SpatialRendererErrorBoundaryProps } from './SpatialRendererErrorBoundary'
export { SpatialWorkspace, type SpatialWorkspaceProps, type SpatialWorkspaceState } from './SpatialWorkspace'
export { PrimaryAgentManagementSurface, type PrimaryAgentManagementSurfaceProps } from './PrimaryAgentManagementSurface'
export { ConversationSurface } from './ConversationSurface'
export { SpatialTopologySurface } from './SpatialTopologySurface'
export { readSpatialViewport, useSpatialViewport, type SpatialViewport, type SpatialViewportOrientation } from './viewport'
export {
  SpatialWorkspaceConflict,
  applySpatialSemanticSnapshot,
  assertPresentationOwnership,
  assertWorkspaceOwnership,
  cloneSpatialViewportSnapshot,
  cloneSpatialWorkspaceSnapshot,
  createSpatialPresentationSnapshot,
  createSpatialWorkspaceModel,
  resetSpatialPresentation,
  workspaceSurvivesAgentChange,
  type SpatialWorkspaceConflictCode,
  type SpatialWorkspaceModel,
} from './model'
export {
  InMemorySpatialWorkspaceRepository,
  createHttpSpatialWorkspaceRepository,
  type InMemoryWorkspaceRepositoryOptions,
  type HttpSpatialWorkspaceRepositoryOptions,
  type SpatialPresentationResult,
  type SpatialSemanticMutationResult,
  type SpatialSemanticOperation,
  type SpatialWorkspaceChange,
  type SpatialWorkspaceRepository,
} from './repository'
