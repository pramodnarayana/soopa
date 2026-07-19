export const JobStatus = {
  PENDING: 'PENDING',
  RUNNING: 'RUNNING',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED'
} as const;
export type JobStatusType = typeof JobStatus[keyof typeof JobStatus];

export const NotificationChannel = {
  EMAIL: 'EMAIL',
  SLACK: 'SLACK',
  IN_APP: 'IN_APP'
} as const;
export type NotificationChannelType = typeof NotificationChannel[keyof typeof NotificationChannel];

export const DefaultTenants = {
  SOOPA_PLATFORM: 'SOOPA_PLATFORM'
} as const;

export const EventTypes = {
  EDI_PROCESSING_FAILED: 'EDI_PROCESSING_FAILED',
  TEST: 'test'
} as const;

export const UserRoles = {
  ADMIN: 'admin',
  MEMBER: 'member'
} as const;
export type UserRoleType = typeof UserRoles[keyof typeof UserRoles];
