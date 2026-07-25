import { All, Controller, Next, Req, Res } from '@nestjs/common';
import type { NextFunction, Request, Response } from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';

const EDI_API_URL = process.env.EDI_API_URL || 'http://localhost:8000';

@Controller('api/v1/tenants/:tenantId/edi')
export class TenantProxyController {
  private proxy = createProxyMiddleware({
    target: EDI_API_URL,
    changeOrigin: true,
    pathRewrite: (path) => {
      // The incoming path is /api/v1/tenants/:tenantId/edi/...
      // We rewrite it to /api/... so the EDI Python API receives it correctly.
      // Wait, let me check the Python API routers...
      // The Python API routers have `/api/v1/...` for platform and some others.
      // Wait, `/api/me` is literally `/api/me`.
      // `/api/v1/edi-headers` is literally `/api/v1/edi-headers`.
      // So if the UI calls `/api/v1/tenants/:tenantId/edi/api/me`, it should rewrite to `/api/me`.
      // Actually, if the UI calls `/api/v1/tenants/:tenantId/edi/me`, it should rewrite to `/api/me`.
      // Let's rewrite `/api/v1/tenants/[^/]+/edi(.*)` to `/api$1`.
      return path.replace(/^\/api\/v1\/tenants\/[^/]+\/edi/, '/api');
    },
  });

  @All('*')
  proxyToEdi(@Req() req: Request, @Res() res: Response, @Next() next: NextFunction) {
    void this.proxy(req, res, next);
  }
}
