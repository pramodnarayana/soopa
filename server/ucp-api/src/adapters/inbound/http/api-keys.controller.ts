import { Controller, Post, Body, Param } from '@nestjs/common';
import { GenerateApiKeyUseCase } from '../../../application/use-cases/generate-api-key.use-case';
import { IsString, IsArray, IsNotEmpty } from 'class-validator';

export class CreateApiKeyRequestDto {
  @IsString()
  @IsNotEmpty()
  name: string;

  @IsArray()
  @IsString({ each: true })
  @IsNotEmpty()
  scopes: string[];
}

@Controller('tenants/:tenantId/keys')
export class ApiKeysController {
  constructor(private readonly generateApiKeyUseCase: GenerateApiKeyUseCase) {}

  @Post()
  async generate(
    @Param('tenantId') tenantId: string,
    @Body() dto: CreateApiKeyRequestDto,
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
