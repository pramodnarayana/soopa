import {
  Controller,
  Post,
  Body,
  Param,
  Inject,
  Get,
  NotFoundException,
  Delete,
} from '@nestjs/common';
import { DATABASE_CLIENT } from '../../../infrastructure/database.module';
import { tenantSubscriptions, apps, tenants } from '@soopa/database';
import type { DbClient } from '@soopa/database';
import { eq, and } from 'drizzle-orm';
import { IsString, IsNotEmpty } from 'class-validator';
import { PROJECT_PROVIDER } from '../../../ports/outbound/project.provider';
import type { IProjectProvider } from '../../../ports/outbound/project.provider';

export class SubscribeDto {
  @IsString()
  @IsNotEmpty()
  appId: string;
}

@Controller('tenants/:tenantId/subscriptions')
export class SubscriptionsController {
  constructor(
    @Inject(DATABASE_CLIENT) private readonly db: DbClient,
    @Inject(PROJECT_PROVIDER)
    private readonly projectProvider: IProjectProvider,
  ) {}

  @Get()
  async getSubscriptions(@Param('tenantId') tenantId: string) {
    const subscriptions = await this.db
      .select()
      .from(tenantSubscriptions)
      .where(eq(tenantSubscriptions.tenantId, tenantId));
    return subscriptions;
  }

  @Post()
  async subscribe(
    @Param('tenantId') tenantId: string,
    @Body() dto: SubscribeDto,
  ) {
    const appRecords = await this.db
      .select()
      .from(apps)
      .where(eq(apps.id, dto.appId))
      .limit(1);
    if (!appRecords.length) throw new NotFoundException('App not found');
    const app = appRecords[0];

    const tenantRecords = await this.db
      .select()
      .from(tenants)
      .where(eq(tenants.id, tenantId))
      .limit(1);
    if (!tenantRecords.length) throw new NotFoundException('Tenant not found');
    const tenant = tenantRecords[0];

    // Enterprise Grade B2B Project Grant Wiring
    let zitadelProjectId: string | undefined;
    if (app.slug === 'edi') {
      zitadelProjectId = process.env.ZITADEL_EDI_PROJECT_ID;
    }

    if (zitadelProjectId && tenant.zitadelOrgId) {
      // Create B2B project grant in Zitadel. (No specific roles granted for now)
      await this.projectProvider.createProjectGrant(
        tenant.zitadelOrgId,
        zitadelProjectId,
        [],
      );
    }

    // Basic implementation to insert or ignore if exists
    await this.db
      .insert(tenantSubscriptions)
      .values({
        tenantId,
        appId: dto.appId,
        tier: 'standard',
        status: 'active',
      })
      .onConflictDoNothing();

    return { success: true };
  }

  @Delete(':appId')
  async unsubscribe(
    @Param('tenantId') tenantId: string,
    @Param('appId') appId: string,
  ) {
    await this.db
      .delete(tenantSubscriptions)
      .where(
        and(
          eq(tenantSubscriptions.tenantId, tenantId),
          eq(tenantSubscriptions.appId, appId),
        ),
      );
    return { success: true };
  }
}
