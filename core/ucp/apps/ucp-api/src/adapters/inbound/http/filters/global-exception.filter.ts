import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';

@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(GlobalExceptionFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const reply = ctx.getResponse<FastifyReply>();
    const request = ctx.getRequest<FastifyRequest>();

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let message = 'Internal server error';
    let stack = '';

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const res = exception.getResponse();

      message =
        typeof res === 'string'
          ? res
          : typeof res === 'object' && res !== null && 'message' in res
            ? String((res as Record<string, unknown>).message)
            : JSON.stringify(res);
      stack = exception.stack || '';
    } else if (exception instanceof Error) {
      message = exception.message;
      stack = exception.stack || '';
    }

    // Enterprise-grade logging via Pino (built into Fastify)
    // Sanitize URL to remove query string for security
    const sanitizedPath = request.url.split('?')[0];
    this.logger.error(`[HTTP ${status}] ${request.method} ${sanitizedPath} - ${message}`, stack);

    void reply.status(status).send({
      statusCode: status,
      timestamp: new Date().toISOString(),
      path: request.url,
      message,
    });
  }
}
