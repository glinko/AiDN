import { useMemo, useRef } from 'react'
import { Line } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { AdditiveBlending, CubicBezierCurve3, Mesh, Vector3 } from 'three'
import type { Line2 } from 'three-stdlib'

import type { ConnectionEntity, CubeEntity, OrbEntity, Vector3Tuple } from './model'

const segmentCount = 48

type ThreadConnectionProps = {
  entity: ConnectionEntity
  sourcePosition: Vector3Tuple
  targetPosition: Vector3Tuple
}

function ThreadConnection({ entity, sourcePosition, targetPosition }: ThreadConnectionProps) {
  const coreLine = useRef<Line2>(null)
  const photon = useRef<Mesh>(null)
  const photonCore = useRef<Mesh>(null)
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
    if (photon.current && photonCore.current) {
      curve.getPoint(entity.getFlowProgress(0), point)
      const swell = 0.5 + 0.5 * Math.sin(entity.time * 2.2)
      photon.current.position.copy(point)
      photon.current.scale.setScalar(0.048 + swell * 0.016)
      photonCore.current.position.copy(point)
      photonCore.current.scale.setScalar(0.016 + swell * 0.006)
    }
  })

  return <group name={entity.id}>
    <Line ref={coreLine} points={initialPoints} color={entity.color} lineWidth={1} transparent opacity={0.74}
      blending={AdditiveBlending} depthWrite={false} toneMapped={false} renderOrder={1} />
    <mesh ref={photon} frustumCulled={false} renderOrder={2}>
      <sphereGeometry args={[1, 14, 10]} />
      <meshBasicMaterial color={entity.color} toneMapped={false} transparent opacity={0.92} blending={AdditiveBlending} />
    </mesh>
    <mesh ref={photonCore} frustumCulled={false} renderOrder={3}>
      <sphereGeometry args={[1, 10, 8]} />
      <meshBasicMaterial color="#ffffff" toneMapped={false} transparent opacity={0.98} blending={AdditiveBlending} />
    </mesh>
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
