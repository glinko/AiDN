export type SavedHypervisorConnection = {
  id: string
  name: string
  url: string
  addedAt: string
}

export const savedHypervisorsStorageKey = 'aidn.dashboard.hypervisors.v1'

function isSavedHypervisorConnection(value: unknown): value is SavedHypervisorConnection {
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return typeof record.id === 'string'
    && typeof record.name === 'string'
    && typeof record.url === 'string'
    && typeof record.addedAt === 'string'
}

export function loadSavedHypervisors(): SavedHypervisorConnection[] {
  if (typeof window === 'undefined') return []

  try {
    const raw = window.localStorage.getItem(savedHypervisorsStorageKey)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isSavedHypervisorConnection) : []
  } catch {
    return []
  }
}

export function saveSavedHypervisors(connections: SavedHypervisorConnection[]): void {
  window.localStorage.setItem(savedHypervisorsStorageKey, JSON.stringify(connections))
}

export function normalizeDashboardUrl(value: string): string {
  const parsed = new URL(value.trim())
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('Dashboard URL must use http:// or https://.')
  }
  if (parsed.username || parsed.password) {
    throw new Error('Dashboard URLs must not contain embedded credentials.')
  }
  parsed.hash = ''
  parsed.search = ''
  return parsed.toString().replace(/\/$/, '')
}

export function createSavedHypervisor(name: string, url: string): SavedHypervisorConnection {
  const normalizedUrl = normalizeDashboardUrl(url)
  const normalizedName = name.trim() || new URL(normalizedUrl).hostname
  return {
    id: normalizedUrl,
    name: normalizedName.slice(0, 96),
    url: normalizedUrl,
    addedAt: new Date().toISOString(),
  }
}
