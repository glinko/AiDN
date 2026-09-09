import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard } from '@react-three/drei'
import { Color, Group, InstancedMesh, Object3D, ShaderMaterial } from 'three'
import { EndpointEntity } from './endpoint'

const samples = 40

function createCorona(color: string) {
  return new ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uColor: { value: new Color(color) } },
    vertexShader: `varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
    fragmentShader: `
      uniform float uTime;
      uniform vec3 uColor;
      varying vec2 vUv;
      void main(){
        vec2 p=(vUv-.5)*2.0;
        float r=length(p);
        float a=atan(p.y,p.x);
        float tongues=pow(0.5+0.5*sin(a*9.0+sin(a*5.0-uTime*.22)),5.0);
        float fine=0.5+0.5*sin(a*23.0+sin(a*8.0+uTime*.3));
        float edge=.48+0.045*sin(a*7.0+uTime*.18)+tongues*.16;
        float rays=exp(-abs(r-edge)*21.0)*(0.24+tongues*.48+fine*.12);
        float glow=exp(-pow((r-.46)*6.0,2.0))*.18;
        float alpha=(rays+glow)*smoothstep(.37,.48,r)*(1.0-smoothstep(.83,1.0,r));
        vec3 corona=mix(uColor*.78,vec3(1.45),tongues*.26);
        gl_FragColor=vec4(corona,alpha*1.10);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
}

export function SolarEndpoint({ entity }: { entity: EndpointEntity }) {
  const group = useRef<Group>(null)
  const meteors = useRef<InstancedMesh>(null)
  const corona = useMemo(() => createCorona(entity.config.coronaColor), [entity])
  const dummy = useMemo(() => new Object3D(), [])
  const colors = useMemo(() => entity.config.meteorColors.map(value => new Color(value)), [entity])
  const tint = useMemo(() => new Color(), [])
  const white = useMemo(() => new Color('#ffffff'), [])
  useEffect(() => () => corona.dispose(), [corona])
  useFrame(() => {
    group.current?.position.fromArray(entity.position)
    corona.uniforms.uTime.value = entity.time
    if (!meteors.current) return
    for (let meteor = 0; meteor < 3; meteor++) {
      for (let sample = 0; sample < samples; sample++) {
        const tail = sample / (samples - 1)
        dummy.position.fromArray(entity.sampleMeteor(meteor, tail))
        dummy.scale.setScalar(sample === 0 ? 0.046 : 0.027 * Math.pow(1-tail,1.1) + 0.001)
        dummy.updateMatrix()
        const index = meteor * samples + sample
        meteors.current.setMatrixAt(index, dummy.matrix)
        tint.copy(colors[meteor]).lerp(white, sample === 0 ? 0.75 : tail * 0.75)
        meteors.current.setColorAt(index, tint)
      }
    }
    meteors.current.instanceMatrix.needsUpdate = true
    if (meteors.current.instanceColor) meteors.current.instanceColor.needsUpdate = true
  })
  return <group ref={group} position={entity.position} name="solar-endpoint">
    <mesh>
      <sphereGeometry args={[entity.config.radius, 48, 32]} />
      <meshPhysicalMaterial color={entity.config.coreColor} emissive={entity.config.coreColor} emissiveIntensity={0.32}
        roughness={0.26} metalness={0.06} iridescence={0.22} clearcoat={1} />
    </mesh>
    <Billboard><mesh material={corona}><planeGeometry args={[entity.config.radius*4.4,entity.config.radius*4.4]} /></mesh></Billboard>
    <instancedMesh ref={meteors} args={[undefined,undefined,3*samples]} frustumCulled={false}>
      <sphereGeometry args={[1,10,8]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  </group>
}
