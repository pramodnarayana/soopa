import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      thresholds: {
        lines: 85,
        functions: 85,
        branches: 80,
        statements: 85,
      },
      include: [
        'src/network/**/*.ts',
        'src/observability/**/*.ts',
        'src/contexts/useProductTheme.ts',
        'src/components/observability/use-clipboard-copy.ts',
        'src/features/developers/api/apiTokenRepository.ts',
        'src/features/webhooks/api/webhookRepository.ts',
        'src/features/notifications/api/notificationRepository.ts',
        'src/features/notifications/api/notificationConfigRepository.ts',
      ],
      exclude: ['src/**/index.ts', 'src/**/ports.ts'],
    },
  },
});
