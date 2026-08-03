import { All, Controller, Logger, Req, Res, UseGuards } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';

const EDI_API_URL = process.env.EDI_API_URL || 'http://localhost:8001';

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'transfer-encoding',
  'te',
  'trailer',
  'upgrade',
  'proxy-authorization',
  'proxy-authenticate',
]);

@Controller('api/v1/tenants/:tenantId/edi')
@UseGuards(TenantAuthGuard)
export class TenantProxyController {
  private readonly logger = new Logger(TenantProxyController.name);

  @All('*')
  async proxyToEdi(
    @Req() req: FastifyRequest & { ucpTenantId?: string },
    @Res() res: FastifyReply,
  ) {
    const params = req.params as Record<string, string>;
    const tenantId = params.tenantId;

    // Rewrite: /api/v1/tenants/:tenantId/edi/foo -> /api/v1/foo
    const rewrittenPath = req.url.replace(`/api/v1/tenants/${tenantId}/edi`, '/api/v1');
    const url = `${EDI_API_URL}${rewrittenPath}`;

    this.logger.log(`[PROXY] ${req.method} ${req.url} -> ${url} (tenant=${req.ucpTenantId})`);

    const forwardHeaders: Record<string, string> = {};
    for (const [key, value] of Object.entries(req.headers)) {
      if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase()) && key !== 'host' && value !== undefined) {
        forwardHeaders[key] = Array.isArray(value) ? value.join(', ') : value;
      }
    }

    // Inject the resolved internal tenant ID for the downstream EDI API
    if (req.ucpTenantId) {
      forwardHeaders['x-tenant-id'] = req.ucpTenantId;
    }

    const hasBody =
      req.method !== 'GET' && req.method !== 'HEAD' && req.body !== undefined && req.body !== null;

    this.logger.log(
      `[PROXY OUTBOUND] ${req.method} ${url}\nHeaders: ${JSON.stringify(forwardHeaders)}\nBody: ${hasBody ? JSON.stringify(req.body) : 'none'}`,
    );

    try {
      const response = await fetch(url, {
        method: req.method,
        headers: forwardHeaders,
        body: hasBody ? JSON.stringify(req.body) : undefined,
      });

      for (const [key, value] of response.headers.entries()) {
        if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
          void res.header(key, value);
        }
      }

      const responseBody = await response.arrayBuffer();

      this.logger.log(
        `[PROXY RESPONSE] ${response.status} from ${url}\nHeaders: ${JSON.stringify(Object.fromEntries(response.headers.entries()))}`,
      );

      return res.status(response.status).send(Buffer.from(responseBody));
    } catch (error) {
      this.logger.error(`[PROXY ERROR] Failed to proxy to ${url}:`, error);
      return res.status(502).send({
        error: 'Bad Gateway',
        message: 'Failed to communicate with downstream EDI service',
        details: error instanceof Error ? error.message : String(error),
      });
    }
  }
}
