import { Button } from '@/spatial/primitives'

import { cameraTransitionDuration, type SpatialCameraState } from './camera'

export type SpatialNavigationControllerProps = {
  camera: SpatialCameraState
  hasSelection: boolean
  prefersReducedMotion?: boolean
  onHome: () => void
  onFocusSelected: () => void
  onBack: () => void
  onZoom: (delta: number) => void
}

/** DOM equivalent for every camera gesture. World/entity coordinates stay in the canvas. */
export function SpatialNavigationController({
  camera,
  hasSelection,
  prefersReducedMotion = false,
  onHome,
  onFocusSelected,
  onBack,
  onZoom,
}: SpatialNavigationControllerProps) {
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Home') {
      event.preventDefault()
      onHome()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onBack()
    } else if (event.key === '+' || event.key === '=') {
      event.preventDefault()
      onZoom(0.08)
    } else if (event.key === '-' || event.key === '_') {
      event.preventDefault()
      onZoom(-0.08)
    }
  }

  return (
    <div
      className="aidn-spatial-navigation"
      data-aidn-navigation-controller="local"
      data-aidn-camera-focus={camera.focusId ?? 'home'}
      data-aidn-camera-transition-duration={cameraTransitionDuration(prefersReducedMotion)}
      tabIndex={0}
      aria-label="Spatial camera navigation"
      onKeyDown={handleKeyDown}
    >
      <div className="aidn-spatial-control-heading">
        <span className="aidn-spatial-control-label">Camera</span>
        <span className="aidn-spatial-control-value">{camera.zoom.toFixed(2)}×</span>
      </div>
      <div className="aidn-spatial-control-actions">
        <Button size="sm" variant="outline" accent="blue" onClick={onHome}>HOME</Button>
        <Button size="sm" variant="outline" accent="violet" disabled={!hasSelection} onClick={onFocusSelected}>Focus selected</Button>
        <Button size="sm" variant="ghost" accent="neutral" aria-label="Back from focus" disabled={!camera.focusId} onClick={onBack}>Back</Button>
        <Button size="sm" variant="ghost" accent="neutral" aria-label="Zoom out" onClick={() => onZoom(-0.08)}>−</Button>
        <Button size="sm" variant="ghost" accent="neutral" aria-label="Zoom in" onClick={() => onZoom(0.08)}>+</Button>
      </div>
      <p className="aidn-spatial-control-hint">Keyboard: Home returns, Escape backs out, +/− zoom. Drag the scene for local orbit/pan.</p>
    </div>
  )
}
