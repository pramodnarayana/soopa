import {
  type FrontendLoggerPort,
  type LogAttributes,
  LogLevel,
  type LogLevelValue,
  type StructuredLogEntry,
  sanitizeLogAttributes,
} from '../observability';

export class RecordingLoggerFake implements FrontendLoggerPort {
  public readonly entries: StructuredLogEntry[];
  private readonly bindings: LogAttributes;
  private readonly clock: () => string;

  constructor(
    entries: StructuredLogEntry[] = [],
    bindings: LogAttributes = {},
    clock: () => string = () => '2026-10-29T00:00:00.000Z',
  ) {
    this.entries = entries;
    this.bindings = bindings;
    this.clock = clock;
  }

  public bind(bindings: LogAttributes): RecordingLoggerFake {
    return new RecordingLoggerFake(this.entries, { ...this.bindings, ...bindings }, this.clock);
  }

  public debug(event: string, attributes?: LogAttributes): void {
    this.push(LogLevel.DEBUG, event, attributes);
  }

  public info(event: string, attributes?: LogAttributes): void {
    this.push(LogLevel.INFO, event, attributes);
  }

  public warn(event: string, attributes?: LogAttributes): void {
    this.push(LogLevel.WARN, event, attributes);
  }

  public error(event: string, attributes?: LogAttributes): void {
    this.push(LogLevel.ERROR, event, attributes);
  }

  private push(level: LogLevelValue, event: string, attributes?: LogAttributes): void {
    this.entries.push({
      timestamp: this.clock(),
      level,
      event,
      attributes: sanitizeLogAttributes(this.bindings, attributes),
    });
  }
}
