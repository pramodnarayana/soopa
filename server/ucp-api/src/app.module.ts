import { Module } from '@nestjs/common';
import { DatabaseModule } from './infrastructure/database.module';
import { TenantsController } from './adapters/inbound/http/tenants.controller';
import { ApiKeysController } from './adapters/inbound/http/api-keys.controller';
import { ProvisionTenantUseCase } from './application/use-cases/provision-tenant.use-case';
import { GenerateApiKeyUseCase } from './application/use-cases/generate-api-key.use-case';
import { TENANT_REPOSITORY } from './ports/outbound/tenant.repository';
import { API_KEY_REPOSITORY } from './ports/outbound/api-key.repository';
import { IDENTITY_PROVIDER } from './ports/outbound/identity.provider';
import { TenantDrizzleRepository } from './adapters/outbound/database/tenant.drizzle.repository';
import { ApiKeyDrizzleRepository } from './adapters/outbound/database/api-key.drizzle.repository';
import { ZitadelManagementAdapter } from './adapters/outbound/identity/zitadel.provider';
import { ScheduleModule } from '@nestjs/schedule';
import { OutboxSweeperService } from './application/services/outbox-sweeper.service';
import { OUTBOX_REPOSITORY } from './ports/outbound/outbox.repository';
import { OutboxDrizzleRepository } from './adapters/outbound/database/outbox.drizzle.repository';
import { MESSAGE_BUS } from './ports/outbound/message.bus';
import { SqsMessageBusAdapter } from './adapters/outbound/messaging/sqs.message.bus';

@Module({
  imports: [DatabaseModule, ScheduleModule.forRoot()],
  controllers: [TenantsController, ApiKeysController],
  providers: [
    ProvisionTenantUseCase,
    GenerateApiKeyUseCase,
    OutboxSweeperService,
    {
      provide: TENANT_REPOSITORY,
      useClass: TenantDrizzleRepository,
    },
    {
      provide: API_KEY_REPOSITORY,
      useClass: ApiKeyDrizzleRepository,
    },
    {
      provide: IDENTITY_PROVIDER,
      useClass: ZitadelManagementAdapter,
    },
    {
      provide: OUTBOX_REPOSITORY,
      useClass: OutboxDrizzleRepository,
    },
    {
      provide: MESSAGE_BUS,
      useClass: SqsMessageBusAdapter,
    },
  ],
})
export class AppModule {}
