export type SpatialLocale = 'en' | 'ru'

export const SPATIAL_LOCALES: readonly SpatialLocale[] = ['en', 'ru']

export function spatialLocaleLanguageTag(locale: SpatialLocale): 'en-US' | 'ru-RU' {
  return locale === 'ru' ? 'ru-RU' : 'en-US'
}

export const SPATIAL_CATALOG = {
  en: {
    'resources.balance': 'Balance',
    'resources.usage': 'Usage',
    'resources.cost': 'Cost',
    'states.ready': 'Ready',
    'states.working': 'Working',
    'states.critical': 'Critical',
    'states.offline': 'Offline',
    'states.stale': 'Stale',
    'actions.open': 'Open',
    'actions.retry': 'Retry safely',
    'actions.returnClassic': 'Return to Classic',
    'errors.AUTH_REQUIRED': 'Authorization is required for this action.',
    'errors.STALE_REVISION': 'This view is out of date. Refresh before trying again.',
    'errors.REMOTE_QUARANTINED': 'The remote result was quarantined and was not executed.',
    'errors.UNKNOWN': 'The action could not be completed. Check the status and try again.',
    'errors.count': '{{count}} item(s)',
  },
  ru: {
    'resources.balance': 'Баланс',
    'resources.usage': 'Использование',
    'resources.cost': 'Стоимость',
    'states.ready': 'Готово',
    'states.working': 'Выполняется',
    'states.critical': 'Критическое состояние',
    'states.offline': 'Не в сети',
    'states.stale': 'Устарело',
    'actions.open': 'Открыть',
    'actions.retry': 'Повторить безопасно',
    'actions.returnClassic': 'Вернуться в Classic',
    'errors.AUTH_REQUIRED': 'Для этого действия требуется авторизация.',
    'errors.STALE_REVISION': 'Представление устарело. Обновите его перед повторной попыткой.',
    'errors.REMOTE_QUARANTINED': 'Удалённый результат помещён в карантин и не был выполнен.',
    'errors.UNKNOWN': 'Действие не выполнено. Проверьте статус и повторите попытку.',
    'errors.count': '{{count}} объект(ов)',
  },
} as const satisfies Record<SpatialLocale, Record<string, string>>

export type SpatialCatalogKey = keyof typeof SPATIAL_CATALOG.en

function interpolate(template: string, variables: Record<string, string | number> | undefined): string {
  if (!variables) return template
  return template.replace(/\{\{(\w+)\}\}/g, (match, key: string) => key in variables ? String(variables[key]) : match)
}

export function translateSpatial(locale: SpatialLocale, key: SpatialCatalogKey, variables?: Record<string, string | number>): string {
  const catalog = SPATIAL_CATALOG[locale] ?? SPATIAL_CATALOG.en
  return interpolate(catalog[key] ?? SPATIAL_CATALOG.en[key], variables)
}

export function translateSpatialCount(locale: SpatialLocale, count: number): string {
  const normalized = Math.max(0, Math.trunc(count))
  if (locale === 'ru') {
    const remainder10 = normalized % 10
    const remainder100 = normalized % 100
    const noun = remainder10 === 1 && remainder100 !== 11 ? 'объект' : remainder10 >= 2 && remainder10 <= 4 && (remainder100 < 10 || remainder100 >= 20) ? 'объекта' : 'объектов'
    return `${normalized} ${noun}`
  }
  return `${normalized} ${normalized === 1 ? 'item' : 'items'}`
}

/** Q is a protocol quantity; never run it through currency formatting. */
export function formatSpatialQuantity(qAtoms: string | number): string {
  const raw = String(qAtoms).trim()
  if (!/^-?\d+$/.test(raw)) throw new Error('q_atoms must be an integer string')
  return `${raw} Q`
}

export function formatSpatialTimestamp(value: string | Date, locale: SpatialLocale = 'en', timeZone = 'UTC'): string {
  const date = value instanceof Date ? value : new Date(value)
  if (!Number.isFinite(date.getTime())) throw new Error('timestamp must be parseable')
  return new Intl.DateTimeFormat(spatialLocaleLanguageTag(locale), {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone,
  }).format(date)
}

export type SpatialLocalizedError = {
  code: string
  message: string
}

export function localizeSpatialError(locale: SpatialLocale, code: string): SpatialLocalizedError {
  const key = `errors.${code}` as SpatialCatalogKey
  const message = key in SPATIAL_CATALOG.en ? translateSpatial(locale, key) : translateSpatial(locale, 'errors.UNKNOWN')
  return { code, message }
}

export const SPATIAL_PROTOCOL_TERMS = ['Workspace', 'Primary Agent', 'MCP', 'Hook', 'Node', 'Classic', 'Spatial', 'Q'] as const

/** Protocol terms stay stable across catalogs; only surrounding copy is translated. */
export function assertProtocolTermNotMachineTranslated(term: string): string {
  const trimmed = term.trim()
  if (!SPATIAL_PROTOCOL_TERMS.includes(trimmed as (typeof SPATIAL_PROTOCOL_TERMS)[number])) {
    throw new Error(`protocol term must remain canonical: ${trimmed}`)
  }
  return trimmed
}
