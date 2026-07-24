import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      exclude: ['src/index.ts', 'dist/**', 'node_modules/**'],
      include: ['src/**/*.ts'],
    },
    exclude: ['dist/**', 'node_modules/**'],
    include: ['tests/**/*.ts'],
  },
});
