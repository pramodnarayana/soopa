import { NestFactory } from '@nestjs/core';
import * as express from 'express';
import { NextFunction, Request, Response } from 'express';
import { AppModule } from './app.module.js';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, { bodyParser: false });

  // Enterprise-Grade Zero-Copy Proxy:
  // Conditionally apply body parser ONLY to non-proxy routes.
  // This allows http-proxy-middleware to stream raw TCP socket data directly
  // to the backend without allocating memory or double-serializing.
  const jsonParser = express.json();
  const urlencodedParser = express.urlencoded({ extended: true });

  app.use((req: Request, res: Response, next: NextFunction) => {
    // Skip body parsing for all EDI proxy routes
    if (
      req.originalUrl.includes('/api/v1/platform') ||
      req.originalUrl.match(/\/api\/v1\/tenants\/[^/]+\/edi/)
    ) {
      next();
    } else {
      jsonParser(req, res, (err) => {
        if (err) return next(err);
        urlencodedParser(req, res, next);
      });
    }
  });

  // Add HTTP Request Logging
  app.use((req: Request, res: Response, next: NextFunction) => {
    const start = Date.now();
    res.on('finish', () => {
      const duration = Date.now() - start;
      console.log(`[HTTP] ${req.method} ${req.url} ${res.statusCode} - ${duration}ms`);
    });
    next();
  });

  app.enableCors({
    origin: process.env.FRONTEND_URL || 'http://localhost:5173',
  });
  const port = process.env.PORT ?? 3000;
  await app.listen(port);
  console.log(`\n🚀 UCP Backend API is running on: http://localhost:${port}`);
  console.log(
    `🌐 Platform Dashboard (Frontend) is running on: ${process.env.FRONTEND_URL || 'http://localhost:5173'}\n`,
  );
}
void bootstrap();
