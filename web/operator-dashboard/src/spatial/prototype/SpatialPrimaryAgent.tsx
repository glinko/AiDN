import { useMemo } from 'react'

import { primaryAgentAccentColor, primaryAgentVisual, type PrimaryAgentState } from './primary-agent'
import { spatialEnvironmentProfile, type SpatialQualityProfile } from './environment'
import type { PrimaryAgentPresenceViewModel } from '../data/primary-agent-presence'

export type SpatialPrimaryAgentProps = {
  state: PrimaryAgentState
  profile: SpatialQualityProfile
  prefersReducedMotion?: boolean
  presence?: PrimaryAgentPresenceViewModel
}

function AgentParticles({ state, profile }: Pick<SpatialPrimaryAgentProps, 'state' | 'profile'>) {
  const count = spatialEnvironmentProfile(profile).particleBudget
  const particlePositions = useMemo(() => Array.from({ length: count }, (_, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(count, 1)
    const radius = state === 'WORKING' ? 1.08 + (index % 2) * 0.16 : 0.96
    return [Math.cos(angle) * radius, Math.sin(angle) * radius, Math.sin(angle * 2) * 0.12] as const
  }), [count, state])

  if (count === 0 || state === 'OFFLINE') return null
  return (
    <group userData={{ spatialParticleField: 'primary-agent' }}>
      {particlePositions.map((position, index) => (
        <mesh key={index} position={position}>
          <sphereGeometry args={[0.035, 8, 8]} />
          <meshBasicMaterial color={primaryAgentAccentColor(state)} transparent opacity={0.72} />
        </mesh>
      ))}
    </group>
  )
}

/** Primary Agent material prototype. State is deliberately presentation-only. */
export function SpatialPrimaryAgent({ state, profile, prefersReducedMotion = false, presence }: SpatialPrimaryAgentProps) {
  const visual = primaryAgentVisual(state, profile, prefersReducedMotion)
  const accent = presence?.material.accentColor ?? primaryAgentAccentColor(state)
  const bodyColor = presence?.material.bodyColor ?? (state === 'OFFLINE' ? '#b7c1cf' : '#f7fbff')
  const simple = visual.lod === 'simple'

  return (
    <group position={[0, 0.42, 0]} userData={{ spatialEntityId: 'primary-agent', state, channel: visual.channel }}>
      <pointLight color={accent} intensity={presence?.material.glowIntensity ?? (state === 'OFFLINE' ? 0.2 : 0.9)} distance={4} decay={2} />
      <mesh castShadow={!simple}>
        <sphereGeometry args={[0.82, simple ? 20 : 36, simple ? 20 : 36]} />
        <meshPhysicalMaterial
          color={bodyColor}
          roughness={simple ? 0.38 : 0.14}
          metalness={0}
          transmission={simple ? 0 : 0.82}
          thickness={1.4}
          ior={1.32}
          transparent={!simple}
          opacity={simple ? 1 : state === 'OFFLINE' ? 0.76 : 0.98}
        />
      </mesh>
      <mesh scale={state === 'THINKING' ? 0.48 : state === 'CRITICAL' ? 0.46 : 0.4}>
        <sphereGeometry args={[1, simple ? 12 : 24, simple ? 12 : 24]} />
        <meshBasicMaterial color={accent} transparent={!simple} opacity={simple ? 1 : state === 'OFFLINE' ? 0.2 : 0.7} />
      </mesh>
      {state !== 'OFFLINE' ? (
        <mesh rotation={[Math.PI / 2, 0, 0]} scale={state === 'WORKING' ? 1.28 : 1.15}>
          <torusGeometry args={[0.88, 0.018, 8, 64]} />
          <meshBasicMaterial color={accent} transparent opacity={visual.motion === 'static' ? 0.5 : 0.72} />
        </mesh>
      ) : null}
      {presence?.attention.visible ? (
        <mesh rotation={[Math.PI / 2, 0, 0]} scale={presence.attention.severity === 'CRITICAL' ? 1.5 : 1.35} userData={{ spatialAttentionOverlay: presence.attention.severity }}>
          <torusGeometry args={[0.88, presence.attention.severity === 'CRITICAL' ? 0.034 : 0.022, 8, 64]} />
          <meshBasicMaterial color={presence.attention.color} transparent opacity={visual.motion === 'static' ? 0.62 : 0.9} />
        </mesh>
      ) : null}
      <AgentParticles state={state} profile={profile} />
    </group>
  )
}
