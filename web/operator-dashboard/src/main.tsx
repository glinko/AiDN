import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from '@/App'
import { OperatorProviders } from '@/app/operator-providers'
import { SpatialRouteBoundary } from '@/spatial/route-boundary'
import '@/index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <OperatorProviders>
      <SpatialRouteBoundary classic={<App />} />
    </OperatorProviders>
  </StrictMode>,
)
