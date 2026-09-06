import { useLayoutEffect, useRef } from 'react'

import { Line } from '@react-three/drei'

import { spatialEnvironmentProfile, type SpatialQualityProfile } from './environment'
import {
  spatialEntities,
  spatialEntityLod,
  spatialRelations,
  type SpatialEntity,
} from './entities'
import type { SpatialCameraState } from './camera'

export type SpatialEntitySceneProps = {
  selectedEntityId: string | null
  onEntitySelect: (entityId: string) => void
  camera: SpatialCameraState
  profile: SpatialQualityProfile
  entities?: readonly SpatialEntity[]
  relations?: readonly { id: string; sourceId: string; targetId: string; label: string }[]
}

type MatrixLike = {
  elements: number[]
  toArray: (array?: number[], offset?: number) => number[]
}

type InstancedMeshHandle = {
  setMatrixAt: (index: number, matrix: MatrixLike) => void
  instanceMatrix: { needsUpdate: boolean }
}

function translationMatrix(x: number, y: number, z: number): MatrixLike {
  const elements = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]
  return {
    elements,
    toArray: (array = [], offset = 0) => {
      elements.forEach((value, index) => { array[offset + index] = value })
      return array
    },
  }
}

function entityDistance(entity: SpatialEntity, camera: SpatialCameraState): number {
  const dx = entity.position.x - camera.x
  const dy = entity.position.y - camera.y
  return Math.sqrt(dx * dx + dy * dy + Math.abs(entity.position.z)) / Math.max(camera.zoom, 0.1)
}

function EntityMesh({ entity, selected, lod, onSelect }: { entity: SpatialEntity; selected: boolean; lod: string; onSelect: () => void }) {
  const color = entity.kind === 'subagent'
    ? '#7777b7'
    : entity.kind === 'endpoint'
      ? '#4b829f'
      : entity.kind === 'service'
        ? '#5d8f86'
        : entity.kind === 'session'
          ? '#7f6ca5'
      : entity.kind === 'artifact'
        ? '#9a694e'
        : '#81571f'
  const geometry = entity.kind === 'subagent'
    ? <sphereGeometry args={[selected ? 0.27 : 0.21, lod === 'LOD0' ? 8 : 18, lod === 'LOD0' ? 8 : 18]} />
    : entity.kind === 'endpoint'
      ? <octahedronGeometry args={[selected ? 0.23 : 0.17, lod === 'LOD0' ? 0 : 1]} />
      : entity.kind === 'service'
        ? <cylinderGeometry args={[selected ? 0.21 : 0.16, selected ? 0.21 : 0.16, selected ? 0.34 : 0.26, lod === 'LOD0' ? 6 : 12]} />
        : entity.kind === 'session'
          ? <dodecahedronGeometry args={[selected ? 0.25 : 0.19, lod === 'LOD0' ? 0 : 1]} />
      : entity.kind === 'artifact'
        ? <boxGeometry args={[selected ? 0.36 : 0.28, selected ? 0.25 : 0.2, 0.08]} />
        : <torusGeometry args={[selected ? 0.27 : 0.2, 0.045, 8, lod === 'LOD0' ? 12 : 24]} />

  return (
    <mesh
      position={[entity.position.x, entity.position.y, entity.position.z]}
      rotation={entity.kind === 'attention' ? [Math.PI / 2, 0, 0] : [0, entity.kind === 'artifact' ? 0.24 : 0, 0]}
      scale={selected ? 1.18 : 1}
      userData={{ spatialEntityId: entity.id, spatialEntityKind: entity.kind, spatialEntityLod: lod }}
      onClick={(event) => {
        event.stopPropagation()
        onSelect()
      }}
    >
      {entity.kind === 'endpoint' ? (
        <group userData={{ spatialEntityKind: 'endpoint-energy-object', spatialEntityClass: 'capability', availability: 'unknown-safe-default' }}>
          <mesh>
            <sphereGeometry args={[selected ? 0.23 : 0.17, lod === 'LOD0' ? 8 : 18, lod === 'LOD0' ? 8 : 18]} />
            <meshPhysicalMaterial color={selected ? '#ffffff' : color} emissive={color} emissiveIntensity={selected ? 0.5 : 0.16} transparent opacity={lod === 'LOD0' ? 0.46 : selected ? 0.98 : 0.86} roughness={0.22} metalness={0.18} transmission={0.18} />
          </mesh>
          {lod !== 'LOD0' ? <mesh rotation={[Math.PI / 2, 0.25, 0]}>
            <torusGeometry args={[selected ? 0.29 : 0.22, 0.018, 8, 24]} />
            <meshBasicMaterial color={color} transparent opacity={selected ? 0.78 : 0.36} />
          </mesh> : null}
        </group>
      ) : geometry}
      <meshStandardMaterial
        color={selected ? '#ffffff' : color}
        emissive={color}
        emissiveIntensity={selected ? 0.38 : entity.kind === 'attention' ? 0.22 : 0.08}
        transparent
        opacity={lod === 'LOD0' ? 0.46 : selected ? 0.98 : 0.84}
        roughness={entity.kind === 'artifact' ? 0.5 : 0.28}
        metalness={entity.kind === 'endpoint' || entity.kind === 'service' ? 0.12 : 0}
      />
    </mesh>
  )
}

function EndpointParticles({ profile, entities }: { profile: SpatialQualityProfile; entities: readonly SpatialEntity[] }) {
  const ref = useRef<InstancedMeshHandle | null>(null)
  const endpointEntitiesForScene = entities.filter((entity) => entity.kind === 'endpoint')
  const count = Math.min(spatialEnvironmentProfile(profile).particleBudget, endpointEntitiesForScene.length)

  useLayoutEffect(() => {
    if (!ref.current) return
    endpointEntitiesForScene.slice(0, count).forEach((entity, index) => {
      ref.current?.setMatrixAt(index, translationMatrix(entity.position.x, entity.position.y, entity.position.z + 0.08))
    })
    ref.current.instanceMatrix.needsUpdate = true
  }, [count, endpointEntitiesForScene])

  if (count === 0) return null
  return (
    <instancedMesh
      ref={(node) => { ref.current = node as unknown as InstancedMeshHandle | null }}
      args={[undefined, undefined, count]}
      userData={{ spatialEntityKind: 'endpoint-particle-field', spatialEntityLod: 'LOD2', renderer: 'instancedMesh' }}
    >
      <sphereGeometry args={[0.045, 6, 6]} />
      <meshBasicMaterial color="#4b829f" transparent opacity={0.72} />
    </instancedMesh>
  )
}

function RelationThreads({ entities, relations }: { entities: readonly SpatialEntity[]; relations: readonly { id: string; sourceId: string; targetId: string; label: string }[] }) {
  const entityById = new Map(entities.map((entity) => [entity.id, entity]))
  return (
    <group userData={{ spatialEntityKind: 'semantic-thread-layer' }}>
      {relations.map((relation) => {
        const source = entityById.get(relation.sourceId)
        const target = entityById.get(relation.targetId)
        if (!source || !target) return null
        return (
          <Line
            key={relation.id}
            points={[
              [source.position.x, source.position.y, source.position.z],
              [target.position.x, target.position.y, target.position.z],
            ]}
            color="#9db6d5"
            lineWidth={0.8}
            transparent
            opacity={0.42}
          />
        )
      })}
    </group>
  )
}

/** M1.6 mock entity grammar; LOD changes geometry only and preserves identity. */
export function SpatialEntityScene({ selectedEntityId, onEntitySelect, camera, profile, entities = spatialEntities, relations = spatialRelations }: SpatialEntitySceneProps) {
  return (
    <>
      <RelationThreads entities={entities} relations={relations} />
      {entities.map((entity) => (
        <EntityMesh
          key={entity.id}
          entity={entity}
          selected={selectedEntityId === entity.id}
          lod={spatialEntityLod(entityDistance(entity, camera), profile)}
          onSelect={() => onEntitySelect(entity.id)}
        />
      ))}
      <EndpointParticles profile={profile} entities={entities} />
    </>
  )
}
