import { All, Controller, Logger, Req, Res, UseGuards } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { PlatformAuthGuard } from './guards/platform-auth.guard.js';

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

@Controller('api/v1/platform')
@UseGuards(PlatformAuthGuard)
export class PlatformProxyController {
  private readonly logger = new Logger(PlatformProxyController.name);

  @All('*')
  async proxyToEdi(@Req() req: FastifyRequest, @Res() res: FastifyReply) {
    const upstreamPath = req.url;
    const url = `${EDI_API_URL}${upstreamPath}`;

    const forwardHeaders: Record<string, string> = {};
    for (const [key, value] of Object.entries(req.headers)) {
      if (
        !HOP_BY_HOP_HEADERS.has(key.toLowerCase()) &&
        key !== 'host' &&
        value !== undefined
      ) {
        forwardHeaders[key] = Array.isArray(value) ? value.join(', ') : value;
      }
    }

    const hasBody = req.body !== undefined && req.body !== null;
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
    return res.status(response.status).send(Buffer.from(responseBody));
  }
}
