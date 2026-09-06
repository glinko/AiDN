import { Environment } from '@react-three/drei'

import { spatialAtmosphere, spatialEnvironmentProfile, type SpatialQualityProfile } from './environment'

export type SpatialEnvironmentProps = {
  profile: SpatialQualityProfile
}

/** M1.4 neutral studio environment: fog, matte ground, horizon, and bounded lights. */
export function SpatialEnvironment({ profile }: SpatialEnvironmentProps) {
  const settings = spatialEnvironmentProfile(profile)

  return (
    <>
      <color attach="background" args={[spatialAtmosphere.background]} />
      <fog attach="fog" args={[spatialAtmosphere.horizon, settings.fogNear, settings.fogFar]} />
      <hemisphereLight
        color="#ffffff"
        groundColor={spatialAtmosphere.ground}
        intensity={profile === 'high' ? 1.1 : 0.9}
      />
      <directionalLight
        color="#fffdf9"
        position={[-3.5, 5, 4]}
        intensity={profile === 'low' || profile === 'mobile' ? 1.15 : 1.55}
        castShadow={settings.softShadows}
        shadow-mapSize={settings.softShadows ? [1024, 1024] : undefined}
      />
      <directionalLight color="#dcecff" position={[4, 1.5, -2]} intensity={0.45} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.15, -1.5]} receiveShadow={settings.softShadows}>
        <planeGeometry args={[40, 40]} />
        <meshStandardMaterial color={spatialAtmosphere.ground} roughness={0.94} metalness={0} />
      </mesh>
      {settings.reflections ? <Environment preset="studio" environmentIntensity={0.24} /> : null}
    </>
  )
}
