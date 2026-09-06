import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const reportPath = join(projectRoot, 'test-results', 'bundle-report.json')
const distIndexPath = join(projectRoot, 'dist', 'index.html')
const pnpmCommand = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'

function run(script) {
  execFileSync(pnpmCommand, ['run', script], {
    cwd: projectRoot,
    env: process.env,
    shell: process.platform === 'win32',
    stdio: 'inherit',
  })
}

if (!existsSync(reportPath)) {
  if (!existsSync(distIndexPath)) run('build')
  run('bundle:report')
}
const firstReport = readFileSync(reportPath, 'utf8')
run('build')
run('bundle:report')
const secondReport = readFileSync(reportPath, 'utf8')

if (firstReport !== secondReport) {
  console.error('Reproducible build check failed: bundle reports differ between identical builds')
  process.exitCode = 1
} else {
  console.log('Reproducible build check: passed')
}
