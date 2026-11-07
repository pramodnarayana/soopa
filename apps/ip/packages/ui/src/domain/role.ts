export const IpUserRoleEnum = {
  SUPPORT: 'support',
  CUSTOMER: 'customer',
} as const;

export type IpUserRole = (typeof IpUserRoleEnum)[keyof typeof IpUserRoleEnum];
