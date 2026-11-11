import { useTheme } from 'next-themes';

export interface StrictJsonDiagnosticsOptions {
  readonly validate: true;
  readonly allowComments: false;
  readonly trailingCommas: 'error';
  readonly comments: 'error';
  readonly enableSchemaRequest: false;
}

export const STRICT_JSON_DIAGNOSTICS_OPTIONS: StrictJsonDiagnosticsOptions = {
  validate: true,
  allowComments: false,
  trailingCommas: 'error',
  comments: 'error',
  enableSchemaRequest: false,
};

export interface MonacoJsonDiagnosticsTarget {
  readonly json: {
    readonly jsonDefaults: {
      setDiagnosticsOptions(options: StrictJsonDiagnosticsOptions): void;
    };
  };
}

export interface MonacoLoaderTarget<TMonaco> {
  config(params: { readonly monaco: TMonaco }): void;
}

export type MonacoWorkerConstructor<TWorker = Worker> = new () => TWorker;

export interface MonacoWorkerRegistry<TWorker = Worker> {
  readonly editor: MonacoWorkerConstructor<TWorker>;
  readonly json: MonacoWorkerConstructor<TWorker>;
  readonly css?: MonacoWorkerConstructor<TWorker>;
  readonly html?: MonacoWorkerConstructor<TWorker>;
  readonly ts?: MonacoWorkerConstructor<TWorker>;
}

export interface MonacoEnvironmentTarget<TWorker = Worker> {
  MonacoEnvironment?:
    | {
        getWorker?(workerId: string, label: string): TWorker;
      }
    | undefined;
}

export interface ConfigureMonacoEnvironmentOptions<TWorker = Worker> {
  readonly workers?: MonacoWorkerRegistry<TWorker>;
  readonly environmentTarget?: MonacoEnvironmentTarget<TWorker>;
}

export function resolveMonacoWorkerByLabel<TWorker>(
  workers: MonacoWorkerRegistry<TWorker>,
  label: string,
): TWorker {
  if (label === 'json') {
    return new workers.json();
  }
  if ((label === 'css' || label === 'scss' || label === 'less') && workers.css) {
    return new workers.css();
  }
  if ((label === 'html' || label === 'handlebars' || label === 'razor') && workers.html) {
    return new workers.html();
  }
  if ((label === 'typescript' || label === 'javascript') && workers.ts) {
    return new workers.ts();
  }
  return new workers.editor();
}

export function configureMonacoEnvironment<
  TMonaco extends MonacoJsonDiagnosticsTarget,
  TWorker = Worker,
>(
  monacoApi: TMonaco,
  loaderApi: MonacoLoaderTarget<TMonaco>,
  options?: ConfigureMonacoEnvironmentOptions<TWorker>,
): void {
  if (options?.workers) {
    const workers = options.workers;
    if (options.environmentTarget) {
      options.environmentTarget.MonacoEnvironment = {
        getWorker(_workerId: string, label: string): TWorker {
          return resolveMonacoWorkerByLabel(workers, label);
        },
      };
    }
  }
  monacoApi.json.jsonDefaults.setDiagnosticsOptions(STRICT_JSON_DIAGNOSTICS_OPTIONS);
  loaderApi.config({ monaco: monacoApi });
}

export function useEffectiveMonacoTheme(customThemeName?: string): string {
  const { resolvedTheme } = useTheme();
  return customThemeName ?? (resolvedTheme === 'dark' ? 'vs-dark' : 'vs');
}

export type MonacoBuiltinTheme = 'vs' | 'vs-dark' | 'hc-black' | 'hc-light';

export interface MonacoThemeRule {
  token: string;
  foreground?: string;
  background?: string;
  fontStyle?: string;
}

export interface MonacoStandaloneThemeData {
  base: MonacoBuiltinTheme;
  inherit: boolean;
  rules: MonacoThemeRule[];
  encodedTokensColors?: string[];
  colors: Record<string, string>;
}

export interface MonacoLanguageExtensionPoint {
  id: string;
  extensions?: string[];
  filenames?: string[];
  aliases?: string[];
  mimetypes?: string[];
}

export interface MonacoExpandedMonarchAction {
  group?: MonacoMonarchAction[];
  cases?: Record<string, MonacoMonarchAction>;
  token?: string;
  next?: string;
  switchTo?: string;
}

export type MonacoMonarchAction = string | MonacoExpandedMonarchAction | MonacoMonarchAction[];

export type MonacoMonarchRule =
  | [string | RegExp, MonacoMonarchAction]
  | [string | RegExp, MonacoMonarchAction, string]
  | { regex?: string | RegExp; action?: MonacoMonarchAction; include?: string };

export interface MonacoMonarchLanguage {
  tokenizer: Record<string, MonacoMonarchRule[]>;
  ignoreCase?: boolean;
  unicode?: boolean;
  defaultToken?: string;
  start?: string;
  tokenPostfix?: string;
  includeLF?: boolean;
}

export interface MonacoInstance {
  languages: {
    getLanguages(): MonacoLanguageExtensionPoint[];
    register(language: MonacoLanguageExtensionPoint): void;
    setMonarchTokensProvider(languageId: string, languageDef: MonacoMonarchLanguage): unknown;
  };
  editor: {
    defineTheme(themeName: string, themeData: MonacoStandaloneThemeData): void;
    setTheme(themeName: string): void;
  };
}

export interface MonacoMarker {
  readonly message: string;
  readonly severity: number;
  readonly startLineNumber: number;
  readonly startColumn: number;
  readonly endLineNumber: number;
  readonly endColumn: number;
}

export interface MonacoMountedEditor {
  getValue(): string;
  setValue(newValue: string): void;
  focus(): void;
}

export type MonacoBeforeMount = (monaco: MonacoInstance) => void;
export type MonacoOnMount = (editor: MonacoMountedEditor, monaco: MonacoInstance) => void;
export type MonacoOnValidate = (markers: readonly MonacoMarker[]) => void;
