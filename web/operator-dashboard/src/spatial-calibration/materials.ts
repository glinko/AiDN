import { BackSide, Color, DoubleSide, ShaderMaterial } from 'three'

const vertex = /* glsl */ `
  varying vec3 vNormalWorld;
  varying vec3 vWorld;
  varying vec3 vLocal;
  void main() {
    vLocal = position;
    vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
    vNormalWorld = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * vec4(vWorld, 1.0);
  }
`

// These are authored optical layers, not a physically accurate volume simulation.
// World-space reflection lobes remain anchored as geometry/camera moves.
export function createPearlMaterial(opacity = 0.76, pulseColor = '#f26f68', pulseColorAmount = 0.38) {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      uTime: { value: 0 },
      uOpacity: { value: opacity },
      uPulseColor: { value: new Color(pulseColor) },
      uPulseColorAmount: { value: pulseColorAmount },
    },
    vertexShader: vertex,
    fragmentShader: /* glsl */ `
      uniform float uTime;
      uniform float uOpacity;
      uniform vec3 uPulseColor;
      uniform float uPulseColorAmount;
      varying vec3 vNormalWorld;
      varying vec3 vWorld;
      varying vec3 vLocal;
      float lobe(vec3 n, vec3 direction, float power) {
        return pow(max(dot(n, normalize(direction)), 0.0), power);
      }
      void main() {
        vec3 n = normalize(vNormalWorld);
        vec3 view = normalize(cameraPosition - vWorld);
        float facing = max(dot(n, view), 0.0);
        float rim = pow(1.0 - facing, 2.8);
        float cloud = sin(vLocal.x * 3.4 + vLocal.y * 2.7 + uTime * 0.10)
                    * sin(vLocal.z * 3.1 - vLocal.y * 2.2 + uTime * 0.065);
        vec3 pearl = vec3(0.60, 0.73, 0.86);
        pearl = mix(pearl, vec3(0.16, 0.55, 0.84), lobe(n, vec3(-0.55,0.3,0.85), 2.5) * 0.68);
        pearl = mix(pearl, vec3(0.56, 0.30, 0.88), lobe(n, vec3(0.75,-0.10,0.75), 3.0) * 0.64);
        pearl = mix(pearl, vec3(1.00, 0.60, 0.52), lobe(n, vec3(0.45,-0.80,0.6), 5.0) * 0.44);
        pearl = mix(pearl, vec3(0.72, 0.89, 0.95), cloud * 0.10 + 0.10);
        // A front-facing volume gradient keeps the rim misty while the center carries pigment.
        float front = smoothstep(0.08, 0.94, facing);
        pearl = mix(vec3(0.86, 0.91, 0.97), pearl, front);
        pearl *= mix(1.04, 0.80, front);
        // A restrained warm chroma breath keeps the optical color alive without moving the light source.
        float colorBreath = 0.5 + 0.5 * sin(uTime * 1.04719755 + n.y * 1.6);
        vec3 colorTint = mix(vec3(1.0), uPulseColor, colorBreath * uPulseColorAmount);
        pearl *= colorTint;
        float spectral = sin((1.0 - facing) * 10.0 + n.y * 2.2 + cloud * 0.2);
        pearl += vec3(0.025, -0.009, 0.018) * spectral;
        pearl = mix(pearl, vec3(1.65), rim * 0.95);
        float softbox = lobe(n, vec3(-0.6,0.8,0.8), 28.0);
        pearl += vec3(0.25) * softbox;
        float volumeAlpha = mix(uOpacity * 0.82, uOpacity * 1.08, front);
        gl_FragColor = vec4(pearl, volumeAlpha + rim * 0.16);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  })
}

export function createAtmosphereMaterial() {
  return new ShaderMaterial({
    side: BackSide,
    depthWrite: false,
    vertexShader: vertex,
    fragmentShader: /* glsl */ `
      varying vec3 vWorld;
      void main() {
        vec3 direction = normalize(vWorld - cameraPosition);
        vec3 sky = vec3(0.925, 0.941, 0.965);
        float horizon = exp(-pow((direction.y + 0.055) * 18.0, 2.0));
        float cyan = exp(-pow((direction.x + 0.38) * 2.5, 2.0) - pow(direction.y * 3.0, 2.0));
        float lilac = exp(-pow((direction.x - 0.5) * 2.0, 2.0) - pow((direction.y-0.15)*3.0,2.0));
        sky = mix(sky, vec3(0.83,0.92,0.96), cyan * 0.25);
        sky = mix(sky, vec3(0.91,0.87,0.97), lilac * 0.16);
        sky += horizon * 0.035;
        gl_FragColor = vec4(sky,1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  })
}

/** Thin glass finish: clear face centers, softly luminous physical edge regions. */
export function createGlassFinish(size: number) {
  return new ShaderMaterial({
    transparent: true, depthWrite: false, side: DoubleSide,
    uniforms: { uHalfSize: { value: size / 2 } },
    vertexShader: vertex,
    fragmentShader: `
      uniform float uHalfSize;
      varying vec3 vNormalWorld;
      varying vec3 vWorld;
      varying vec3 vLocal;
      void main() {
        vec3 n = normalize(vNormalWorld);
        vec3 v = normalize(cameraPosition-vWorld);
        vec3 p = abs(vLocal/uHalfSize);
        float second = min(max(p.x,p.y), min(max(p.x,p.z),max(p.y,p.z)));
        float edge = smoothstep(0.89, 0.998, second);
        float fresnel = pow(1.0-abs(dot(n,v)),3.0);
        vec3 r = reflect(-v,n);
        float softbox = pow(max(dot(r,normalize(vec3(-0.6,0.8,0.9))),0.0),12.0);
        float cyan = max(dot(n,normalize(vec3(-1.0,0.2,0.6))),0.0);
        float peach = max(dot(n,normalize(vec3(1.0,0.4,0.1))),0.0);
        vec3 tint = mix(vec3(0.46,0.52,0.74),vec3(0.30,0.63,0.80),cyan);
        tint = mix(tint,vec3(0.84,0.60,0.55),peach*0.6);
        float front = smoothstep(0.04, 0.92, max(dot(n,v), 0.0));
        vec3 glass = mix(tint * mix(0.48, 0.84, front), vec3(1.25), edge*0.9);
        glass += softbox * 0.42;
        float alpha = 0.13 + front*0.14 + fresnel*0.10 + edge*0.58 + softbox*0.18;
        if (!gl_FrontFacing) alpha *= 0.52;
        gl_FragColor = vec4(glass,alpha);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  })
}

export function createHaloMaterial() {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    toneMapped: false,
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }
    `,
    fragmentShader: /* glsl */ `
      varying vec2 vUv;
      void main(){
        float r=length(vUv-0.5)*2.0;
        float halo=exp(-pow((r-0.70)*15.0,2.0))*0.23;
        gl_FragColor=vec4(1.0,1.0,1.0,halo);
        #include <colorspace_fragment>
      }
    `,
  })
}
