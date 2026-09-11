import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { AdditiveBlending, BufferAttribute, BufferGeometry, Group, Line, LineBasicMaterial } from 'three'
import type { Vector3Tuple } from './model'
import type { WorkspaceArtifactEntity } from './workspace-artifacts'

/** One continuous, non-strobing discharge: agent → creation point → settled cube. */
export function ArtifactBirth({ entity, source }: { entity: WorkspaceArtifactEntity; source: Vector3Tuple }) {
  const group = useRef<Group>(null)
  const head = useRef<Group>(null)
  const discharge = useMemo(() => {
    const geometry = new BufferGeometry()
    geometry.setAttribute('position', new BufferAttribute(new Float32Array(25 * 3), 3))
    const haloMaterial = new LineBasicMaterial({
      color: '#c5e6ff',
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: AdditiveBlending,
    })
    const halo = new Line(geometry, haloMaterial)
    halo.frustumCulled = false
    halo.raycast = () => undefined
    const material = new LineBasicMaterial({ color: '#8eafea', transparent: true, opacity: 0, depthWrite: false })
    const line = new Line(geometry, material)
    line.frustumCulled = false
    line.raycast = () => undefined
    return { halo, line }
  }, [])
  useEffect(() => () => {
    discharge.line.geometry.dispose()
    discharge.line.material.dispose()
    discharge.halo.material.dispose()
  }, [discharge])
  useFrame(() => {
    const elapsed = entity.birthElapsed
    if (group.current) group.current.visible = elapsed < 1.8
    if (elapsed >= 1.8) return
    const reach = Math.min(1, elapsed / 0.38)
    const positions = discharge.line.geometry.getAttribute('position') as BufferAttribute
    const target = entity.position
    for (let index = 0; index < 25; index++) {
      const t = index / 24 * reach
      const envelope = Math.sin(t * Math.PI)
      const x = source[0] + (target[0] - source[0]) * t + Math.sin(t * 17 + elapsed * 3) * 0.06 * envelope
      const y = source[1] - 0.65 + (target[1] - source[1] + 0.65) * t
      const z = source[2] + (target[2] - source[2]) * t + envelope * 0.12
      positions.setXYZ(index, x, y, z)
      if (index === 24) head.current?.position.set(x, y, z)
    }
    positions.needsUpdate = true
    const opacity = Math.min(0.8, elapsed * 5) * Math.max(0, 1 - (elapsed - 0.5) / 1.3)
    discharge.line.material.opacity = opacity
    discharge.halo.material.opacity = opacity * 0.28
    head.current?.scale.setScalar(Math.max(0, 1 - elapsed / 1.8))
  })
  return <group ref={group} visible={entity.birthElapsed < 1.8} name={'birth:' + entity.id}>
    <primitive object={discharge.halo} />
    <primitive object={discharge.line} />
    <group ref={head}><mesh raycast={() => null}>
      <sphereGeometry args={[0.04, 12, 8]} /><meshBasicMaterial color="#d2e3ff" toneMapped={false} />
    </mesh></group>
  </group>
}
