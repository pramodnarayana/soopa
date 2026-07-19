export * from './domain/IdentityContext.js';
export * from './domain/Errors.js';
export * from './ports/TokenVerifier.js';
export * from './ports/TenantRepository.js';
export * from './adapters/outbound/zitadel/ZitadelJwksVerifier.js';
export * from './adapters/outbound/database/DrizzleTenantRepository.js';
export * from './application/Authenticate.js';

export { default as identityPlugin } from './middleware/fastifyPlugin.js';
export * from './middleware/fastifyPlugin.js';
