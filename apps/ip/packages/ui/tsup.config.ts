import { defineConfig } from 'tsup';

export default defineConfig({
  entry: ['src/index.ts'],
  format: ['cjs', 'esm'],
  dts: true,
  splitting: true,
  sourcemap: true,
  external: ['react', 'react-dom', '@soopa/ui', '@tanstack/react-query', '@tanstack/react-router'],
  esbuildOptions(options) {
    options.banner = {
      js: '"use client";',
    };
  },
});
