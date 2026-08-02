import { Global, Module } from '@nestjs/common';
import { createDbClient } from '@soopa/database';
import { ApiKeyDrizzleRepository } from '../adapters/outbound/database/api-key.drizzle.repository.js';
import { ApiTokenDrizzleRepository } from '../adapters/outbound/database/api-token.drizzle.repository.js';
import { AppSubscriptionDrizzleRepository } from '../adapters/outbound/database/app-subscription.drizzle.repository.js';
import { ControlPlaneOutboxDrizzleRepository } from '../adapters/outbound/database/control-plane-outbox.drizzle.repository.js';
import { ShardRegistryDrizzleRepository } from '../adapters/outbound/database/shard-registry.drizzle.repository.js';
import { TargetControlPlaneOutboxDrizzleRepository } from '../adapters/outbound/database/target-control-plane-outbox.drizzle.repository.js';
import { TenantDrizzleRepository } from '../adapters/outbound/database/tenant.drizzle.repository.js';
import { UserDrizzleRepository } from '../adapters/outbound/database/user.drizzle.repository.js';
import { WebhookDrizzleRepository } from '../adapters/outbound/database/webhook.drizzle.repository.js';
import { API_KEY_REPOSITORY } from '../ports/outbound/api-key.repository.js';
import { API_TOKEN_REPOSITORY } from '../ports/outbound/api-token.repository.js';
import { APP_SUBSCRIPTION_REPOSITORY } from '../ports/outbound/app-subscription.repository.js';
import { OUTBOX_REPOSITORY } from '../ports/outbound/control-plane-outbox.repository.js';
import { SHARD_REGISTRY_REPOSITORY } from '../ports/outbound/shard-registry.repository.js';
import { TARGET_CONTROL_PLANE_OUTBOX_REPOSITORY } from '../ports/outbound/target-control-plane-outbox.repository.js';
import { TENANT_REPOSITORY } from '../ports/outbound/tenant.repository.js';
import { USER_REPOSITORY } from '../ports/outbound/user.repository.js';
import { WEBHOOK_REPOSITORY } from '../ports/outbound/webhook.repository.js';
import { DATABASE_CLIENT } from './database.constants.js';

const databaseProvider = {
  provide: DATABASE_CLIENT,
  useFactory: () => {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error('DATABASE_URL is not set');
    }
    const { db } = createDbClient(connectionString);
    return db;
  },
};

const repositoryProviders = [
  { provide: TENANT_REPOSITORY, useClass: TenantDrizzleRepository },
  { provide: USER_REPOSITORY, useClass: UserDrizzleRepository },
  { provide: WEBHOOK_REPOSITORY, useClass: WebhookDrizzleRepository },
  { provide: API_KEY_REPOSITORY, useClass: ApiKeyDrizzleRepository },
  { provide: API_TOKEN_REPOSITORY, useClass: ApiTokenDrizzleRepository },
  { provide: OUTBOX_REPOSITORY, useClass: ControlPlaneOutboxDrizzleRepository },
  {
    provide: TARGET_CONTROL_PLANE_OUTBOX_REPOSITORY,
    useClass: TargetControlPlaneOutboxDrizzleRepository,
  },
  {
    provide: APP_SUBSCRIPTION_REPOSITORY,
    useClass: AppSubscriptionDrizzleRepository,
  },
  {
    provide: SHARD_REGISTRY_REPOSITORY,
    useClass: ShardRegistryDrizzleRepository,
  },
];

@Global()
@Module({
  providers: [databaseProvider, ...repositoryProviders],
  exports: [DATABASE_CLIENT, ...repositoryProviders],
})
export class DatabaseModule {}
