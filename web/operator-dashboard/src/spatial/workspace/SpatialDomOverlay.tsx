import type { ComponentPropsWithoutRef, ReactNode } from 'react'

import { cn } from '@/lib/utils'

export type SpatialDomOverlayProps = ComponentPropsWithoutRef<'div'>

export function SpatialDomOverlay({ className, ...props }: SpatialDomOverlayProps) {
  return (
    <div
      data-spatial-layer="dom-overlay"
      className={cn('aidn-spatial-dom-overlay', className)}
      {...props}
    />
  )
}

export type SpatialInteractiveProps = ComponentPropsWithoutRef<'div'> & {
  children?: ReactNode
}

export function SpatialInteractive({ className, ...props }: SpatialInteractiveProps) {
  return (
    <div
      data-interactive="true"
      className={cn('aidn-spatial-interactive', className)}
      {...props}
    />
  )
}
