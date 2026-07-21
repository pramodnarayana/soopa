import { Controller, Get, Inject } from '@nestjs/common';
import { DATABASE_CLIENT } from '../../../infrastructure/database.module';
import { apps } from '@soopa/database';
import type { DbClient } from '@soopa/database';

@Controller('apps')
export class AppsController {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  @Get()
  async getApps() {
    const allApps = await this.db.select().from(apps);
    return allApps;
  }
}
