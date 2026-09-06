import { useEffect, useRef, useState } from 'react'

import { isSpatialDocumentVisible } from './environment'

export type SpatialPerformanceMetrics = {
  fps: number
  averageFrameTimeMs: number
  pointerLatencyMs: number
  idleCpuActivity: 'bounded' | 'paused' | 'unknown'
  memoryMb: number | null
  sampleCount: number
}

export type SpatialPerformanceCheck = {
  id: 'fps' | 'frame-time' | 'pointer-latency' | 'idle-activity'
  label: string
  pass: boolean
  value: string
}

export type SpatialPerformanceGate = {
  status: 'pass' | 'needs-attention'
  checks: readonly SpatialPerformanceCheck[]
}

export const SPATIAL_PERFORMANCE_BUDGET = {
  targetFps: 55,
  maxFrameTimeMs: 16.7,
  maxPointerLatencyMs: 100,
} as const

export const initialSpatialPerformanceMetrics: SpatialPerformanceMetrics = {
  fps: 60,
  averageFrameTimeMs: 16.2,
  pointerLatencyMs: 0,
  idleCpuActivity: 'paused',
  memoryMb: null,
  sampleCount: 0,
}

export function evaluateSpatialPerformanceGate(metrics: SpatialPerformanceMetrics): SpatialPerformanceGate {
  const checks: SpatialPerformanceCheck[] = [
    { id: 'fps', label: 'Desktop FPS baseline', pass: metrics.fps >= SPATIAL_PERFORMANCE_BUDGET.targetFps, value: `${metrics.fps.toFixed(0)} FPS` },
    { id: 'frame-time', label: 'Average frame time', pass: metrics.averageFrameTimeMs <= SPATIAL_PERFORMANCE_BUDGET.maxFrameTimeMs, value: `${metrics.averageFrameTimeMs.toFixed(1)} ms` },
    { id: 'pointer-latency', label: 'Pointer/focus response', pass: metrics.pointerLatencyMs <= SPATIAL_PERFORMANCE_BUDGET.maxPointerLatencyMs, value: `${metrics.pointerLatencyMs.toFixed(0)} ms` },
    { id: 'idle-activity', label: 'Idle activity when hidden', pass: metrics.idleCpuActivity === 'paused' || metrics.idleCpuActivity === 'bounded', value: metrics.idleCpuActivity },
  ]

  return { status: checks.every((check) => check.pass) ? 'pass' : 'needs-attention', checks }
}

export function updateSpatialPerformanceFrame(
  metrics: SpatialPerformanceMetrics,
  frameTimeMs: number,
  visible: boolean,
): SpatialPerformanceMetrics {
  if (!visible) return { ...metrics, idleCpuActivity: 'paused' }
  const sampleCount = metrics.sampleCount + 1
  const averageFrameTimeMs = metrics.sampleCount === 0
    ? frameTimeMs
    : (metrics.averageFrameTimeMs * metrics.sampleCount + frameTimeMs) / sampleCount
  return {
    ...metrics,
    fps: averageFrameTimeMs > 0 ? 1000 / averageFrameTimeMs : 0,
    averageFrameTimeMs,
    idleCpuActivity: 'bounded',
    sampleCount,
  }
}

export function recordSpatialPointerLatency(metrics: SpatialPerformanceMetrics, latencyMs: number): SpatialPerformanceMetrics {
  return { ...metrics, pointerLatencyMs: Math.max(0, latencyMs) }
}

function readMemoryMb(): number | null {
  if (typeof performance === 'undefined') return null
  const memory = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory
  return memory ? Math.round(memory.usedJSHeapSize / 1024 / 1024) : null
}

/**
 * Samples a bounded window only while the document is visible. The canvas
 * remains demand-driven; this probe never becomes a permanent animation loop.
 */
export function useSpatialPerformanceProbe(enabled: boolean): [SpatialPerformanceMetrics, (startedAt?: number) => void] {
  const [metrics, setMetrics] = useState(initialSpatialPerformanceMetrics)
  const interactionStartRef = useRef<number | null>(null)

  useEffect(() => {
    if (!enabled) return undefined

    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') return undefined

    let frame = 0
    let previous = performance.now()
    let raf = 0
    let active = true
    const schedule = () => {
      if (!active || frame >= 24 || !isSpatialDocumentVisible()) return
      raf = window.requestAnimationFrame(sample)
    }
    const sample = (now: number) => {
      if (!active) return
      if (!isSpatialDocumentVisible()) {
        setMetrics((current) => updateSpatialPerformanceFrame(current, 0, false))
        return
      }
      setMetrics((current) => updateSpatialPerformanceFrame(current, Math.max(0, now - previous), true))
      frame += 1
      previous = now
      schedule()
    }

    schedule()
    const onVisibilityChange = () => {
      if (document.hidden) {
        window.cancelAnimationFrame(raf)
        setMetrics((current) => updateSpatialPerformanceFrame(current, 0, false))
        return
      }
      previous = performance.now()
      schedule()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      active = false
      window.cancelAnimationFrame(raf)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [enabled])

  useEffect(() => {
    if (metrics.sampleCount > 0 && metrics.memoryMb === null) {
      setMetrics((current) => ({ ...current, memoryMb: readMemoryMb() }))
    }
  }, [metrics.sampleCount, metrics.memoryMb])

  const markInteraction = (startedAt = interactionStartRef.current ?? performance.now()) => {
    interactionStartRef.current = null
    const latency = Math.max(0, performance.now() - startedAt)
    setMetrics((current) => recordSpatialPointerLatency(current, latency))
  }

  return [metrics, markInteraction]
}
