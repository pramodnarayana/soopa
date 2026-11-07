import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      thresholds: {
        lines: 78,
        functions: 72,
        branches: 68,
        statements: 78,
        'src/domain/**/*.ts': {
          lines: 90,
          functions: 90,
          branches: 80,
          statements: 90,
        },
        'src/adapters/**/*.ts': {
          lines: 90,
          functions: 90,
          branches: 80,
          statements: 90,
        },
        'src/application/**/*.ts': {
          lines: 85,
          functions: 80,
          branches: 75,
          statements: 85,
        },
        'src/provider/**/*.{ts,tsx}': {
          lines: 85,
          functions: 75,
          branches: 70,
          statements: 85,
        },
      },
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/__tests__/**',
        'src/testing/**',
        'src/**/index.ts',
        'src/ports/**',
        'src/domain/catalog.ts',
        'src/domain/connection.ts',
        'src/domain/stitch.ts',
        'src/domain/sync-run.ts',
        'src/domain/trace.ts',
        'src/domain/transformation.ts',
        'src/presentation/**/*Modal*.tsx',
        'src/presentation/shared/CommandPalette.tsx',
      ],
    },
  },
});
