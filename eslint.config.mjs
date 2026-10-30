import eslint from '@eslint/js';
import pluginRouter from '@tanstack/eslint-plugin-router';
import boundaries from 'eslint-plugin-boundaries';
import tailwind from 'eslint-plugin-tailwindcss';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const IP_UI_NON_TEST_RINGS = [
  { to: { element: { type: 'ip-ui-domain' } } },
  { to: { element: { type: 'ip-ui-ports' } } },
  { to: { element: { type: 'ip-ui-adapters' } } },
  { to: { element: { type: 'ip-ui-application' } } },
  { to: { element: { type: 'ip-ui-presentation' } } },
  { to: { element: { type: 'ip-ui-provider' } } },
];

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'core/ucp/infra/zitadel/sync.ts'],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  tailwind.configs.recommended,
  {
    settings: {
      tailwindcss: {
        cssConfigPath: `${import.meta.dirname}/core/ucp/apps/dashboard/src/index.css`,
      },
      'boundaries/elements': [
        { type: 'test-suite', pattern: '**/__tests__/**' },
        { type: 'platform-ui-testing', pattern: 'core/packages/ui/src/testing/**' },
        { type: 'ip-ui-testing', pattern: 'apps/ip/packages/ui/src/testing/**' },
        { type: 'ip-ui-domain', pattern: 'apps/ip/packages/ui/src/domain/**' },
        { type: 'ip-ui-ports', pattern: 'apps/ip/packages/ui/src/ports/**' },
        { type: 'ip-ui-adapters', pattern: 'apps/ip/packages/ui/src/adapters/**' },
        { type: 'ip-ui-application', pattern: 'apps/ip/packages/ui/src/application/**' },
        { type: 'ip-ui-presentation', pattern: 'apps/ip/packages/ui/src/presentation/**' },
        { type: 'ip-ui-provider', pattern: 'apps/ip/packages/ui/src/**' },
        { type: 'platform-ui', pattern: 'core/packages/ui/src/**' },
        { type: 'edi-ui', pattern: 'apps/edi/packages/ui/src/**' },
        { type: 'dashboard', pattern: 'core/ucp/apps/dashboard/src/**' },
      ],
    },
    plugins: {
      boundaries,
    },
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: [
            '*.js',
            '*.mjs',
            '*.cjs',
            '*.d.ts',
            'core/ucp/infra/zitadel/sync.ts',
          ],
        },
        tsconfigRootDir: import.meta.dirname,
      },
      globals: {
        ...globals.node,
      },
    },
    rules: {
      complexity: ['error', 10],
      'tailwindcss/no-arbitrary-value': 'error',
      'tailwindcss/no-custom-classname': 'error',
      'boundaries/dependencies': [
        'error',
        {
          default: 'disallow',
          policies: [
            {
              from: { element: { type: 'test-suite' } },
              allow: [
                { to: { element: { type: 'test-suite' } } },
                { to: { element: { type: 'platform-ui-testing' } } },
                { to: { element: { type: 'ip-ui-testing' } } },
                { to: { element: { type: 'platform-ui' } } },
                { to: { element: { type: 'edi-ui' } } },
                ...IP_UI_NON_TEST_RINGS,
                { to: { element: { type: 'dashboard' } } },
              ],
            },
            {
              from: { element: { type: 'platform-ui-testing' } },
              allow: [
                { to: { element: { type: 'platform-ui-testing' } } },
                { to: { element: { type: 'platform-ui' } } },
              ],
            },
            {
              from: { element: { type: 'ip-ui-testing' } },
              allow: [
                { to: { element: { type: 'ip-ui-testing' } } },
                { to: { element: { type: 'platform-ui-testing' } } },
                ...IP_UI_NON_TEST_RINGS,
                { to: { element: { type: 'platform-ui' } } },
              ],
            },
            {
              from: { element: { type: 'ip-ui-domain' } },
              allow: [{ to: { element: { type: 'ip-ui-domain' } } }],
            },
            {
              from: { element: { type: 'ip-ui-ports' } },
              allow: [
                { to: { element: { type: 'ip-ui-ports' } } },
                { to: { element: { type: 'ip-ui-domain' } } },
                { to: { element: { type: 'platform-ui' } } },
              ],
            },
            {
              from: { element: { type: 'ip-ui-adapters' } },
              allow: [
                { to: { element: { type: 'ip-ui-adapters' } } },
                { to: { element: { type: 'ip-ui-ports' } } },
                { to: { element: { type: 'ip-ui-domain' } } },
                { to: { element: { type: 'platform-ui' } } },
              ],
            },
            {
              from: { element: { type: 'ip-ui-application' } },
              allow: [
                { to: { element: { type: 'ip-ui-application' } } },
                { to: { element: { type: 'ip-ui-ports' } } },
                { to: { element: { type: 'ip-ui-domain' } } },
                { to: { element: { type: 'ip-ui-provider' } } },
                { to: { element: { type: 'platform-ui' } } },
              ],
            },
            {
              from: { element: { type: 'ip-ui-presentation' } },
              allow: [
                { to: { element: { type: 'ip-ui-presentation' } } },
                { to: { element: { type: 'ip-ui-application' } } },
                { to: { element: { type: 'ip-ui-ports' } } },
                { to: { element: { type: 'ip-ui-domain' } } },
                { to: { element: { type: 'ip-ui-provider' } } },
                { to: { element: { type: 'platform-ui' } } },
              ],
            },
            {
              from: { element: { type: 'ip-ui-provider' } },
              allow: [...IP_UI_NON_TEST_RINGS, { to: { element: { type: 'platform-ui' } } }],
            },
            {
              from: { element: { type: 'platform-ui' } },
              allow: [{ to: { element: { type: 'platform-ui' } } }],
            },
            {
              from: { element: { type: 'edi-ui' } },
              allow: [
                { to: { element: { type: 'edi-ui' } } },
                { to: { element: { type: 'platform-ui' } } },
              ],
            },
            {
              from: { element: { type: 'dashboard' } },
              allow: [
                { to: { element: { type: 'dashboard' } } },
                { to: { element: { type: 'platform-ui' } } },
                { to: { element: { type: 'edi-ui' } } },
                { to: { element: { type: 'ip-ui-provider' } } },
                { to: { element: { type: 'ip-ui-presentation' } } },
                { to: { element: { type: 'ip-ui-application' } } },
                { to: { element: { type: 'ip-ui-ports' } } },
                { to: { element: { type: 'ip-ui-domain' } } },
              ],
            },
          ],
        },
      ],
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/explicit-function-return-type': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/require-await': 'off',
      '@typescript-eslint/restrict-template-expressions': 'off',
      '@typescript-eslint/no-misused-promises': [
        'error',
        {
          checksVoidReturn: {
            attributes: false,
          },
        },
      ],
    },
  },
  {
    ignores: [
      '**/dist/**',
      '**/node_modules/**',
      '**/vitest.config.ts',
      'vitest.workspace.ts',
      '**/eslint.config.mjs',
      'eslint.config.mjs',
      'ecosystem.config.cjs',
      '**/drizzle.config.ts',
      '**/coverage/**',
      '**/.venv/**',
      '**/postcss.config.js',
      '**/tailwind.config.js',
      '**/generated/**/*.d.ts',
      '**/*.js',
      '**/*.mjs',
      '**/*.cjs',
      '**/*.d.ts',
    ],
  },
  {
    files: ['**/*.js', '**/*.mjs', '**/*.cjs'],
    ...tseslint.configs.disableTypeChecked,
  },
  {
    files: ['apps/edi/packages/ui/src/**/*.ts', 'apps/edi/packages/ui/src/**/*.tsx'],
    plugins: {
      '@tanstack/router': pluginRouter,
    },
    rules: {
      ...pluginRouter.configs.recommended.rules,
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/*'],
              message:
                'Absolute imports (@/*) are forbidden inside shared UI packages to prevent Vite alias hijacking by host applications. Use relative imports instead.',
            },
            {
              group: ['@soopa/ip-ui', '@soopa/ip-ui/*', '**/apps/ip/**'],
              message:
                'Cross-bounded-context imports from @soopa/ip-ui into @soopa/edi-ui are strictly forbidden.',
            },
          ],
        },
      ],
    },
  },
  {
    files: [
      'apps/ip/packages/ui/src/**/*.ts',
      'apps/ip/packages/ui/src/**/*.tsx',
      'core/packages/ui/src/network/**/*.ts',
      'core/packages/ui/src/observability/**/*.ts',
      'core/packages/ui/src/testing/**/*.ts',
      'core/packages/ui/src/components/observability/**/*.ts',
      'core/packages/ui/src/components/observability/**/*.tsx',
    ],
    plugins: {
      '@tanstack/router': pluginRouter,
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/*'],
              message:
                'Absolute imports (@/*) are forbidden inside shared UI packages to prevent Vite alias hijacking by host applications. Use relative imports instead.',
            },
            {
              group: ['@soopa/edi-ui', '@soopa/edi-ui/*', '**/apps/edi/**'],
              message:
                'Cross-bounded-context imports from @soopa/edi-ui into @soopa/ip-ui or @soopa/ui are strictly forbidden.',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['**/*.spec.ts', '**/*.test.ts', '**/*.test.tsx', 'test/**'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
    },
  },
  {
    files: ['apps/**/*.tsx', 'core/**/*.tsx'],
    ignores: ['**/packages/ui/src/components/ui/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'JSXElement[openingElement.name.name="table"]',
          message: 'Raw <table> tags are forbidden. Use <DataTable> from the design system.',
        },
        {
          selector: 'JSXElement[openingElement.name.name="button"]',
          message:
            'Raw <button> tags are forbidden. Use <DataTable> or <Button> from the design system.',
        },
        {
          selector: 'JSXElement[openingElement.name.name="td"]',
          message: 'Raw <td> tags are forbidden. Use <DataTable> from the design system.',
        },
        {
          selector: 'JSXElement[openingElement.name.name="th"]',
          message: 'Raw <th> tags are forbidden. Use <DataTable> from the design system.',
        },
        {
          selector: 'JSXElement[openingElement.name.name="tr"]',
          message: 'Raw <tr> tags are forbidden. Use <DataTable> from the design system.',
        },
      ],
    },
  },
);
