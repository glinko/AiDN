import type { ReactNode } from 'react'

import { SPATIAL_TOKEN_VERSION, type SpatialContrastMode, type SpatialTransparencyMode } from './tokens'
import './spatial-theme.css'

export type SpatialThemeBoundaryProps = {
  children: ReactNode
  contrast?: SpatialContrastMode
  transparency?: SpatialTransparencyMode
  className?: string
}

/**
 * Owns the Spatial visual boundary. Keeping the class and data attributes on
 * one wrapper prevents token variables from leaking into the Classic UI.
 */
export function SpatialThemeBoundary({
  children,
  contrast = 'standard',
  transparency = 'full',
  className,
}: SpatialThemeBoundaryProps) {
  const classes = ['aidn-spatial-theme', className].filter(Boolean).join(' ')

  return (
    <div
      className={classes}
      data-aidn-theme-version={SPATIAL_TOKEN_VERSION}
      data-aidn-contrast={contrast}
      data-aidn-transparency={transparency}
    >
      {children}
    </div>
  )
}

