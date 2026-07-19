module.exports = {
  apps: [
    {
      name: 'notification-engine',
      script: 'server/notification_engine/dist/index.js',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '512M'
    },
    {
      name: 'scheduler-engine',
      script: 'server/scheduler_engine/dist/index.js',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '512M'
    }
  ]
};
