import { describe, expect, it } from 'vitest';
import { parseBotsError } from './ediErrors';

describe('parseBotsError', () => {
  it('parses field-match mandatory errors', () => {
    const raw = '[B44] Record "PO1-IT1" field "IT101" is mandatory';
    const result = parseBotsError(raw);

    expect(result.code).toBe('B44');
    expect(result.segment).toBe('IT1');
    expect(result.element).toBe('IT101');
    expect(result.globalMessage).toBe('IT101 is missing');
    expect(result.localMessage).toBe('Missing');
    expect(result.raw).toBe(raw);
  });

  it('parses field-match non-mandatory errors', () => {
    const raw = '[E33] Record "ISA-GS-ST" field "ST01" has invalid format';
    const result = parseBotsError(raw);

    expect(result.code).toBe('E33');
    expect(result.segment).toBe('ST');
    expect(result.element).toBe('ST01');
    expect(result.globalMessage).toBe('ST01 has invalid format');
    expect(result.localMessage).toBe('Has invalid format');
    expect(result.raw).toBe(raw);
  });

  it('parses count-match errors', () => {
    const raw = '[C99] Count in ISA-IEA is 1; should be equal to number of segments 5';
    const result = parseBotsError(raw);

    expect(result.code).toBe('C99');
    expect(result.segment).toBe('ISA');
    expect(result.element).toBe('IEA');
    expect(result.globalMessage).toBe('IEA must be 5');
    expect(result.localMessage).toBe('Must be 5');
    expect(result.raw).toBe(raw);
  });

  it('strips generic code-prefixes', () => {
    const raw = '[G12] line 5 pos 10: General syntax error occurred';
    const result = parseBotsError(raw);

    expect(result.code).toBe('G12');
    expect(result.segment).toBeNull();
    expect(result.element).toBeNull();
    expect(result.globalMessage).toBe('General syntax error occurred');
    expect(result.localMessage).toBe('General syntax error occurred');
    expect(result.raw).toBe(raw);
  });

  it('handles no-match fallback with defaults', () => {
    const raw = 'Completely unformatted unknown error string';
    const result = parseBotsError(raw);

    expect(result.code).toBe('UNKNOWN');
    expect(result.segment).toBeNull();
    expect(result.element).toBeNull();
    expect(result.globalMessage).toBe(raw);
    expect(result.localMessage).toBe(raw);
    expect(result.raw).toBe(raw);
  });
});
