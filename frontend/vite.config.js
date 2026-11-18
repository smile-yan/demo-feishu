import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    // 前端独立跑在 5173，/api 转发到 FastAPI。
    // 走代理后前后端同源，httpOnly cookie 天然可用。
    proxy: {
      '/api': {
        // 联调时改 8001 可指向 scripts/mock_server.py（假数据，无需扫码）
        target: process.env.API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
