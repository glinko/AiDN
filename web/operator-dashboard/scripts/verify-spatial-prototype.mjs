import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const prototypeRoot = resolve(root, 'src/spatial/prototype')
const files = {
  environment: resolve(prototypeRoot, 'environment.ts'),
  environmentComponent: resolve(prototypeRoot, 'SpatialEnvironment.tsx'),
  primary: resolve(prototypeRoot, 'primary-agent.ts'),
  primaryComponent: resolve(prototypeRoot, 'SpatialPrimaryAgent.tsx'),
  entities: resolve(prototypeRoot, 'entities.ts'),
  entityComponent: resolve(prototypeRoot, 'SpatialEntityScene.tsx'),
  camera: resolve(prototypeRoot, 'camera.ts'),
  navigation: resolve(prototypeRoot, 'SpatialNavigationController.tsx'),
  performance: resolve(prototypeRoot, 'performance.ts'),
  gate: resolve(prototypeRoot, 'SpatialPrototypeGate.tsx'),
  workspace: resolve(root, 'src/spatial/workspace/SpatialWorkspace.tsx'),
  canvas: resolve(root, 'src/spatial/workspace/SpatialCanvas.tsx'),
}

function fail(message) {
  console.error(`Spatial Prototype A verification failed: ${message}`)
  process.exitCode = 1
}

const source = Object.fromEntries(await Promise.all(
  Object.entries(files).map(async ([name, path]) => [name, await readFile(path, 'utf8')]),
))

function requireSource(name, required) {
  if (!source[name].includes(required)) fail(`${name} is missing ${required}`)
}

for (const profile of ['low', 'mobile', 'desktop', 'high']) requireSource('environment', `${profile}: {`)
for (const required of ['fogNear', 'fogFar', 'dprCap', 'physicalMaterials', 'softShadows', 'reflections', 'postProcessing', 'particleBudget', 'studio-neutral', 'document.hidden']) {
  requireSource('environment', required)
}
for (const required of ['<fog attach="fog"', '<hemisphereLight', '<directionalLight', '<planeGeometry', 'Environment preset="studio"']) {
  requireSource('environmentComponent', required)
}
for (const forbidden of ['gridHelper', 'volumetric', 'depthOfField']) {
  if (source.environmentComponent.toLowerCase().includes(forbidden.toLowerCase())) fail(`environment includes forbidden ${forbidden}`)
}
if (source.environment.includes('postProcessing: true')) fail('post-processing is enabled in the bounded profiles')

for (const required of ['READY', 'THINKING', 'WORKING', 'OFFLINE', 'channel:', 'motion:', 'lod:', 'primaryAgentSequence']) requireSource('primary', required)
for (const required of ['meshPhysicalMaterial', 'sphereGeometry', 'pointLight', 'torusGeometry']) {
  requireSource('primaryComponent', required)
}

const counts = {
  subagents: (source.entities.match(/kind: 'subagent'/g) ?? []).length,
  endpoints: (source.entities.match(/kind: 'endpoint'/g) ?? []).length,
  artifacts: (source.entities.match(/kind: 'artifact'/g) ?? []).length,
  attention: (source.entities.match(/kind: 'attention'/g) ?? []).length,
  relations: (source.entities.match(/id: 'thread-/g) ?? []).length,
}
if (counts.subagents !== 3 || counts.endpoints !== 7 || counts.artifacts !== 6 || counts.attention !== 3 || counts.relations !== 2) {
  fail(`entity grammar counts are ${JSON.stringify(counts)}; expected 3/7/6/3 and 2 relations`)
}
for (const required of ['spatialEntityLod', 'spatialEntityById', 'spatialRelations']) requireSource('entities', required)
for (const required of ['instancedMesh', 'spatialEntityKind', 'onClick', 'spatialEntityLod']) requireSource('entityComponent', required)

for (const required of ['HOME_CAMERA', 'FOCUS_PRIMARY_AGENT', 'focusSpatialEntity', 'focusPrimaryAgent', 'homeSpatialCamera', 'returnFromSpatialFocus', 'clampSpatialCamera', 'transitionToken']) requireSource('camera', required)
for (const required of ['NavigationController', 'HOME', 'Focus selected', 'Escape', 'Zoom in', 'Zoom out']) requireSource('navigation', required)
for (const required of ['targetFps', 'maxFrameTimeMs', 'maxPointerLatencyMs', 'requestAnimationFrame', 'cancelAnimationFrame', 'visibilitychange', 'document.hidden']) requireSource('performance', required)
for (const required of ['data-aidn-prototype-gate', 'data-aidn-gate-check']) requireSource('gate', required)
for (const required of ['data-aidn-quality-profile', 'data-aidn-primary-agent-state', 'data-aidn-camera-focus', 'data-aidn-performance-gate', 'SpatialEntityList', 'SpatialNavigationController', 'FOCUS_PRIMARY_AGENT']) requireSource('workspace', required)
requireSource('canvas', 'WorkspaceCamera')
for (const required of ['data-aidn-canvas-atmosphere', 'data-aidn-canvas-fog', 'frameloop="demand"', 'data-aidn-canvas-hidden-animation']) requireSource('canvas', required)

if (process.exitCode !== 1) {
  console.log(`Verified Prototype A environment, primary-agent states, ${counts.subagents + counts.endpoints + counts.artifacts + counts.attention} entities, ${counts.relations} relations, camera controls, and performance gate.`)
}
