import { HttpException, HttpStatus, Logger } from '@nestjs/common';

export abstract class ZitadelBaseClient {
  protected readonly logger = new Logger(this.constructor.name);

  protected get apiUrl() {
    return process.env.ZITADEL_API_URL || 'http://ucp.localhost:8080';
  }

  protected get token() {
    return process.env.ZITADEL_API_TOKEN;
  }

  protected get ucpProjectId() {
    return process.env.ZITADEL_UCP_PROJECT_ID;
  }

  protected assertConfig() {
    if (!this.token) throw new Error('ZITADEL_API_TOKEN is not configured');
    if (!this.ucpProjectId) throw new Error('ZITADEL_UCP_PROJECT_ID is not configured');
  }

  protected async fetchWithAuth(endpoint: string, options: RequestInit = {}): Promise<Response> {
    this.assertConfig();
    const headers = new Headers(options.headers);
    headers.set('Authorization', `Bearer ${this.token}`);
    headers.set('Accept', 'application/json');
    if (!headers.has('Content-Type') && options.method !== 'GET' && options.method !== 'DELETE') {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(`${this.apiUrl}${endpoint}`, {
      ...options,
      headers,
    });

    return response;
  }

  protected async handleResponseError(response: Response, actionContext: string): Promise<never> {
    const errorText = await response.text();
    this.logger.error(`Failed to ${actionContext}: ${errorText}`);
    throw new HttpException(
      `Failed to ${actionContext}: ${errorText}`,
      HttpStatus.INTERNAL_SERVER_ERROR,
    );
  }
}
