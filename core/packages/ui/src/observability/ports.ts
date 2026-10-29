export const LogLevel = {
  DEBUG: 'DEBUG',
  INFO: 'INFO',
  WARN: 'WARN',
  ERROR: 'ERROR',
} as const;

export type LogLevelValue = (typeof LogLevel)[keyof typeof LogLevel];

export type LogAttributeScalar = string | number | boolean | null | undefined;
export type LogAttributes = Readonly<Record<string, LogAttributeScalar>>;

export interface StructuredLogEntry {
  readonly timestamp: string;
  readonly level: LogLevelValue;
  readonly event: string;
  readonly attributes: Readonly<Record<string, string | number | boolean | null>>;
}

export interface LogSinkPort {
  emit(entry: StructuredLogEntry): void;
}

export interface FrontendLoggerPort {
  bind(bindings: LogAttributes): FrontendLoggerPort;
  debug(event: string, attributes?: LogAttributes): void;
  info(event: string, attributes?: LogAttributes): void;
  warn(event: string, attributes?: LogAttributes): void;
  error(event: string, attributes?: LogAttributes): void;
}
