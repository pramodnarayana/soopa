import {
  type FrontendLoggerPort,
  type LogAttributes,
  LogLevel,
  type LogLevelValue,
  type LogSinkPort,
  type StructuredLogEntry,
} from './ports';

export interface ConsoleWriterPort {
  debug(message: string): void;
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

export class ConsoleJsonLogSink implements LogSinkPort {
  private readonly writer: ConsoleWriterPort;

  constructor(writer: ConsoleWriterPort = console) {
    this.writer = writer;
  }

  public emit(entry: StructuredLogEntry): void {
    const serialized = JSON.stringify(entry);
    if (entry.level === LogLevel.ERROR) {
      this.writer.error(serialized);
      return;
    }
    if (entry.level === LogLevel.WARN) {
      this.writer.warn(serialized);
      return;
    }
    if (entry.level === LogLevel.DEBUG) {
      this.writer.debug(serialized);
      return;
    }
    this.writer.info(serialized);
  }
}

export interface StructuredJsonLoggerConfig {
  readonly sink?: LogSinkPort;
  readonly bindings?: LogAttributes;
  readonly clock?: () => string;
}

export function sanitizeLogAttributes(
  base: LogAttributes,
  extra?: LogAttributes,
): Readonly<Record<string, string | number | boolean | null>> {
  const merged: Record<string, string | number | boolean | null> = {};
  for (const [key, val] of Object.entries(base)) {
    if (val !== undefined) {
      merged[key] = val;
    }
  }
  if (extra) {
    for (const [key, val] of Object.entries(extra)) {
      if (val !== undefined) {
        merged[key] = val;
      }
    }
  }
  return merged;
}

export class StructuredJsonLoggerAdapter implements FrontendLoggerPort {
  private readonly sink: LogSinkPort;
  private readonly bindings: LogAttributes;
  private readonly clock: () => string;

  constructor(config?: StructuredJsonLoggerConfig) {
    this.sink = config?.sink ?? new ConsoleJsonLogSink();
    this.bindings = config?.bindings ?? {};
    this.clock = config?.clock ?? (() => new Date().toISOString());
  }

  public bind(bindings: LogAttributes): FrontendLoggerPort {
    return new StructuredJsonLoggerAdapter({
      sink: this.sink,
      bindings: { ...this.bindings, ...bindings },
      clock: this.clock,
    });
  }

  public debug(event: string, attributes?: LogAttributes): void {
    this.record(LogLevel.DEBUG, event, attributes);
  }

  public info(event: string, attributes?: LogAttributes): void {
    this.record(LogLevel.INFO, event, attributes);
  }

  public warn(event: string, attributes?: LogAttributes): void {
    this.record(LogLevel.WARN, event, attributes);
  }

  public error(event: string, attributes?: LogAttributes): void {
    this.record(LogLevel.ERROR, event, attributes);
  }

  private record(level: LogLevelValue, event: string, attributes?: LogAttributes): void {
    this.sink.emit({
      timestamp: this.clock(),
      level,
      event,
      attributes: sanitizeLogAttributes(this.bindings, attributes),
    });
  }
}
