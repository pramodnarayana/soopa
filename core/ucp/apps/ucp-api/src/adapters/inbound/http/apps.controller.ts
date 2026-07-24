import { Controller, Get, Inject } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { apps } from '@soopa/database';
import { DATABASE_CLIENT } from '../../../infrastructure/database.module.js';

@Controller('apps')
export class AppsController {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  @Get()
  async getApps() {
    const allApps = await this.db.select().from(apps);
    return allApps;
  }
}
