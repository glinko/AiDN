import { Component, type ErrorInfo, type ReactNode } from 'react'

export type SpatialRendererErrorBoundaryProps = {
  children: ReactNode
  fallback?: ReactNode
  onError?: (error: Error, errorInfo: ErrorInfo) => void
}

type SpatialRendererErrorBoundaryState = {
  error: Error | null
}

/**
 * Keeps renderer failures inside the Spatial surface. The fallback remains a
 * DOM tree so an operator can recover without a working WebGL context.
 */
export class SpatialRendererErrorBoundary extends Component<
  SpatialRendererErrorBoundaryProps,
  SpatialRendererErrorBoundaryState
> {
  state: SpatialRendererErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): SpatialRendererErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.props.onError?.(error, errorInfo)
  }

  render() {
    if (this.state.error) {
      return this.props.fallback ?? (
        <div role="alert" data-spatial-renderer-state="error">
          Spatial renderer unavailable. Continue with the DOM fallback.
        </div>
      )
    }

    return this.props.children
  }
}
