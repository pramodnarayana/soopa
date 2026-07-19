import * as Handlebars from 'handlebars';
import { ITemplateRenderer } from '../../domain/services.js';

export class HandlebarsTemplateRenderer implements ITemplateRenderer {
  public render(template: string, payload: Record<string, unknown>): string {
    const compiled = Handlebars.compile(template);
    return compiled(payload);
  }
}
