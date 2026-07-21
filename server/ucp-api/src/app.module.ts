import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DatabaseModule } from './infrastructure/database.module';
import { TenantsController } from './adapters/inbound/http/tenants.controller';
import { ApiKeysController } from './adapters/inbound/http/api-keys.controller';
import { ProvisionTenantUseCase } from './application/use-cases/provision-tenant.use-case';
import { GenerateApiKeyUseCase } from './application/use-cases/generate-api-key.use-case';
import { TENANT_REPOSITORY } from './ports/outbound/tenant.repository';
import { API_KEY_REPOSITORY } from './ports/outbound/api-key.repository';
import { ORGANIZATION_PROVIDER } from './ports/outbound/organization.provider';
import { USER_IDENTITY_PROVIDER } from './ports/outbound/user-identity.provider';
import { PROJECT_PROVIDER } from './ports/outbound/project.provider';
import { TenantDrizzleRepository } from './adapters/outbound/database/tenant.drizzle.repository';
import { ApiKeyDrizzleRepository } from './adapters/outbound/database/api-key.drizzle.repository';
import { ZitadelOrganizationsAdapter } from './adapters/outbound/identity/zitadel-organizations.adapter';
import { ZitadelUsersAdapter } from './adapters/outbound/identity/zitadel-users.adapter';
import { ZitadelProjectsAdapter } from './adapters/outbound/identity/zitadel-projects.adapter';
import { ScheduleModule } from '@nestjs/schedule';
import { OutboxSweeperService } from './application/services/outbox-sweeper.service';
import { OUTBOX_REPOSITORY } from './ports/outbound/outbox.repository';
import { USER_REPOSITORY } from './ports/outbound/user.repository';
import { UserDrizzleRepository } from './adapters/outbound/database/user.drizzle.repository';
import { OutboxDrizzleRepository } from './adapters/outbound/database/outbox.drizzle.repository';
import { MESSAGE_BUS } from './ports/outbound/message.bus';
import { SqsMessageBusAdapter } from './adapters/outbound/messaging/sqs.message.bus';
import { UsersController } from './adapters/inbound/http/users.controller';
import { ZitadelWebhookController } from './adapters/inbound/http/zitadel-webhook.controller';
import { AppsController } from './adapters/inbound/http/apps.controller';
import { SubscriptionsController } from './adapters/inbound/http/subscriptions.controller';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, envFilePath: '../../.env' }),
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
      useClass: SqsMessageBusAdapter,
    },
  ],
})
export class AppModule {}
