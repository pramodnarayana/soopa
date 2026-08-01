import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';
import { LoggerModule } from 'nestjs-pino';
import { createDbClient } from '@soopa/database';
import {
  AuthenticateUseCase,
  DrizzleTenantRepository,
  ZitadelJwksVerifier,
} from '@soopa/identity';
import * as path from 'path';
import { ApiKeysController } from './adapters/inbound/http/api-keys.controller.js';
import { ApiTokensController } from './adapters/inbound/http/api-tokens.controller.js';
import { AppsController } from './adapters/inbound/http/apps.controller.js';
import { DATABASE_CLIENT } from './infrastructure/database.constants.js';
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
import { ControlPlaneOutboxDrizzleRepository } from './adapters/outbound/database/control-plane-outbox.drizzle.repository.js';
import { TargetControlPlaneOutboxDrizzleRepository } from './adapters/outbound/database/target-control-plane-outbox.drizzle.repository.js';
import { TenantDrizzleRepository } from './adapters/outbound/database/tenant.drizzle.repository.js';
import { AppSubscriptionDrizzleRepository } from './adapters/outbound/database/app-subscription.drizzle.repository.js';
import { UserDrizzleRepository } from './adapters/outbound/database/user.drizzle.repository.js';
import { WebhookDrizzleRepository } from './adapters/outbound/database/webhook.drizzle.repository.js';
import { ZitadelOrganizationsAdapter } from './adapters/outbound/identity/zitadel-organizations.adapter.js';
import { ZitadelProjectsAdapter } from './adapters/outbound/identity/zitadel-projects.adapter.js';
import { ZitadelUsersAdapter } from './adapters/outbound/identity/zitadel-users.adapter.js';
import { SnsMessageBusAdapter } from './adapters/outbound/messaging/sns.message.bus.js';
import { ControlPlaneOutboxSweeperDaemon } from './application/services/control-plane-outbox-sweeper.daemon.js';
import { CreateWebhookUseCase } from './application/use-cases/create-webhook.use-case.js';
import { GenerateApiKeyUseCase } from './application/use-cases/generate-api-key.use-case.js';
import { GenerateApiTokenUseCase } from './application/use-cases/generate-api-token.use-case.js';
import { ProvisionTenantUseCase } from './application/use-cases/provision-tenant.use-case.js';
import { SubscribeAppUseCase } from './application/use-cases/subscribe-app.use-case.js';
import { UnsubscribeAppUseCase } from './application/use-cases/unsubscribe-app.use-case.js';
import { DeleteTenantUseCase } from './application/use-cases/delete-tenant.use-case.js';
import { ApplicationModule } from './application/application.module.js';
import { DatabaseModule } from './infrastructure/database.module.js';
import { MessagingModule } from './infrastructure/messaging/messaging.module.js';
import { API_KEY_REPOSITORY } from './ports/outbound/api-key.repository.js';
import { API_TOKEN_REPOSITORY } from './ports/outbound/api-token.repository.js';
import { APP_SUBSCRIPTION_REPOSITORY } from './ports/outbound/app-subscription.repository.js';
import { TARGET_CONTROL_PLANE_OUTBOX_REPOSITORY } from './ports/outbound/target-control-plane-outbox.repository.js';
import { MESSAGE_BUS } from './ports/outbound/message.bus.js';
import { ORGANIZATION_PROVIDER } from './ports/outbound/organization.provider.js';
import { OUTBOX_REPOSITORY } from './ports/outbound/control-plane-outbox.repository.js';
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
    LoggerModule.forRoot({
      pinoHttp: {
        transport:
          process.env.NODE_ENV !== 'production'
            ? {
                target: 'pino-pretty',
                options: {
                  colorize: true,
                  translateTime: 'SYS:standard',
                  ignore: 'pid,hostname',
                },
              }
            : undefined,
      },
    }),
    DatabaseModule,
    ApplicationModule,
    MessagingModule,
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
    {
      provide: ZitadelJwksVerifier,
      inject: [ConfigService],
      useFactory: (config: ConfigService) => {
        const projectId = config.get<string>('ZITADEL_UCP_PROJECT_ID');
        if (!projectId || projectId.trim() === '') {
          throw new Error(
            'ZITADEL_UCP_PROJECT_ID is required but not configured',
          );
        }
        return new ZitadelJwksVerifier({
          issuer: config.get<string>(
            'ZITADEL_URL',
            'http://ucp.localhost:8080',
          ),
          audience: projectId,
        });
      },
    },
    {
      provide: DrizzleTenantRepository,
      inject: [DATABASE_CLIENT],
      useFactory: (db: ReturnType<typeof createDbClient>['db']) => {
        return new DrizzleTenantRepository(db);
      },
    },
    {
      provide: AuthenticateUseCase,
      inject: [ZitadelJwksVerifier, DrizzleTenantRepository, ConfigService],
      useFactory: (
        verifier: ZitadelJwksVerifier,
        repo: DrizzleTenantRepository,
        config: ConfigService,
      ) => {
        const projectId = config.get<string>('ZITADEL_UCP_PROJECT_ID');
        if (!projectId || projectId.trim() === '') {
          throw new Error(
            'ZITADEL_UCP_PROJECT_ID is required but not configured',
          );
        }
        return new AuthenticateUseCase(verifier, repo, {
          audience: projectId,
        });
      },
    },
    PlatformAuthGuard,
    TenantAuthGuard,
    ProvisionTenantUseCase,
    SubscribeAppUseCase,
    UnsubscribeAppUseCase,
    DeleteTenantUseCase,
    GenerateApiKeyUseCase,
    GenerateApiTokenUseCase,
    CreateWebhookUseCase,
    ControlPlaneOutboxSweeperDaemon,
    {
      provide: MESSAGE_BUS,
      useClass: SnsMessageBusAdapter,
    },
    {
      provide: ORGANIZATION_PROVIDER,
      useClass: ZitadelOrganizationsAdapter,
    },
    {
      provide: PROJECT_PROVIDER,
      useClass: ZitadelProjectsAdapter,
    },
    {
      provide: USER_IDENTITY_PROVIDER,
      useClass: ZitadelUsersAdapter,
    },
  ],
})
export class AppModule {}
