import { NotificationChannel, EventTypes } from "@soopa/database";
import { describe, it, expect } from 'vitest';
import { HandlebarsTemplateRenderer } from '../src/adapters/outbound/HandlebarsTemplateRenderer.js';

describe('HandlebarsTemplateRenderer', () => {
  it('should render template with payload', () => {
    const renderer = new HandlebarsTemplateRenderer();
    const result = renderer.render('Hello {{name}}!', { name: 'World' });
    expect(result).toBe('Hello World!');
  });
});
