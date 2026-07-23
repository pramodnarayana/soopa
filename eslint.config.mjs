import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';
import globals from 'globals';

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        project: 'tsconfig.eslint.json',
        tsconfigRootDir: import.meta.dirname,
      },
      globals: {
        ...globals.node,
      },
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/explicit-function-return-type': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/require-await': 'off',
      '@typescript-eslint/no-floating-promises': 'off',
      '@typescript-eslint/no-misused-promises': 'off',
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/restrict-template-expressions': 'off'
    },
  },
  {
    ignores: ['**/dist/**', '**/node_modules/**', '**/vitest.config.ts', 'vitest.workspace.ts', '**/eslint.config.mjs', 'eslint.config.mjs', 'ecosystem.config.cjs', '**/drizzle.config.ts', '**/coverage/**', '**/.venv/**', '**/postcss.config.js', '**/tailwind.config.js', '**/generated/**/*.d.ts'],
  },
  {
    files: ['**/*.spec.ts', '**/*.test.ts', 'test/**'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off'
    }
  }
);
