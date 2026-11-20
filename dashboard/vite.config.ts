import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// base './' para que el build funcione desde cualquier ruta.
// En desarrollo, Vite (5173) reenvía /api a Uvicorn (8000).
export default defineConfig({
  base: './',
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
