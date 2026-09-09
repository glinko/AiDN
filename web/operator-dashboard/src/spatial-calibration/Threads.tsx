import { useMemo, useRef } from 'react'
import { Line } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { AdditiveBlending, CubicBezierCurve3, InstancedMesh, Object3D, Vector3 } from 'three'
import type { Line2 } from 'three-stdlib'

import type { ConnectionEntity, CubeEntity, OrbEntity, Vector3Tuple } from './model'

const segmentCount = 48
const beadCount = 4

type ThreadConnectionProps = {
  entity: ConnectionEntity
  sourcePosition: Vector3Tuple
  targetPosition: Vector3Tuple
}

function ThreadConnection({ entity, sourcePosition, targetPosition }: ThreadConnectionProps) {
  const coreLine = useRef<Line2>(null)
  const glowLine = useRef<Line2>(null)
  const beads = useRef<InstancedMesh>(null)
  const beadCores = useRef<InstancedMesh>(null)
  const dummy = useMemo(() => new Object3D(), [])
  const point = useMemo(() => new Vector3(), [])
  const sampled = useMemo(() => Array.from({ length: segmentCount + 1 }, () => new Vector3()), [])
  const positions = useMemo(() => Array<number>((segmentCount + 1) * 3).fill(0), [])
  const curve = useMemo(() => {
    const [start, bendA, bendB, end] = entity.getControlPoints(sourcePosition, targetPosition)
    return new CubicBezierCurve3(
      new Vector3().fromArray(start),
      new Vector3().fromArray(bendA),
      new Vector3().fromArray(bendB),
      new Vector3().fromArray(end),
    )
  }, [entity, sourcePosition, targetPosition])
  const initialPoints = useMemo(() => curve.getPoints(segmentCount), [curve])

  useFrame(() => {
    const [start, bendA, bendB, end] = entity.getControlPoints(sourcePosition, targetPosition)
    curve.v0.fromArray(start)
    curve.v1.fromArray(bendA)
    curve.v2.fromArray(bendB)
    curve.v3.fromArray(end)

    for (let index = 0; index <= segmentCount; index += 1) {
      curve.getPoint(index / segmentCount, sampled[index])
      const offset = index * 3
      positions[offset] = sampled[index].x
      positions[offset + 1] = sampled[index].y
      positions[offset + 2] = sampled[index].z
    }

    if (coreLine.current) {
      coreLine.current.geometry.setPositions(positions)
      coreLine.current.computeLineDistances()
    }
    if (glowLine.current) {
      glowLine.current.geometry.setPositions(positions)
      glowLine.current.computeLineDistances()
    }

    if (beads.current && beadCores.current) {
      for (let index = 0; index < beadCount; index += 1) {
        const progress = entity.getFlowProgress(index)
        curve.getPoint(progress, point)
        dummy.position.copy(point)
        const swell = 0.5 + 0.5 * Math.sin(entity.time * 2.2 + index * 1.7)
        dummy.scale.setScalar(0.052 + swell * 0.018)
        dummy.updateMatrix()
        beads.current.setMatrixAt(index, dummy.matrix)
        dummy.scale.setScalar(0.019 + swell * 0.008)
        dummy.updateMatrix()
        beadCores.current.setMatrixAt(index, dummy.matrix)
      }
      beads.current.instanceMatrix.needsUpdate = true
      beadCores.current.instanceMatrix.needsUpdate = true
    }
  })

  return <group name={entity.id}>
    <Line ref={glowLine} points={initialPoints} color={entity.color} lineWidth={7} transparent opacity={0.11}
      blending={AdditiveBlending} depthWrite={false} toneMapped={false} renderOrder={1} />
    <Line ref={coreLine} points={initialPoints} color={entity.color} lineWidth={1.55} transparent opacity={0.72}
      blending={AdditiveBlending} depthWrite={false} toneMapped={false} renderOrder={2} />
    <instancedMesh ref={beads} args={[undefined, undefined, beadCount]} frustumCulled={false} renderOrder={3}>
      <sphereGeometry args={[1, 10, 8]} />
      <meshBasicMaterial color={entity.color} toneMapped={false} transparent opacity={0.98} blending={AdditiveBlending} />
    </instancedMesh>
    <instancedMesh ref={beadCores} args={[undefined, undefined, beadCount]} frustumCulled={false} renderOrder={4}>
      <sphereGeometry args={[1, 8, 6]} />
      <meshBasicMaterial color="#ffffff" toneMapped={false} transparent opacity={0.98} blending={AdditiveBlending} />
    </instancedMesh>
  </group>
}

export type SpatialThreadsProps = {
  connections: ReadonlyArray<ConnectionEntity>
  orb: OrbEntity
  cube: CubeEntity
  endpoint: { id: string; position: Vector3Tuple }
}

export function SpatialThreads({ connections, orb, cube, endpoint }: SpatialThreadsProps) {
  const targetPositions = useMemo(() => new Map<string, Vector3Tuple>([
    [cube.id, cube.position],
    [endpoint.id, endpoint.position],
  ]), [cube, endpoint])

  return <group name="spatial-connections">
    {connections.map((connection) => {
      const targetPosition = targetPositions.get(connection.targetId)
      if (!targetPosition || connection.sourceId !== orb.id) return null
      return <ThreadConnection key={connection.id} entity={connection} sourcePosition={orb.position} targetPosition={targetPosition} />
    })}
  </group>
}
