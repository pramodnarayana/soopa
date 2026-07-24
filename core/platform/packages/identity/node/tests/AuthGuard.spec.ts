import {
  ExecutionContext,
  ForbiddenException,
  InternalServerErrorException,
  UnauthorizedException,
} from '@nestjs/common';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthenticateUseCase } from '../src/application/Authenticate.js';
import { IdentityInfrastructureError, TenantMappingDomainError } from '../src/domain/Errors.js';
import { AuthGuard } from '../src/middleware/AuthGuard.js';

describe('AuthGuard', () => {
  let guard: AuthGuard;
  let useCase: AuthenticateUseCase;

  beforeEach(() => {
    vi.clearAllMocks();
    // @ts-expect-error - Mucking dependencies for test
    useCase = { execute: vi.fn() } as unknown as AuthenticateUseCase;
    guard = new AuthGuard(useCase);
  });

  function createMockContext(headers: Record<string, string>): ExecutionContext {
    return {
      switchToHttp: () => ({
        getRequest: () => ({ headers }),
      }),
    } as unknown as ExecutionContext;
  }

  it('should throw UnauthorizedException if authorization header is missing', async () => {
    const context = createMockContext({});
    await expect(guard.canActivate(context)).rejects.toThrow(UnauthorizedException);
  });

  it('should throw UnauthorizedException if authorization header is invalid', async () => {
    const context = createMockContext({ authorization: 'Basic token' });
    await expect(guard.canActivate(context)).rejects.toThrow(UnauthorizedException);
  });

  it('should authenticate user and decorate request', async () => {
    const executeSpy = vi.spyOn(useCase, 'execute').mockResolvedValueOnce({
      userId: 'u1',
      tenantId: 't1',
      email: 'test@test.com',
      name: 'Test',
      roles: [],
    });

    const req = { headers: { authorization: 'Bearer valid-token' } };
    const context = {
      switchToHttp: () => ({ getRequest: () => req }),
    } as unknown as ExecutionContext;

    const result = await guard.canActivate(context);

    expect(result).toBe(true);
    expect((req as any).userId).toBe('u1');
    expect((req as any).tenantId).toBe('t1');
    expect(executeSpy).toHaveBeenCalledWith('valid-token');
  });

  it('should throw ForbiddenException on TenantMappingDomainError', async () => {
    vi.spyOn(useCase, 'execute').mockRejectedValueOnce(new TenantMappingDomainError('test'));

    const context = createMockContext({ authorization: 'Bearer token' });
    await expect(guard.canActivate(context)).rejects.toThrow(ForbiddenException);
  });

  it('should throw InternalServerErrorException on IdentityInfrastructureError', async () => {
    vi.spyOn(useCase, 'execute').mockRejectedValueOnce(
      new IdentityInfrastructureError('db failed'),
    );

    const context = createMockContext({ authorization: 'Bearer token' });
    await expect(guard.canActivate(context)).rejects.toThrow(InternalServerErrorException);
  });

  it('should throw UnauthorizedException on other errors', async () => {
    vi.spyOn(useCase, 'execute').mockRejectedValueOnce(new Error('bad jwt'));

    const context = createMockContext({ authorization: 'Bearer token' });
    await expect(guard.canActivate(context)).rejects.toThrow(UnauthorizedException);
  });
});
