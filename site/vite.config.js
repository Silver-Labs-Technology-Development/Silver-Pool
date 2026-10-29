/** @type {import('vite').UserConfig} */
import { resolve } from 'node:path'

const pages = {
  index: 'index.html',
  statistics: 'statistics/index.html',
  miners: 'miners/index.html',
  miner: 'miner/index.html',
  blocks: 'blocks/index.html',
  'getting-started': 'getting-started/index.html',
  pool: 'pool/index.html',
  'api-docs': 'api-docs/index.html',
  status: 'status/index.html',
  help: 'help/index.html',
}

export default {
  // Root-relative by default. Set SITE_BASE=/Silver-Pool/ when the site is
  // hosted under a repository subpath instead of a dedicated hostname.
  base: process.env.SITE_BASE || '/',
  root: '.',
  // Includes Cloudflare's _headers rules in the deployment output.
  publicDir: 'public',
  build: {
    outDir: '_site',
    emptyOutDir: true,
    rollupOptions: {
      input: Object.fromEntries(
        Object.entries(pages).map(([name, file]) => [name, resolve(process.cwd(), file)]),
      ),
      output: {
        assetFileNames: 'assets/[name]-[hash][extname]',
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
}
