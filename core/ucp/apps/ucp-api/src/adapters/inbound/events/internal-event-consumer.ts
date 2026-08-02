import { Inject, Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { ProcessControlPlaneOutboxEventUseCase } from '../../../application/use-cases/process-control-plane-outbox-event.use-case.js';
import {
  type IProjectProvider,
  PROJECT_PROVIDER,
} from '../../../ports/outbound/project.provider.js';

@Injectable()
export class InternalEventConsumer {
  private readonly logger = new Logger(InternalEventConsumer.name);

  constructor(
    private readonly outboxProcessor: ProcessControlPlaneOutboxEventUseCase,
    @Inject(PROJECT_PROVIDER)
    private readonly projectProvider: IProjectProvider,
  ) {}

  @OnEvent('outbox.event.created')
  async handleOutboxEvent(eventId: string) {
    this.logger.log(`[INTERNAL MESSAGE BUS] Consuming event ${eventId}...`);
    try {
      await this.outboxProcessor.execute(eventId);
    } catch (e) {
      this.logger.error(`[INTERNAL MESSAGE BUS] Failed to process event ${eventId}:`, e);
    }
  }

  @OnEvent('Idp.GrantProjectAccess')
  async handleGrantProjectAccess(event: {
    payload: { idpTenantId: string; projectId: string; roles: string[] };
  }) {
    this.logger.log(`Granting project access for tenant ${event.payload.idpTenantId}`);
    try {
      await this.projectProvider.createProjectGrant(
        event.payload.idpTenantId,
        event.payload.projectId,
        event.payload.roles || [],
      );
    } catch (e) {
      this.logger.error(
        `Failed to grant project access for tenant ${event.payload.idpTenantId}`,
        e,
      );
      throw e;
    }
  }

  @OnEvent('Idp.RevokeProjectAccess')
  async handleRevokeProjectAccess(event: { payload: { idpTenantId: string; projectId: string } }) {
    this.logger.log(`Revoking project access for tenant ${event.payload.idpTenantId}`);
    try {
      await this.projectProvider.deleteProjectGrant(
        event.payload.idpTenantId,
        event.payload.projectId,
      );
    } catch (e) {
      this.logger.error(`Revoke project access failed for tenant ${event.payload.idpTenantId}`, e);
      throw e;
    }
  }
}
