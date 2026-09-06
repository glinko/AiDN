import { useState } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { SpatialThemeBoundary } from '@/spatial/theme/SpatialThemeBoundary'
import { SpatialTokenGallery } from '@/spatial/theme/SpatialTokenGallery'
import type { SpatialContrastMode, SpatialTransparencyMode } from '@/spatial/theme/tokens'
import { SpatialWorkspace } from '@/spatial/workspace'
import { MOCK_SPATIAL_SCOPE, mockSpatialEventStream, useSpatialWorkspaceData } from '@/spatial/data'

type SpatialRouteProps = {
  onReturn: () => void
}

const spatialRouteQueryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
})

function SpatialRouteSurface({ onReturn }: SpatialRouteProps) {
  const workspaceData = useSpatialWorkspaceData({ scope: MOCK_SPATIAL_SCOPE, mode: 'mock-real', eventStream: mockSpatialEventStream })
  return <SpatialWorkspace onReturn={onReturn} workspaceData={workspaceData} />
}

/**
 * The first real Spatial route module. It is intentionally loaded behind the
 * route boundary so Three.js never enters the Classic initial graph.
 */
export function SpatialRoute({ onReturn }: SpatialRouteProps) {
  const [contrast, setContrast] = useState<SpatialContrastMode>('standard')
  const [transparency, setTransparency] = useState<SpatialTransparencyMode>('full')

  return (
    <SpatialThemeBoundary contrast={contrast} transparency={transparency}>
      <QueryClientProvider client={spatialRouteQueryClient}>
        <SpatialRouteSurface onReturn={onReturn} />
      </QueryClientProvider>
      <SpatialTokenGallery
        contrast={contrast}
        transparency={transparency}
        onContrastChange={setContrast}
        onTransparencyChange={setTransparency}
        onReturn={onReturn}
      />
    </SpatialThemeBoundary>
  )
}
