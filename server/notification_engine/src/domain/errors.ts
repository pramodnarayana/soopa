
export class InfrastructureError extends Error {
  constructor(message: string, public readonly code: string = 'INFRASTRUCTURE_ERROR', public readonly originalError?: unknown) {
    super(message);
    this.name = 'InfrastructureError';
  }
}
