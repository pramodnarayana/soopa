import { Module, DynamicModule, Provider, Global } from '@nestjs/common';
import { createDbClient } from '@soopa/database';
import { AuthenticateUseCase } from './application/Authenticate.js';
import { ZitadelJwksVerifier } from './adapters/outbound/zitadel/ZitadelJwksVerifier.js';
import { DrizzleTenantRepository } from './adapters/outbound/database/DrizzleTenantRepository.js';
import { AuthGuard } from './middleware/AuthGuard.js';

export interface IdentityModuleOptions {
  zitadelIssuer: string;
  zitadelAudience: string;
  dbConnectionString: string;
}

@Global()
@Module({})
export class IdentityModule {
  static register(options: IdentityModuleOptions): DynamicModule {
    const dbProvider: Provider = {
      provide: 'DATABASE_CONNECTION',
      useFactory: () => {
        return createDbClient(options.dbConnectionString).db;
      },
    };

    const verifierProvider: Provider = {
      provide: ZitadelJwksVerifier,
      useFactory: () => {
        return new ZitadelJwksVerifier({ issuer: options.zitadelIssuer, audience: options.zitadelAudience });
      },
    };

    const repoProvider: Provider = {
      provide: DrizzleTenantRepository,
      useFactory: (db: ReturnType<typeof createDbClient>['db']) => {
        return new DrizzleTenantRepository(db);
      },
      inject: ['DATABASE_CONNECTION'],
    };

    const useCaseProvider: Provider = {
      provide: AuthenticateUseCase,
      useFactory: (verifier: ZitadelJwksVerifier, repo: DrizzleTenantRepository) => {
        return new AuthenticateUseCase(verifier, repo);
      },
      inject: [ZitadelJwksVerifier, DrizzleTenantRepository],
    };

    return {
      module: IdentityModule,
      providers: [
        dbProvider,
        verifierProvider,
        repoProvider,
        useCaseProvider,
        AuthGuard,
      ],
      exports: [
        AuthenticateUseCase,
        AuthGuard,
      ],
    };
  }
}
