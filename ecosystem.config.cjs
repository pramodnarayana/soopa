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
      name: 'ucp-api',
      script: 'node_modules/@nestjs/cli/bin/nest.js',
      args: 'start --watch',
      cwd: 'server/ucp-api',
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
