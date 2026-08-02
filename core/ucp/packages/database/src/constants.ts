export const JobStatus = {
  PENDING: 'PENDING',
  RUNNING: 'RUNNING',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED',
} as const;

export const NotificationChannel = {
  EMAIL: 'EMAIL',
  SLACK: 'SLACK',
  IN_APP: 'IN_APP',
} as const;

export const DefaultTenants = {
  SOOPA_PLATFORM: 'ten_000000000000000000000000', // True Enterprise Canonical Master Tenant ID
} as const;

export const EventTypes = {
  EDI_PROCESSING_FAILED: 'EDI_PROCESSING_FAILED',
  TEST: 'test',
} as const;

export const UserRoles = {
  ADMIN: 'admin',
  MEMBER: 'member',
} as const;
