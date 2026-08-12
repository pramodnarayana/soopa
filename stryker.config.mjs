export default {
  $schema:
    'https://raw.githubusercontent.com/stryker-mutator/stryker-js/master/packages/api/schema/stryker-core.json',
  testRunner: 'vitest',
  reporters: ['html', 'clear-text', 'progress'],
  coverageAnalysis: 'perTest',
  vitest: {
    configFile: 'vitest.workspace.ts',
  },
  mutate: [
    'apps/edi/packages/ui/src/**/*.ts?(x)',
    'core/ucp/apps/dashboard/src/**/*.ts?(x)',
    '!**/*.test.ts?(x)',
    '!**/*.spec.ts?(x)',
    '!**/*.d.ts',
  ],
};
