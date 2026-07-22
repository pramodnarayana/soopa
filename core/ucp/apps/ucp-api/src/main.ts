import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  
  // Add HTTP Request Logging
  app.use((req: any, res: any, next: any) => {
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
