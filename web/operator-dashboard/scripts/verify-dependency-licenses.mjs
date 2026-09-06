import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const packageJson = JSON.parse(readFileSync(join(projectRoot, 'package.json'), 'utf8'))
const spatialDependencies = ['three', '@react-three/fiber', '@react-three/drei', 'motion']
const failures = []

for (const name of spatialDependencies) {
  const packagePath = join(projectRoot, 'node_modules', ...name.split('/'), 'package.json')
  const installed = JSON.parse(readFileSync(packagePath, 'utf8'))
  const declared = packageJson.dependencies?.[name]
  if (!declared) failures.push(`${name} is missing from package.json dependencies`)
  if (installed.license !== 'MIT') failures.push(`${name}@${installed.version} declares ${installed.license ?? 'no license'} (expected MIT)`)
  console.log(`${name}@${installed.version} — ${installed.license ?? 'no license'}`)
}

if (failures.length > 0) {
  console.error('Spatial dependency license check failed:')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('Spatial dependency license check: passed')
}

