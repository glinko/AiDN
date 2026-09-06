import { useEffect } from 'react'

import { OrbitControls } from '@react-three/drei'
import { useThree } from '@react-three/fiber'

import { clampSpatialCamera, type SpatialCameraState } from './camera'

export type SpatialCameraRigProps = {
  cameraState: SpatialCameraState
  onCameraChange?: (state: SpatialCameraState) => void
  prefersReducedMotion?: boolean
}

/** Applies local viewport camera state without mutating world/entity coordinates. */
export function SpatialCameraRig({ cameraState }: SpatialCameraRigProps) {
  const { camera } = useThree()

  useEffect(() => {
    camera.position.set(cameraState.x, cameraState.y + 0.1, 4.5 / cameraState.zoom)
    camera.lookAt(cameraState.x, cameraState.y, 0)
    camera.updateProjectionMatrix()
  }, [camera, cameraState.x, cameraState.y, cameraState.zoom, cameraState.transitionToken])

  return null
}

/** Named WorkspaceCamera seam for the roadmap; state remains local to the viewport. */
export function WorkspaceCamera(props: SpatialCameraRigProps) {
  return <SpatialCameraRig {...props} />
}

export function SpatialOrbitControls({ cameraState, onCameraChange }: SpatialCameraRigProps) {
  const handleChange = (event?: unknown) => {
    const controls = event as { target?: { object?: { position?: { x: number; y: number; z: number } } } } | undefined
    const object = controls?.target?.object?.position
    if (!object) return
    const next = clampSpatialCamera({
      ...cameraState,
      x: object.x,
      y: object.y - 0.1,
      zoom: Math.min(1.55, Math.max(0.72, 4.5 / Math.max(object.z, 0.1))),
      focusId: null,
      transitionToken: cameraState.transitionToken + 1,
    })
    onCameraChange?.(next)
  }

  return (
    <OrbitControls
      makeDefault
      enableDamping
      dampingFactor={0.08}
      enablePan
      minDistance={2.9}
      maxDistance={6.25}
      minPolarAngle={Math.PI / 3.1}
      maxPolarAngle={Math.PI / 2.15}
      onChange={handleChange}
    />
  )
}
