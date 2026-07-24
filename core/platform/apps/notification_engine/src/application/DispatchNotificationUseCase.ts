import { NotificationEvent } from '../domain/models.js';
import { NotificationRendererService } from '../domain/services.js';
import { IDeliveryService, ITemplateRepository } from '../ports/index.js';

export class DispatchNotificationUseCase {
  constructor(
    private readonly templateRepo: ITemplateRepository,
    private readonly deliveryService: IDeliveryService,
    private readonly rendererService: NotificationRendererService,
  ) {}

  public async execute(event: NotificationEvent): Promise<void> {
    const templates = await this.templateRepo.getTemplates(event.tenantId, event.eventType);

    // Filter templates to only those requested in the event's channels
    const targetTemplates = templates.filter((t) => event.channels.includes(t.channel));

    if (targetTemplates.length === 0) {
      console.warn(
        `No templates found for event ${event.eventType} on channels ${event.channels.join(',')}`,
      );
      return;
    }

    const dispatchPromises = targetTemplates.map(async (template) => {
      const rendered = this.rendererService.render(template, event.payload);
      await this.deliveryService.dispatch(rendered);
    });

    await Promise.all(dispatchPromises);
  }
}
