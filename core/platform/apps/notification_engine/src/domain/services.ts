import { NotificationTemplate, RenderedNotification } from './models.js';


export interface ITemplateRenderer {
  render(template: string, payload: Record<string, unknown>): string;
}

export class NotificationRendererService {
  constructor(private readonly renderer: ITemplateRenderer) {}

  public render(
    template: NotificationTemplate,
    payload: Record<string, unknown>
  ): RenderedNotification {
    const subject = this.renderer.render(template.subjectTemplate, payload);
    const body = this.renderer.render(template.bodyTemplate, payload);

    return new RenderedNotification(template.channel, subject, body);
  }
}
