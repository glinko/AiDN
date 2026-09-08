import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin, type ViteDevServer } from 'vite'

function offlineDashboardApiFixture(): Plugin {
  return {
    name: 'aidn-offline-dashboard-api-fixture',
    configureServer(server: ViteDevServer) {
      if (process.env.AIDN_E2E_OFFLINE_API !== '1') return
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?', 1)[0] ?? ''
        if (!path.startsWith('/operators/') || path.startsWith('/operators/dashboard/react/')) {
          next()
          return
        }
        response.statusCode = 503
        response.setHeader('Content-Type', 'application/json')
        response.end(JSON.stringify({ detail: 'offline dashboard fixture' }))
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  base: '/operators/dashboard/react/',
  plugins: [offlineDashboardApiFixture(), react(), tailwindcss()],
  build: {
    rolldownOptions: {
      input: {
        dashboard: fileURLToPath(new URL('./index.html', import.meta.url)),
        calibration: fileURLToPath(new URL('./spatial-calibration.html', import.meta.url)),
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '^/operators/(?!dashboard/react(?:/|$))': {
        target: process.env.AIDN_HYPERVISOR_URL ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
