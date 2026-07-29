import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';
import * as path from 'path';
import { ApiKeysController } from './adapters/inbound/http/api-keys.controller.js';
import { ApiTokensController } from './adapters/inbound/http/api-tokens.controller.js';
import { AppsController } from './adapters/inbound/http/apps.controller.js';
import { ZitadelAuthService } from './adapters/inbound/http/auth/zitadel-auth.service.js';
import { PlatformAuthGuard } from './adapters/inbound/http/guards/platform-auth.guard.js';
import { TenantAuthGuard } from './adapters/inbound/http/guards/tenant-auth.guard.js';
import { PlatformProxyController } from './adapters/inbound/http/platform-proxy.controller.js';
import { SubscriptionsController } from './adapters/inbound/http/subscriptions.controller.js';
import { TenantProxyController } from './adapters/inbound/http/tenant-proxy.controller.js';
import { TenantsController } from './adapters/inbound/http/tenants.controller.js';
import { UsersController } from './adapters/inbound/http/users.controller.js';
import { WebhooksController } from './adapters/inbound/http/webhooks.controller.js';
import { ZitadelWebhookController } from './adapters/inbound/http/zitadel-webhook.controller.js';
import { ApiKeyDrizzleRepository } from './adapters/outbound/database/api-key.drizzle.repository.js';
import { ApiTokenDrizzleRepository } from './adapters/outbound/database/api-token.drizzle.repository.js';
import { OutboxDrizzleRepository } from './adapters/outbound/database/outbox.drizzle.repository.js';
import { TenantDrizzleRepository } from './adapters/outbound/database/tenant.drizzle.repository.js';
import { UserDrizzleRepository } from './adapters/outbound/database/user.drizzle.repository.js';
import { WebhookDrizzleRepository } from './adapters/outbound/database/webhook.drizzle.repository.js';
import { ZitadelOrganizationsAdapter } from './adapters/outbound/identity/zitadel-organizations.adapter.js';
import { ZitadelProjectsAdapter } from './adapters/outbound/identity/zitadel-projects.adapter.js';
import { ZitadelUsersAdapter } from './adapters/outbound/identity/zitadel-users.adapter.js';
import { SnsMessageBusAdapter } from './adapters/outbound/messaging/sns.message.bus.js';
import { DataPlaneReplicationService } from './application/services/data-plane-replication.service.js';
import { CreateWebhookUseCase } from './application/use-cases/create-webhook.use-case.js';
import { GenerateApiKeyUseCase } from './application/use-cases/generate-api-key.use-case.js';
import { GenerateApiTokenUseCase } from './application/use-cases/generate-api-token.use-case.js';
import { ProvisionTenantUseCase } from './application/use-cases/provision-tenant.use-case.js';
import { DatabaseModule } from './infrastructure/database.module.js';
import { API_KEY_REPOSITORY } from './ports/outbound/api-key.repository.js';
import { API_TOKEN_REPOSITORY } from './ports/outbound/api-token.repository.js';
import { MESSAGE_BUS } from './ports/outbound/message.bus.js';
import { ORGANIZATION_PROVIDER } from './ports/outbound/organization.provider.js';
import { OUTBOX_REPOSITORY } from './ports/outbound/outbox.repository.js';
import { PROJECT_PROVIDER } from './ports/outbound/project.provider.js';
import { TENANT_REPOSITORY } from './ports/outbound/tenant.repository.js';
import { USER_REPOSITORY } from './ports/outbound/user.repository.js';
import { USER_IDENTITY_PROVIDER } from './ports/outbound/user-identity.provider.js';
import { WEBHOOK_REPOSITORY } from './ports/outbound/webhook.repository.js';
@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      // In an enterprise setup, environment variables should be injected by the runtime
      // (Docker, Kubernetes) or the build tool (Turborepo).
      // We allow an optional ENV_FILE_PATH override, and fallback to the monorepo root for local dev.
      envFilePath: process.env.ENV_FILE_PATH
        ? [process.env.ENV_FILE_PATH]
        : ['.env', path.resolve(process.cwd(), '../../../../.env')],
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
    ApiTokensController,
    WebhooksController,
    PlatformProxyController,
    TenantProxyController,
  ],
  providers: [
    ZitadelAuthService,
    PlatformAuthGuard,
    TenantAuthGuard,
    ProvisionTenantUseCase,
    GenerateApiKeyUseCase,
    GenerateApiTokenUseCase,
    CreateWebhookUseCase,
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
      provide: API_TOKEN_REPOSITORY,
      useClass: ApiTokenDrizzleRepository,
    },
    {
      provide: WEBHOOK_REPOSITORY,
      useClass: WebhookDrizzleRepository,
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
