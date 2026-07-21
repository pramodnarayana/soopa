import { z } from 'zod';

const ZitadelRoleSchema = z.object({
  key: z.string(),
  displayName: z.string().optional(),
  group: z.string().optional(),
});
export type ZitadelRole = z.infer<typeof ZitadelRoleSchema>;

const ZitadelProjectGrantSchema = z.object({
  grantId: z.string().optional(),
  id: z.string().optional(),
  grantedOrgId: z.string().optional(),
  projectId: z.string().optional(),
  roleKeys: z.array(z.string()).optional(),
});

export const ZitadelUserSchema = z.object({
  userId: z.string().optional(),
  id: z.string().optional(),
  email: z.string().optional(),
  displayName: z.string().optional(),
  firstName: z.string().optional(),
  lastName: z.string().optional(),
  state: z.string().optional(),
  role: z.string().optional(),
  createdAt: z.string().optional(),
});
export type ZitadelUser = z.infer<typeof ZitadelUserSchema>;

const ZitadelRawUserSchema = z
  .object({
    id: z.string(),
    userName: z.string().optional(),
    state: z.string().optional(),
    human: z
      .object({
        email: z.object({ email: z.string().optional() }).optional(),
        profile: z
          .object({
            displayName: z.string().optional(),
            firstName: z.string().optional(),
            lastName: z.string().optional(),
          })
          .optional(),
      })
      .optional(),
    details: z.object({ creationDate: z.string().optional() }).optional(),
  })
  .passthrough();

export const ZitadelRawUserSearchResponseSchema = z.object({
  result: z.array(ZitadelRawUserSchema).optional().default([]),
});

const ZitadelSearchResponseSchema = <T extends z.ZodTypeAny>(itemSchema: T) =>
  z.object({
    details: z
      .object({
        totalResult: z.string().optional(),
        viewTimestamp: z.string().optional(),
      })
      .optional(),
    result: z.array(itemSchema).optional().default([]),
  });

export const ZitadelRolesResponseSchema =
  ZitadelSearchResponseSchema(ZitadelRoleSchema);
export const ZitadelProjectGrantsResponseSchema = ZitadelSearchResponseSchema(
  ZitadelProjectGrantSchema,
);
