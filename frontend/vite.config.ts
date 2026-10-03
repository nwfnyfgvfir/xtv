import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { execSync } from 'node:child_process'
import { fileURLToPath, URL } from 'node:url'

// App version shown in the UI. Priority:
//   1. APP_VERSION env  — injected by CI (git tag) / Docker build arg
//   2. git describe     — local dev, matches the nearest tag
//   3. "dev"            — no git, no env (e.g. plain `docker build`)
function resolveAppVersion(): string {
  const fromEnv = (process.env.APP_VERSION || '').trim()
  if (fromEnv) return fromEnv
  try {
    const out = execSync('git describe --tags --always', {
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
    if (out) return out
  } catch {
    // git unavailable — fall through
  }
  return 'dev'
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(resolveAppVersion()),
  },
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver({ importStyle: 'css' })],
      dts: 'src/auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver({ importStyle: 'css' })],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    // Do NOT force-split axios/vue/element-plus — causes circular ESM init
    // (TypeError: e is not a function → black screen). Route lazy-load is enough;
    // artplayer stays in the detail async chunk via dynamic import.
  },
})
