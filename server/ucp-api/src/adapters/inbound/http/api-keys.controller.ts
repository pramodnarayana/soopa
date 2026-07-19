import { Controller, Post, Body, Param } from '@nestjs/common';
import {
  GenerateApiKeyUseCase,
  GenerateApiKeyDto,
} from '../../../application/use-cases/generate-api-key.use-case';

@Controller('tenants/:tenantId/keys')
export class ApiKeysController {
  constructor(private readonly generateApiKeyUseCase: GenerateApiKeyUseCase) {}

  @Post()
  async generate(
    @Param('tenantId') tenantId: string,
    @Body() dto: Omit<GenerateApiKeyDto, 'tenantId'>,
  ) {
    const result = await this.generateApiKeyUseCase.execute({
      tenantId,
      name: dto.name,
      scopes: dto.scopes,
    });

    // We return the rawSecret ONCE to the user.
    return {
      apiKey: result.apiKey,
      rawSecret: result.rawSecret,
    };
  }
}
