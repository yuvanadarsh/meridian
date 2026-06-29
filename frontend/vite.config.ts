import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  appType: 'spa',
  server: {
    host: true,
    port: 5173,
  },
  optimizeDeps: {
    include: ['react-force-graph-2d', 'force-graph', 'd3-force-3d'],
  },
})
