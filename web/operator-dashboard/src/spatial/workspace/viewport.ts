import { useEffect, useState, type RefObject } from 'react'

export type SpatialViewportOrientation = 'portrait' | 'landscape'

export type SpatialViewport = {
  width: number
  height: number
  dpr: number
  orientation: SpatialViewportOrientation
  revision: number
}

function viewportDimension(value: number | undefined, fallback: number): number {
  return Math.max(0, Math.round(value ?? fallback))
}

export function readSpatialViewport(
  element?: HTMLElement | null,
  dimensions?: { width?: number; height?: number },
): Omit<SpatialViewport, 'revision'> {
  const elementWidth = element?.clientWidth || undefined
  const elementHeight = element?.clientHeight || undefined
  const width = viewportDimension(
    dimensions?.width ?? elementWidth,
    typeof window === 'undefined' ? 0 : window.innerWidth,
  )
  const height = viewportDimension(
    dimensions?.height ?? elementHeight,
    typeof window === 'undefined' ? 0 : window.innerHeight,
  )
  const devicePixelRatio = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1
  const dprCap = width < 768 ? 1.25 : 1.5

  return {
    width,
    height,
    dpr: Math.min(Math.max(1, devicePixelRatio), dprCap),
    orientation: width > height ? 'landscape' : 'portrait',
  }
}

function isSameViewport(left: SpatialViewport, right: Omit<SpatialViewport, 'revision'>): boolean {
  return left.width === right.width
    && left.height === right.height
    && left.dpr === right.dpr
    && left.orientation === right.orientation
}

export function useSpatialViewport(elementRef: RefObject<HTMLElement | null>): SpatialViewport {
  const [viewport, setViewport] = useState<SpatialViewport>(() => ({
    ...readSpatialViewport(elementRef.current),
    revision: 0,
  }))

  useEffect(() => {
    const element = elementRef.current
    const update = (dimensions?: { width?: number; height?: number }) => {
      const next = readSpatialViewport(element, dimensions)
      setViewport((current) => isSameViewport(current, next)
        ? current
        : { ...next, revision: current.revision + 1 })
    }

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      update(rect && rect.width > 0 && rect.height > 0 ? { width: rect.width, height: rect.height } : undefined)
    })
    if (element) observer?.observe(element)

    const handleResize = () => update()
    const handleOrientationChange = () => update()
    window.addEventListener('resize', handleResize)
    window.addEventListener('orientationchange', handleOrientationChange)
    update()

    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('orientationchange', handleOrientationChange)
    }
  }, [elementRef])

  return viewport
}
