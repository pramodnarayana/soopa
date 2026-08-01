/* eslint-disable */
import {
  Body,
  Controller,
  Delete,
  Get,
  Inject,
  NotFoundException,
  Post,
  UseGuards,
  Param,
} from '@nestjs/common';
import { UcpTenantId } from './decorators/ucp-tenant-id.decorator.js';
import type { DbClient } from '@soopa/database';
import { apps, appSubscriptions, tenants } from '@soopa/database';
import { IsNotEmpty, IsString } from 'class-validator';
import { and, eq } from 'drizzle-orm';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import type { IProjectProvider } from '../../../ports/outbound/project.provider.js';
import { PROJECT_PROVIDER } from '../../../ports/outbound/project.provider.js';
import { SubscribeAppUseCase } from '../../../application/use-cases/subscribe-app.use-case.js';
import { UnsubscribeAppUseCase } from '../../../application/use-cases/unsubscribe-app.use-case.js';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';

export class SubscribeDto {
  @IsString()
  @IsNotEmpty()
  appId!: string;
}

@Controller('tenants/:tenantId/subscriptions')
@UseGuards(TenantAuthGuard)
export class SubscriptionsController {
  constructor(
    @Inject(DATABASE_CLIENT) private readonly db: DbClient,
    @Inject(PROJECT_PROVIDER)
    private readonly projectProvider: IProjectProvider,
    private readonly subscribeAppUseCase: SubscribeAppUseCase,
    private readonly unsubscribeAppUseCase: UnsubscribeAppUseCase,
  ) {}

  @Get()
  async getSubscriptions(@UcpTenantId() tenantId: string) {
    const subscriptions = await this.db
      .select()
      .from(appSubscriptions)
      .where(eq(appSubscriptions.tenantId, tenantId));
    return subscriptions;
  }

  @Post()
  async subscribe(@UcpTenantId() tenantId: string, @Body() dto: SubscribeDto) {
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

    // Enterprise Grade - Delegate to UseCase to handle Domain Events and Outbox
    await this.subscribeAppUseCase.execute(tenantId, { appSlug: app.slug });

    // Enterprise Grade B2B Project Grant Wiring
    let zitadelProjectId: string | undefined;
    if (app.slug === 'edi') {
      zitadelProjectId = process.env.ZITADEL_EDI_PROJECT_ID;
    }

    if (zitadelProjectId && tenant.idpTenantId) {
      // Create B2B project grant in Zitadel. (No specific roles granted for now)
      await this.projectProvider.createProjectGrant(
        tenant.idpTenantId,
        zitadelProjectId,
        [],
      );
    }

    return { success: true };
  }

  @Delete(':appId')
  async unsubscribe(
    @UcpTenantId() tenantId: string,
    @Param('appId') appId: string,
  ) {
    // Fetch the app and tenant to determine if we need to revoke Zitadel grant
    const appRecords = await this.db
      .select()
      .from(apps)
      .where(eq(apps.id, appId))
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

    // Revoke the project grant for EDI app
    if (app.slug === 'edi' && tenant.idpTenantId) {
      const zitadelProjectId = process.env.ZITADEL_EDI_PROJECT_ID;
      if (zitadelProjectId) {
        try {
          await this.projectProvider.deleteProjectGrant(
            tenant.idpTenantId,
            zitadelProjectId,
          );
        } catch (err) {
          // Log the error but continue with database deletion
          console.error(
            `Warning: Failed to revoke project grant for tenant ${tenantId}`,
            err,
          );
        }
      }
    }

    // Enterprise Grade - Delegate to UseCase to handle Domain Events and Outbox
    await this.unsubscribeAppUseCase.execute(tenantId, app.slug);

    // Note: The appSubscriptions db record is automatically deleted by TenantRepository.save()
    // when we splice the slug from tenant.subscriptions!

    return { success: true };
  }
}
