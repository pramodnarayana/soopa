module.exports = {
  apps: [
    {
      name: 'notification-engine',
      script: 'server/notification_engine/dist/index.js',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '512M',
    },
    {
      name: 'scheduler-engine',
      script: 'server/scheduler_engine/dist/index.js',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '512M',
    },
    {
      name: 'unified-api',
      script: 'uv',
      args: 'run uvicorn unified_api.main:app --port 5000',
      cwd: 'core/platform/apps/unified-api',
      instances: 1,
      autorestart: true,
      watch: false,
    },
    {
      name: 'platform-dashboard',
      script: 'node_modules/vite/bin/vite.js',
      args: '',
      cwd: 'apps/platform-dashboard',
      instances: 1,
      autorestart: true,
      watch: false,
    },
  ],
};
