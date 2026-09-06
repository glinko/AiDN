export const SPATIAL_TOKEN_VERSION = 'spatial.tokens.v1' as const

export type SpatialContrastMode = 'standard' | 'high'
export type SpatialTransparencyMode = 'full' | 'reduced'

export const spatialTokens = {
  color: {
    background: {
      base: '#fbfcfe',
      soft: '#f6f8fb',
      raised: '#eef2f6',
    },
    surface: {
      glass: 'rgba(249, 251, 254, 0.68)',
      soft: 'rgba(250, 252, 255, 0.48)',
      strong: 'rgba(248, 250, 253, 0.82)',
      fallback: '#f3f6fa',
      border: 'rgba(255, 255, 255, 0.82)',
    },
    text: {
      primary: '#223553',
      secondary: '#4f607b',
      muted: '#5d6d83',
      onAccent: '#ffffff',
    },
    accent: {
      blue: '#3a5e97',
      blueSoft: '#dce8fb',
      violet: '#7777b7',
      cyan: '#4b829f',
      peach: '#9a694e',
    },
    state: {
      ready: '#2e7457',
      attention: '#81571f',
      critical: '#a44e5c',
      offline: '#56677d',
    },
  },
  opacity: {
    glass: '0.68',
    soft: '0.48',
    strong: '0.82',
    highlight: '0.92',
    disabled: '0.58',
  },
  shadow: {
    float: '0 24px 60px rgba(70, 88, 115, 0.09), 0 8px 24px rgba(70, 88, 115, 0.055)',
    soft: '0 10px 28px rgba(73, 92, 120, 0.07), 0 2px 8px rgba(73, 92, 120, 0.035)',
    neumorphic: '10px 10px 24px rgba(167, 177, 194, 0.12), -10px -10px 24px rgba(255, 255, 255, 0.92)',
    inset: 'inset 4px 4px 12px rgba(158, 170, 189, 0.10), inset -4px -4px 12px rgba(255, 255, 255, 0.88)',
  },
  radius: {
    small: '12px',
    medium: '18px',
    large: '28px',
    extraLarge: '36px',
    pill: '999px',
  },
  blur: {
    small: '10px',
    medium: '18px',
    large: '26px',
  },
  spacing: {
    one: '4px',
    two: '8px',
    three: '12px',
    four: '16px',
    five: '20px',
    six: '24px',
    eight: '32px',
  },
  typography: {
    sans: "'Manrope Variable', 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif",
    mono: "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    displaySize: 'clamp(2rem, 4vw, 3.5rem)',
    displayWeight: '760',
    bodySize: '0.9375rem',
    bodyLineHeight: '1.55',
    labelSize: '0.6875rem',
    labelTracking: '0.11em',
  },
  motion: {
    ease: 'cubic-bezier(0.22, 0.8, 0.25, 1)',
    fast: '160ms',
    normal: '220ms',
    enter: '280ms',
  },
} as const

export type SpatialTokens = typeof spatialTokens

function channelToLinear(channel: number): number {
  const normalized = channel / 255
  return normalized <= 0.04045
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4
}

function hexToRgb(hex: string): [number, number, number] {
  const normalized = hex.replace('#', '')
  if (!/^[\da-f]{6}$/i.test(normalized)) throw new Error(`Expected a six-digit hex color, received ${hex}`)
  return [
    Number.parseInt(normalized.slice(0, 2), 16),
    Number.parseInt(normalized.slice(2, 4), 16),
    Number.parseInt(normalized.slice(4, 6), 16),
  ]
}

function relativeLuminance(hex: string): number {
  const [red, green, blue] = hexToRgb(hex).map(channelToLinear)
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

/** Return the WCAG 2 contrast ratio for two opaque hex colors. */
export function contrastRatio(foreground: string, background: string): number {
  const foregroundLuminance = relativeLuminance(foreground)
  const backgroundLuminance = relativeLuminance(background)
  const lighter = Math.max(foregroundLuminance, backgroundLuminance)
  const darker = Math.min(foregroundLuminance, backgroundLuminance)
  return (lighter + 0.05) / (darker + 0.05)
}

export type SpatialContrastSpecimen = {
  id: string
  label: string
  foreground: string
  background: string
  ratio: number
}

export const spatialContrastSpecimens: SpatialContrastSpecimen[] = [
  {
    id: 'primary',
    label: 'Primary text',
    foreground: spatialTokens.color.text.primary,
    background: spatialTokens.color.background.base,
    ratio: contrastRatio(spatialTokens.color.text.primary, spatialTokens.color.background.base),
  },
  {
    id: 'secondary',
    label: 'Secondary text',
    foreground: spatialTokens.color.text.secondary,
    background: spatialTokens.color.background.soft,
    ratio: contrastRatio(spatialTokens.color.text.secondary, spatialTokens.color.background.soft),
  },
  {
    id: 'muted',
    label: 'Muted text',
    foreground: spatialTokens.color.text.muted,
    background: spatialTokens.color.background.raised,
    ratio: contrastRatio(spatialTokens.color.text.muted, spatialTokens.color.background.raised),
  },
]
