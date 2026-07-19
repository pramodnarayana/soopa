import { AsyncLocalStorage } from 'async_hooks';
import type { IdentityContext } from './IdentityContext.js';

export interface IdentityContextState {
  identity?: IdentityContext;
  token?: string;
}

export const identityContextStorage = new AsyncLocalStorage<IdentityContextState>();
