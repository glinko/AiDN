import { useMemo, useRef } from 'react'
import { Line } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { AdditiveBlending, Color, CubicBezierCurve3, InstancedMesh, Object3D, Vector3 } from 'three'
import type { Line2 } from 'three-stdlib'

import type { ConnectionEntity, CubeEntity, OrbEntity, Vector3Tuple } from './model'

const segmentCount = 48
const trailSamples = 40
const trailLength = 0.16

type ThreadConnectionProps = {
  entity: ConnectionEntity
  sourcePosition: Vector3Tuple
  targetPosition: Vector3Tuple
}

function ThreadConnection({ entity, sourcePosition, targetPosition }: ThreadConnectionProps) {
  const coreLine = useRef<Line2>(null)
  const photonTrail = useRef<InstancedMesh>(null)
  const point = useMemo(() => new Vector3(), [])
  const dummy = useMemo(() => new Object3D(), [])
  const photonColor = useMemo(() => new Color(entity.color), [entity])
  const tint = useMemo(() => new Color(), [])
  const white = useMemo(() => new Color('#ffffff'), [])
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
    if (photonTrail.current) {
      const headProgress = entity.getFlowProgress(0)
      for (let sample = 0; sample < trailSamples; sample += 1) {
        const tail = sample / (trailSamples - 1)
        const progress = Math.max(0, headProgress - tail * trailLength)
        curve.getPoint(progress, point)
        dummy.position.copy(point)
        dummy.scale.setScalar(sample === 0 ? 0.046 : 0.027 * Math.pow(1 - tail, 1.1) + 0.001)
        dummy.updateMatrix()
        photonTrail.current.setMatrixAt(sample, dummy.matrix)
        tint.copy(photonColor).lerp(white, sample === 0 ? 0.75 : tail * 0.75)
        photonTrail.current.setColorAt(sample, tint)
      }
      photonTrail.current.instanceMatrix.needsUpdate = true
      if (photonTrail.current.instanceColor) photonTrail.current.instanceColor.needsUpdate = true
    }
  })

  return <group name={entity.id}>
    <Line ref={coreLine} points={initialPoints} color={entity.color} lineWidth={1} transparent opacity={0.74}
      blending={AdditiveBlending} depthWrite={false} toneMapped={false} renderOrder={1} />
    <instancedMesh ref={photonTrail} args={[undefined, undefined, trailSamples]} frustumCulled={false} renderOrder={2}>
      <sphereGeometry args={[1, 10, 8]} />
      <meshBasicMaterial toneMapped={false} />
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
