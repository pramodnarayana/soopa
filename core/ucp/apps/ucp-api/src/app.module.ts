import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';
import * as path from 'path';
import { ApiKeysController } from './adapters/inbound/http/api-keys.controller.js';
import { AppsController } from './adapters/inbound/http/apps.controller.js';
import { SubscriptionsController } from './adapters/inbound/http/subscriptions.controller.js';
import { TenantsController } from './adapters/inbound/http/tenants.controller.js';
import { UsersController } from './adapters/inbound/http/users.controller.js';
import { ZitadelWebhookController } from './adapters/inbound/http/zitadel-webhook.controller.js';
import { ApiKeyDrizzleRepository } from './adapters/outbound/database/api-key.drizzle.repository.js';
import { OutboxDrizzleRepository } from './adapters/outbound/database/outbox.drizzle.repository.js';
import { TenantDrizzleRepository } from './adapters/outbound/database/tenant.drizzle.repository.js';
import { UserDrizzleRepository } from './adapters/outbound/database/user.drizzle.repository.js';
import { ZitadelOrganizationsAdapter } from './adapters/outbound/identity/zitadel-organizations.adapter.js';
import { ZitadelProjectsAdapter } from './adapters/outbound/identity/zitadel-projects.adapter.js';
import { ZitadelUsersAdapter } from './adapters/outbound/identity/zitadel-users.adapter.js';
import { SnsMessageBusAdapter } from './adapters/outbound/messaging/sns.message.bus.js';
import { DataPlaneReplicationService } from './application/services/data-plane-replication.service.js';
import { GenerateApiKeyUseCase } from './application/use-cases/generate-api-key.use-case.js';
import { ProvisionTenantUseCase } from './application/use-cases/provision-tenant.use-case.js';
import { DatabaseModule } from './infrastructure/database.module.js';
import { API_KEY_REPOSITORY } from './ports/outbound/api-key.repository.js';
import { MESSAGE_BUS } from './ports/outbound/message.bus.js';
import { ORGANIZATION_PROVIDER } from './ports/outbound/organization.provider.js';
import { OUTBOX_REPOSITORY } from './ports/outbound/outbox.repository.js';
import { PROJECT_PROVIDER } from './ports/outbound/project.provider.js';
import { TENANT_REPOSITORY } from './ports/outbound/tenant.repository.js';
import { USER_REPOSITORY } from './ports/outbound/user.repository.js';
import { USER_IDENTITY_PROVIDER } from './ports/outbound/user-identity.provider.js';
@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: [
        path.resolve(process.cwd(), '.env'),
        path.resolve(import.meta.dirname, '../../../.env'),
        path.resolve(process.cwd(), '../../.env'),
      ],
    }),
    DatabaseModule,
    ScheduleModule.forRoot(),
  ],
  controllers: [
    TenantsController,
    ApiKeysController,
    UsersController,
    ZitadelWebhookController,
    AppsController,
    SubscriptionsController,
  ],
  providers: [
    ProvisionTenantUseCase,
    GenerateApiKeyUseCase,
    DataPlaneReplicationService,
    {
      provide: TENANT_REPOSITORY,
      useClass: TenantDrizzleRepository,
    },
    {
      provide: API_KEY_REPOSITORY,
      useClass: ApiKeyDrizzleRepository,
    },
    {
      provide: ORGANIZATION_PROVIDER,
      useClass: ZitadelOrganizationsAdapter,
    },
    {
      provide: USER_IDENTITY_PROVIDER,
      useClass: ZitadelUsersAdapter,
    },
    {
      provide: PROJECT_PROVIDER,
      useClass: ZitadelProjectsAdapter,
    },
    {
      provide: USER_REPOSITORY,
      useClass: UserDrizzleRepository,
    },
    {
      provide: OUTBOX_REPOSITORY,
      useClass: OutboxDrizzleRepository,
    },
    {
      provide: MESSAGE_BUS,
      useClass: SnsMessageBusAdapter,
    },
  ],
})
export class AppModule {}
