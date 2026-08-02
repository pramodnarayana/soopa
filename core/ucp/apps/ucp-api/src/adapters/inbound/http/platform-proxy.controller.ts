import {
  All,
  BadGatewayException,
  Controller,
  GatewayTimeoutException,
  Logger,
  Req,
  Res,
  UseGuards,
} from '@nestjs/common';
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

const ENTITY_HEADERS = new Set(['content-length', 'content-encoding']);

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
      const lowerKey = key.toLowerCase();
      if (
        !HOP_BY_HOP_HEADERS.has(lowerKey) &&
        !ENTITY_HEADERS.has(lowerKey) &&
        lowerKey !== 'host' &&
        value !== undefined
      ) {
        forwardHeaders[key] = Array.isArray(value) ? value.join(', ') : value;
      }
    }

    const hasBody = req.body !== undefined && req.body !== null;
    let response: Response;
    try {
      response = await fetch(url, {
        method: req.method,
        headers: forwardHeaders,
        body: hasBody ? JSON.stringify(req.body) : undefined,
        signal: AbortSignal.timeout(30000),
      });
    } catch (error) {
      if (
        error instanceof Error &&
        (error.name === 'AbortError' || error.name === 'TimeoutError')
      ) {
        this.logger.error(`Upstream request timeout for ${url}`);
        throw new GatewayTimeoutException('Upstream request timed out');
      }
      this.logger.error(`Upstream request failed for ${url}:`, error);
      throw new BadGatewayException('Upstream service unavailable');
    }

    for (const [key, value] of response.headers.entries()) {
      const lowerKey = key.toLowerCase();
      if (!HOP_BY_HOP_HEADERS.has(lowerKey) && !ENTITY_HEADERS.has(lowerKey)) {
        void res.header(key, value);
      }
    }

    const responseBody = await response.arrayBuffer();
    return res.status(response.status).send(Buffer.from(responseBody));
  }
}
