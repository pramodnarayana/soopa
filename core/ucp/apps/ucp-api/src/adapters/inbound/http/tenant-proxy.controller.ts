import { All, Controller, Next, Req, Res, UseGuards } from '@nestjs/common';
import type { NextFunction, Request, Response } from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';
import { TenantAuthGuard } from './guards/tenant-auth.guard.js';

const EDI_API_URL = process.env.EDI_API_URL || 'http://localhost:8001';

@Controller('api/v1/tenants/:tenantId/edi')
@UseGuards(TenantAuthGuard)
export class TenantProxyController {
  private proxy = createProxyMiddleware({
    target: EDI_API_URL,
    changeOrigin: true,
    pathRewrite: (path) => {
      // Replace the /api/v1/tenants/:tenantId/edi prefix with /api/v1
      // Example: /api/v1/tenants/123/edi/transactions -> /api/v1/transactions
      return path.replace(/^\/api\/v1\/tenants\/[^/]+\/edi/, '/api/v1');
    },
  });

  @All('*')
  proxyToEdi(@Req() req: Request, @Res() res: Response, @Next() next: NextFunction) {
    void this.proxy(req, res, next);
  }
}
