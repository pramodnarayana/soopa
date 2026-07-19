module.exports = {
  apps: [
    {
      name: 'notification-engine',
      script: 'pnpm',
      args: '--filter @soopa/notification-engine start',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '512M'
    },
    {
      name: 'scheduler-engine',
      script: 'pnpm',
      args: '--filter @soopa/scheduler-engine start',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '512M'
    }
  ]
};
