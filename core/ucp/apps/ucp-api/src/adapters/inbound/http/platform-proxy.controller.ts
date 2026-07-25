import { All, Controller, Next, Req, Res, UseGuards } from '@nestjs/common';
import type { NextFunction, Request, Response } from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';
import { ApiKeyGuard } from './api-key.guard.js';

const EDI_API_URL = process.env.EDI_API_URL || 'http://localhost:8000';

@Controller('api/v1/platform')
@UseGuards(ApiKeyGuard)
export class PlatformProxyController {
  private proxy = createProxyMiddleware({
    target: EDI_API_URL,
    changeOrigin: true,
    // Note: The path remains unchanged, e.g. /api/v1/platform/trading-partners -> /api/v1/platform/trading-partners
  });

  @All('*')
  proxyToEdi(@Req() req: Request, @Res() res: Response, @Next() next: NextFunction) {
    // We execute the proxy middleware. It automatically pipes the request to EDI and pipes the response back.
    // If it throws or passes to next, we handle it.
    void this.proxy(req, res, next);
  }
}
