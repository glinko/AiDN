import { useEffect, useMemo } from 'react'
import { Color, Matrix4, PlaneGeometry } from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'
import { DEFAULT_CALIBRATION } from './model'

/** A linear-light reflection composite, not a second lit diffuse surface. */
export function MilkGround({ compact }: { compact: boolean }) {
  const floor = useMemo(() => {
    const config = DEFAULT_CALIBRATION.floor
    const geometry = new PlaneGeometry(config.size, config.size)
    const reflector = new Reflector(geometry, {
      textureWidth: compact ? config.reflection.compactResolution : config.reflection.resolution,
      textureHeight: compact ? config.reflection.compactResolution : config.reflection.resolution,
      multisample: 0,
      clipBias: 0.003,
      color: config.color,
      shader: {
        name: 'MilkReflection',
        uniforms: {
          color: { value: new Color() }, tDiffuse: { value: null }, textureMatrix: { value: new Matrix4() },
          uStrength: { value: config.reflection.strength },
          uBlurNear: { value: config.reflection.blurNear }, uBlurFar: { value: config.reflection.blurFar },
        },
        vertexShader: `
          uniform mat4 textureMatrix;
          varying vec4 vReflection;
          varying vec3 vWorld;
          void main() {
            vReflection = textureMatrix * vec4(position, 1.0);
            vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: `
          uniform sampler2D tDiffuse;
          uniform vec3 color;
          uniform float uStrength;
          uniform float uBlurNear;
          uniform float uBlurFar;
          varying vec4 vReflection;
          varying vec3 vWorld;
          void main() {
            vec2 uv = vReflection.xy / vReflection.w;
            float spread = uBlurNear + smoothstep(0.0, 7.0, vWorld.z) * uBlurFar;
            vec3 reflected = vec3(0.0);
            float weights = 0.0;
            for (int x=-2; x<=2; x++) {
              for (int y=-2; y<=2; y++) {
                float weight = exp(-float(x*x+y*y)*0.6);
                reflected += texture2D(tDiffuse, uv+vec2(float(x),float(y))*spread).rgb * weight;
                weights += weight;
              }
            }
            reflected /= weights;
            float fade = 1.0-smoothstep(1.0, 11.0, vWorld.z);
            float horizon = smoothstep(4.0, 32.0, -vWorld.z);
            float strength = uStrength * fade * (1.0-horizon);
            vec3 milk = mix(color,vec3(0.925,0.941,0.965),horizon);
            gl_FragColor = vec4(mix(milk, reflected, strength), 1.0);
            #include <tonemapping_fragment>
            #include <colorspace_fragment>
          }`,
      },
    })
    reflector.rotation.x = -Math.PI / 2
    reflector.position.y = -0.015
    return reflector
  }, [compact])
  useEffect(() => () => { floor.geometry.dispose(); floor.dispose() }, [floor])
  return <primitive object={floor} />
}
