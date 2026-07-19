import { NotificationChannel, EventTypes } from "@soopa/database";
import { test, expect } from 'vitest';
import { NotificationEvent, NotificationTemplate, Channel } from '../src/domain/models.js';
import { NotificationRendererService } from '../src/domain/services.js';
import { ITemplateRenderer } from '../src/domain/services.js';

// Fake Renderer for Pure Logic (Zero Mocks for Pure Logic)
class FakeTemplateRenderer implements ITemplateRenderer {
  render(template: string, payload: Record<string, unknown>): string {
    return template.replace('{{name}}', payload.name);
  }
}

test('NotificationRendererService pure domain logic', () => {
  const fakeRenderer = new FakeTemplateRenderer();
  const service = new NotificationRendererService(fakeRenderer);

  const template = new NotificationTemplate(
    EventTypes.TEST,
    NotificationChannel.EMAIL,
    'Hello {{name}}',
    'Welcome {{name}} to Soopa!'
  );

  const payload = { name: 'Alice' };

  const result = service.render(template, payload);

  expect(result.channel).toBe(NotificationChannel.EMAIL);
  expect(result.subject).toBe('Hello Alice');
  expect(result.body).toBe('Welcome Alice to Soopa!');
});
