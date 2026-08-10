export function getRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

export function getText(value: unknown, key: string): string {
  const record = getRecord(value)
  const candidate = record?.[key]
  return typeof candidate === 'string' ? candidate : ''
}

export function getTextList(value: unknown, key: string): string[] {
  const record = getRecord(value)
  const candidate = record?.[key]
  return Array.isArray(candidate)
    ? candidate.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : []
}

export function shortId(value: string | undefined | null, limit = 13): string {
  if (!value) return '—'
  if (value.length <= limit) return value
  const edge = Math.max(3, Math.floor((limit - 1) / 2))
  return `${value.slice(0, edge)}…${value.slice(-edge)}`
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value)
}

export function formatPercent(value: number): string {
  return `${Math.round(Number.isFinite(value) ? value : 0)}%`
}

export function formatMemory(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 MB'
  if (value >= 1024) return `${(value / 1024).toFixed(value >= 10_240 ? 0 : 1)} GB`
  return `${Math.round(value)} MB`
}

export function resourceUsage(total = 0, free = 0): { total: number; used: number; percent: number } {
  const safeTotal = Number.isFinite(total) ? Math.max(0, total) : 0
  const safeFree = Number.isFinite(free) ? Math.max(0, free) : 0
  const used = Math.max(0, safeTotal - safeFree)
  return {
    total: safeTotal,
    used,
    percent: safeTotal > 0 ? Math.min(100, (used / safeTotal) * 100) : 0,
  }
}
