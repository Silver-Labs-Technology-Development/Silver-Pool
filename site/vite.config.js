/** @type {import('vite').UserConfig} */
export default {
  base: '/Silver-Pool/',
  root: '.',
  publicDir: 'public',
  build: {
    outDir: '_site',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        assetFileNames: 'assets/[name]-[hash][extname]',
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
  server: {
    open: 'index.html',
  },
}
