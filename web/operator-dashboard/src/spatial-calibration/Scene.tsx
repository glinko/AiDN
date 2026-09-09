import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Billboard, Environment, Lightformer, OrbitControls, RoundedBox } from '@react-three/drei'
import { Color, Group, HalfFloatType, NeutralToneMapping, Vector2, WebGLRenderTarget } from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'

import { DEFAULT_CALIBRATION, createCalibrationEntities } from './model'
import { createAtmosphereMaterial, createGlassFinish, createHaloMaterial, createPearlMaterial } from './materials'
import { MilkGround } from './MilkGround'
import { SolarEndpoint } from './SolarEndpoint'
import { EndpointEntity } from './endpoint'

export type SceneProps = {
  paused: boolean
  reducedMotion: boolean
  resetKey: number
  onReady: () => void
}

function StudioEnvironment() {
  const atmosphere = useMemo(createAtmosphereMaterial, [])
  useEffect(() => () => atmosphere.dispose(), [atmosphere])
  return <>
    <mesh material={atmosphere} renderOrder={-10}>
      <sphereGeometry args={[70, 32, 20]} />
    </mesh>
    <Environment resolution={128} frames={1}>
      <color attach="background" args={['#e3eaf7']} />
      <Lightformer form="rect" intensity={3.5} color="#ffffff" position={[-3.5, 5, 4]} target={[0, 0, 0]} scale={[5, 3, 1]} />
      <Lightformer form="rect" intensity={1.5} color="#b9e1ff" position={[-4, 0.5, 1]} target={[0, 0, 0]} scale={[4, 5, 1]} />
      <Lightformer form="rect" intensity={1.4} color="#c6b5f8" position={[4, 1.2, 0]} target={[0, 0, 0]} scale={[3, 5, 1]} />
      <Lightformer form="rect" intensity={1.3} color="#ffe1cf" position={[2, -1, 3]} target={[0, 0, 0]} scale={[3, 2, 1]} />
      <Lightformer form="rect" intensity={2.2} color="#ffffff" position={[0, 4, -4]} target={[0, 0, 0]} scale={[5, 2, 1]} />
    </Environment>
    <ambientLight intensity={0.7} color="#e8f0ff" />
    <directionalLight position={[-4, 7, 5]} intensity={2.1} color="#fffaf5" />
    <directionalLight position={[4, 2, -1]} intensity={0.4} color="#c5c6f5" />
  </>
}

// A soft analytic penumbra complements the actual reflected scene above the floor.
function Penumbra({ x, z, scale }: { x: number; z: number; scale: [number, number, number] }) {
  const material = useMemo(() => createHaloMaterial(), [])
  useEffect(() => () => material.dispose(), [material])
  // Radial alpha is a shader, keeping the page independent of image/CDN requests.
  const fragment = /* glsl */ `
    varying vec2 vUv;
    void main(){
      float radius=length(vUv-0.5)*2.0;
      float alpha=exp(-radius*radius*6.0)*0.075*smoothstep(1.0,0.75,radius);
      gl_FragColor=vec4(0.36,0.44,0.58,alpha);
      #include <colorspace_fragment>
    }
  `
  material.fragmentShader = fragment
  return <mesh position={[x + 0.16, 0.004, z + 0.08]} rotation={[-Math.PI / 2, 0, 0]} scale={scale} material={material}>
    <planeGeometry args={[4, 4]} />
  </mesh>
}

function OpticalFinish() {
  const { gl, scene, camera, size } = useThree()
  const pipeline = useMemo(() => {
    const target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples: 0 })
    const composer = new EffectComposer(gl, target)
    const render = new RenderPass(scene, camera)
    const bloom = new UnrealBloomPass(new Vector2(1, 1), 0.16, 0.72, 1.02)
    const output = new OutputPass()
    composer.addPass(render)
    composer.addPass(bloom)
    composer.addPass(output)
    return { composer, bloom, output }
  }, [gl, scene, camera])
  useEffect(() => {
    pipeline.composer.setPixelRatio(gl.getPixelRatio())
    pipeline.composer.setSize(size.width, size.height)
  }, [pipeline, gl, size])
  useEffect(() => () => {
    pipeline.composer.dispose()
    pipeline.bloom.dispose()
    pipeline.output.dispose()
  }, [pipeline])
  useFrame((_, delta) => pipeline.composer.render(delta), 1)
  return null
}

export function CalibrationScene({ paused, reducedMotion, resetKey, onReady }: SceneProps) {
  const { size, camera, gl, invalidate } = useThree()
  const compact = size.width < 680
  const entities = useMemo(() => createCalibrationEntities(), [])
  const endpoint = useMemo(() => new EndpointEntity(), [])
  const orbGroup = useRef<Group>(null)
  const cubeGroup = useRef<Group>(null)
  const controls = useRef<OrbitControlsImpl>(null)
  const time = useRef(0)
  const firstFrame = useRef(true)
  const pearl = useMemo(() => createPearlMaterial(0.70), [])
  const cubeSurface = useMemo(() => createGlassFinish(entities.cube.size), [entities])
  const halo = useMemo(createHaloMaterial, [])

  useEffect(() => {
    if (paused || reducedMotion) { invalidate(); return }
    const timer = window.setInterval(() => {
      if (!document.hidden) invalidate()
    }, 1000 / 30)
    return () => window.clearInterval(timer)
  }, [paused, reducedMotion, invalidate])

  useEffect(() => () => { pearl.dispose(); cubeSurface.dispose(); halo.dispose() }, [pearl, cubeSurface, halo])
  useEffect(() => {
    gl.toneMapping = NeutralToneMapping
    gl.toneMappingExposure = 1.05
    gl.setClearColor(new Color('#f4f6fb'), 1)
  }, [gl])
  useEffect(() => {
    // Keep both silhouettes in view on portrait screens without scaling objects independently.
    camera.position.fromArray(compact ? DEFAULT_CALIBRATION.camera.compactPosition : DEFAULT_CALIBRATION.camera.position)
    camera.lookAt(...DEFAULT_CALIBRATION.camera.target)
    controls.current?.target.fromArray(DEFAULT_CALIBRATION.camera.target)
    controls.current?.update()
    invalidate()
  }, [camera, compact, resetKey, invalidate])

  useFrame((_, delta) => {
    if (!paused && !reducedMotion) time.current += Math.min(delta, 0.05)
    entities.orb.update(time.current, reducedMotion)
    entities.cube.update(time.current, reducedMotion)
    endpoint.update(time.current, reducedMotion)
    if (orbGroup.current) orbGroup.current.position.fromArray(entities.orb.position)
    if (cubeGroup.current) {
      cubeGroup.current.position.fromArray(entities.cube.position)
      cubeGroup.current.rotation.fromArray([...entities.cube.rotation, 'XYZ'])
    }
    pearl.uniforms.uTime.value = time.current
    if (firstFrame.current) { firstFrame.current = false; onReady() }
  })

  return <>
    <fog attach="fog" args={['#f4f6fb', 12, 38]} />
    <StudioEnvironment />
    <MilkGround compact={compact} />
    <Penumbra x={-1.1} z={0} scale={[1.1, 0.65, 1]} />
    <Penumbra x={1.35} z={0.4} scale={[0.6, 0.45, 1]} />

    <group ref={orbGroup} position={entities.orb.position} name="primary-orb">
      <mesh scale={1.002} material={pearl} renderOrder={2}>
        <sphereGeometry args={[entities.orb.radius, 64, 48]} />
      </mesh>
      <mesh>
        <sphereGeometry args={[entities.orb.radius, 64, 48]} />
        <meshPhysicalMaterial {...entities.orb.material} />
      </mesh>
      <Billboard>
        <mesh position={[0, 0, -0.04]} material={halo}>
          <planeGeometry args={[2.94, 2.94]} />
        </mesh>
      </Billboard>
    </group>

    <group ref={cubeGroup} position={entities.cube.position} name="session-cube">
      <mesh material={cubeSurface} scale={1.003} renderOrder={2}>
        <boxGeometry args={[entities.cube.size, entities.cube.size, entities.cube.size]} />
      </mesh>
      <RoundedBox args={[entities.cube.size, entities.cube.size, entities.cube.size]} radius={0.016} smoothness={3}>
        <meshPhysicalMaterial depthWrite={false} {...entities.cube.material} />
      </RoundedBox>
    </group>
    <SolarEndpoint entity={endpoint} />
    <OrbitControls ref={controls} makeDefault enablePan={false} enableZoom={false}
      enableDamping={!reducedMotion} dampingFactor={0.06} rotateSpeed={0.32}
      minPolarAngle={1.12} maxPolarAngle={1.5} minAzimuthAngle={-0.45} maxAzimuthAngle={0.45}
      target={[0.15, 1.45, 0]} />
    <OpticalFinish />
  </>
}
