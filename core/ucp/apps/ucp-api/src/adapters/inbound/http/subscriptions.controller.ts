import {
  Body,
  Controller,
  Delete,
  Get,
  Headers,
  Inject,
  NotFoundException,
  Param,
  Post,
  UseGuards,
} from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { createId } from '@paralleldrive/cuid2';
import type { DbClient } from '@soopa/database';
import { appSubscriptions, apps, controlPlaneOutbox, tenants } from '@soopa/database';
import { IsNotEmpty, IsString } from 'class-validator';
import { eq } from 'drizzle-orm';
import { SubscribeAppUseCase } from '../../../application/use-cases/subscribe-app.use-case.js';
import { UnsubscribeAppUseCase } from '../../../application/use-cases/unsubscribe-app.use-case.js';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import type { IProjectProvider } from '../../../ports/outbound/project.provider.js';
import { PROJECT_PROVIDER } from '../../../ports/outbound/project.provider.js';
import { UcpTenantId } from './decorators/ucp-tenant-id.decorator.js';
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
    private readonly eventEmitter: EventEmitter2,
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
  async subscribe(
    @UcpTenantId() tenantId: string,
    @Body() dto: SubscribeDto,
    @Headers('idempotency-key') idempotencyKey?: string,
  ) {
    const appRecords = await this.db.select().from(apps).where(eq(apps.id, dto.appId)).limit(1);
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
      if (!tenant.idpTenantId) {
        throw new NotFoundException('Tenant missing idpTenantId');
      }
      zitadelProjectId = process.env.ZITADEL_EDI_PROJECT_ID;
    }

    if (zitadelProjectId) {
      // Use outbox for retryable Zitadel syncing
      const eventId = createId();
      const finalIdempotencyKey = idempotencyKey
        ? `${idempotencyKey}_IdpGrant_${eventId}` // Scope it to this specific event so retries don't violate the DB unique constraint
        : `Idp.GrantProjectAccess:${tenantId}:${zitadelProjectId}:${eventId}`;

      await this.db.insert(controlPlaneOutbox).values({
        id: eventId,
        idempotencyKey: finalIdempotencyKey,
        tenantId: tenantId,
        eventType: 'Idp.GrantProjectAccess',
        payload: {
          idpTenantId: tenant.idpTenantId,
          projectId: zitadelProjectId,
          roles: [],
        },
        status: 'PENDING',
      });
      // Trigger the local outbox consumer
      this.eventEmitter.emit('outbox.event.created', eventId);
    }

    return { success: true };
  }

  @Delete(':appId')
  async unsubscribe(
    @UcpTenantId() tenantId: string,
    @Param('appId') appId: string,
    @Headers('idempotency-key') idempotencyKey?: string,
  ) {
    // Fetch the app and tenant to determine if we need to revoke Zitadel grant
    const appRecords = await this.db.select().from(apps).where(eq(apps.id, appId)).limit(1);
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
    await this.unsubscribeAppUseCase.execute(tenantId, app.slug);

    // Revoke the project grant for EDI app
    if (app.slug === 'edi') {
      if (!tenant.idpTenantId) {
        throw new NotFoundException('Tenant missing idpTenantId');
      }
      const zitadelProjectId = process.env.ZITADEL_EDI_PROJECT_ID;
      if (zitadelProjectId) {
        // Use outbox for retryable Zitadel syncing
        const eventId = createId();
        const finalIdempotencyKey = idempotencyKey
          ? `${idempotencyKey}_IdpRevoke_${eventId}`
          : `Idp.RevokeProjectAccess:${tenantId}:${zitadelProjectId}:${eventId}`;

        await this.db.insert(controlPlaneOutbox).values({
          id: eventId,
          idempotencyKey: finalIdempotencyKey,
          tenantId: tenantId,
          eventType: 'Idp.RevokeProjectAccess',
          payload: {
            idpTenantId: tenant.idpTenantId,
            projectId: zitadelProjectId,
          },
          status: 'PENDING',
        });
        // Trigger the local outbox consumer
        this.eventEmitter.emit('outbox.event.created', eventId);
      }
    }

    // Note: The appSubscriptions db record is automatically deleted by TenantRepository.save()
    // when we splice the slug from tenant.subscriptions!

    return { success: true };
  }
}
