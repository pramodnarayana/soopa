import eslint from '@eslint/js';
import pluginRouter from '@tanstack/eslint-plugin-router';
import boundaries from 'eslint-plugin-boundaries';
import tailwind from 'eslint-plugin-tailwindcss';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'core/ucp/infra/zitadel/sync.ts'],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  ...tailwind.configs['flat/recommended'],
  {
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
          ],
        },
      ],
    },
  },

  {
    files: ['**/*.spec.ts', '**/*.test.ts', 'test/**'],
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
          message: 'Raw <button> tags are forbidden. Use <Button> from the design system.',
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
