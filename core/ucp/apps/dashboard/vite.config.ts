import fs from 'node:fs';
import path from 'node:path';
import { parseEnv } from 'node:util';
import tailwindcss from '@tailwindcss/vite';
import { TanStackRouterVite } from '@tanstack/router-vite-plugin';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const rootDir = path.resolve(__dirname, '../../../../');
  const envPath = path.resolve(rootDir, '.env');

  // Enterprise Pattern (Shopify Style): In local development, the root .env file on disk is the
  // authoritative Single Source of Truth. Stale terminal session exports (e.g. from direnv or
  // prior shell sessions) must NEVER override the freshly bootstrapped IdP configuration on disk.
  const diskEnv: Record<string, string> = {};
  if (fs.existsSync(envPath)) {
    const rawDisk = parseEnv(fs.readFileSync(envPath, 'utf-8'));
    for (const [key, value] of Object.entries(rawDisk)) {
      if (value !== undefined) {
        diskEnv[key] = value;
      }
    }
  }

  if (command === 'serve') {
    // Purge zombie environment variables from ambient shell memory that are not on disk
    for (const key of Object.keys(process.env)) {
      if ((key.startsWith('VITE_') || key.startsWith('IDENTITY_')) && !(key in diskEnv)) {
        delete process.env[key];
      }
    }
    // Synchronize process.env with authoritative disk values so Vite's internal loadEnv() aligns
    for (const [key, value] of Object.entries(diskEnv)) {
      if (key.startsWith('VITE_') || key.startsWith('IDENTITY_')) {
        process.env[key] = value;
      }
    }
  }

  const loadedEnv = loadEnv(mode, rootDir, ['VITE_', 'IDENTITY_']);
  const activeEnv = { ...loadedEnv, ...diskEnv };

  const proxyTarget = activeEnv.VITE_API_PROXY_TARGET || process.env.VITE_API_PROXY_TARGET;
  if (command === 'serve' && !proxyTarget) {
    throw new Error(
      'VITE_API_PROXY_TARGET environment variable is required for local development proxy.',
    );
  }

  const defines: Record<string, string> = {};
  if (command === 'serve') {
    for (const [key, value] of Object.entries(activeEnv)) {
      if (key.startsWith('VITE_') || key.startsWith('IDENTITY_')) {
        defines[`import.meta.env.${key}`] = JSON.stringify(value);
      }
    }
  }

  return {
    envDir: rootDir,
    envPrefix: ['VITE_', 'IDENTITY_'],
    define: defines,
    plugins: [TanStackRouterVite(), react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@soopa/ui': path.resolve(__dirname, '../../../packages/ui/src'),
        '@soopa/edi-ui': path.resolve(__dirname, '../../../../apps/edi/packages/ui/src'),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
