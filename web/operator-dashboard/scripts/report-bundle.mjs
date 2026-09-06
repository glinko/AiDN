import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, dirname, extname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { brotliCompressSync, gzipSync } from 'node:zlib'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const distRoot = join(projectRoot, 'dist')
const defaultReportPath = join(projectRoot, 'test-results', 'bundle-report.json')
const reportPath = resolve(projectRoot, process.env.AIDN_BUNDLE_REPORT_PATH ?? defaultReportPath)
const spatialBundleMarker = 'aidn-spatial-runtime-m05'

const budgets = {
  classic_initial_gzip_bytes: readBudget('AIDN_CLASSIC_INITIAL_GZIP_BUDGET', 300_000),
  classic_initial_brotli_bytes: readBudget('AIDN_CLASSIC_INITIAL_BROTLI_BUDGET', 240_000),
  spatial_lazy_gzip_bytes: readBudget('AIDN_SPATIAL_LAZY_GZIP_BUDGET', 450_000),
  spatial_lazy_brotli_bytes: readBudget('AIDN_SPATIAL_LAZY_BROTLI_BUDGET', 360_000),
  total_gzip_bytes: readBudget('AIDN_DASHBOARD_TOTAL_GZIP_BUDGET', 800_000),
  total_brotli_bytes: readBudget('AIDN_DASHBOARD_TOTAL_BROTLI_BUDGET', 650_000),
}

function readBudget(name, fallback) {
  const raw = process.env[name]
  if (raw === undefined || raw === '') return fallback
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer byte count`)
  return value
}

function collectFiles(root) {
  const files = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) files.push(...collectFiles(path))
    else files.push(path)
  }
  return files
}

function assetName(path) {
  return relative(distRoot, path).split(sep).join('/')
}

function resolveAssetUrl(reference) {
  const normalized = decodeURIComponent(reference.split('?', 1)[0])
  const assetsMarker = '/assets/'
  const markerIndex = normalized.indexOf(assetsMarker)
  const relativeAsset = markerIndex >= 0 ? normalized.slice(markerIndex + 1) : normalized.replace(/^\/+/, '')
  const path = join(distRoot, relativeAsset)
  if (!existsSync(path)) throw new Error(`index.html references a missing asset: ${reference}`)
  return path
}

function metric(paths) {
  const files = [...new Set(paths)].sort((left, right) => {
    const leftName = assetName(left)
    const rightName = assetName(right)
    return leftName < rightName ? -1 : leftName > rightName ? 1 : 0
  })
  let bytes = 0
  let gzipBytes = 0
  let brotliBytes = 0
  for (const path of files) {
    const content = readFileSync(path)
    bytes += content.byteLength
    gzipBytes += gzipSync(content, { level: 9 }).byteLength
    brotliBytes += brotliCompressSync(content).byteLength
  }
  return {
    files: files.map(assetName),
    bytes,
    gzip_bytes: gzipBytes,
    brotli_bytes: brotliBytes,
  }
}

function isSpatialChunk(path) {
  const name = basename(path).toLowerCase()
  if (name.includes('spatial-route')) return true
  return readFileSync(path, 'utf8').includes(spatialBundleMarker)
}

function formatKiB(value) {
  return `${(value / 1024).toFixed(1)} KiB`
}

if (!existsSync(join(distRoot, 'index.html'))) {
  throw new Error(`Dashboard build output is missing: ${join(distRoot, 'index.html')}`)
}

const allFiles = collectFiles(distRoot)
const javascript = allFiles.filter((path) => extname(path).toLowerCase() === '.js')
if (javascript.length === 0) throw new Error('Dashboard build did not produce JavaScript assets')

const html = readFileSync(join(distRoot, 'index.html'), 'utf8')
const entryReferences = [
  ...[...html.matchAll(/<script[^>]+src=["']([^"']+\.js(?:\?[^"']*)?)["']/gi)].map((match) => match[1]),
  ...[...html.matchAll(/<link[^>]+rel=["']modulepreload["'][^>]+href=["']([^"']+\.js(?:\?[^"']*)?)["']/gi)].map((match) => match[1]),
]
if (entryReferences.length === 0) throw new Error('Dashboard index.html has no module entry script')

const initialFiles = [...new Set(entryReferences.map(resolveAssetUrl).filter((path) => extname(path).toLowerCase() === '.js'))]
const spatialFiles = javascript.filter(isSpatialChunk)
if (spatialFiles.length === 0) {
  throw new Error(`No lazy Spatial chunk found; expected a chunk containing ${spatialBundleMarker}`)
}

const initialSet = new Set(initialFiles)
const initialSpatialFiles = spatialFiles.filter((path) => initialSet.has(path))
const spatialLazyFiles = spatialFiles.filter((path) => !initialSet.has(path))
const failures = []
if (initialSpatialFiles.length > 0) {
  failures.push(`Classic initial entry includes Spatial assets: ${initialSpatialFiles.map(assetName).join(', ')}`)
}
if (spatialLazyFiles.length === 0) failures.push('Spatial assets are not isolated in a lazy chunk')

const initial = metric(initialFiles)
const spatialLazy = metric(spatialLazyFiles)
const total = metric(javascript)
const checks = {
  classic_initial_gzip: initial.gzip_bytes <= budgets.classic_initial_gzip_bytes,
  classic_initial_brotli: initial.brotli_bytes <= budgets.classic_initial_brotli_bytes,
  spatial_lazy_gzip: spatialLazy.gzip_bytes <= budgets.spatial_lazy_gzip_bytes,
  spatial_lazy_brotli: spatialLazy.brotli_bytes <= budgets.spatial_lazy_brotli_bytes,
  total_gzip: total.gzip_bytes <= budgets.total_gzip_bytes,
  total_brotli: total.brotli_bytes <= budgets.total_brotli_bytes,
}
for (const [name, passed] of Object.entries(checks)) {
  if (!passed) failures.push(`${name} exceeds its configured budget`)
}

const report = {
  schema_version: 1,
  entry_scripts: initialFiles.map(assetName).sort(),
  classic_initial_js: initial,
  spatial_lazy_js: spatialLazy,
  all_js: total,
  spatial_chunks: spatialFiles.map(assetName).sort(),
  budgets,
  checks,
}

const distRelativeReport = relative(distRoot, reportPath)
if (distRelativeReport === '' || (!distRelativeReport.startsWith(`..${sep}`) && distRelativeReport !== '..')) {
  throw new Error('Bundle reports must be written outside dist so generated dashboard assets remain unchanged')
}
mkdirSync(dirname(reportPath), { recursive: true })
writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')

console.log(`Classic initial JS: ${formatKiB(initial.gzip_bytes)} gzip / ${formatKiB(initial.brotli_bytes)} Brotli`)
console.log(`Spatial lazy JS:   ${formatKiB(spatialLazy.gzip_bytes)} gzip / ${formatKiB(spatialLazy.brotli_bytes)} Brotli`)
console.log(`All dashboard JS:  ${formatKiB(total.gzip_bytes)} gzip / ${formatKiB(total.brotli_bytes)} Brotli`)
console.log(`Bundle report:     ${reportPath}`)

if (failures.length > 0) {
  console.error('Bundle budget check failed:')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('Bundle budget check: passed')
}
