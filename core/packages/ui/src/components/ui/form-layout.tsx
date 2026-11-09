import { HelpCircle } from 'lucide-react';
import * as React from 'react';
import { cn } from '../../lib/utils';
import { Button } from './button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './card';

export interface FormRowProps {
  readonly label?: React.ReactNode;
  readonly tooltip?: string;
  readonly required?: boolean;
  readonly description?: React.ReactNode;
  readonly error?: string;
  readonly children: React.ReactNode;
  readonly htmlFor?: string;
  readonly className?: string;
  readonly span?: 1 | 2;
}

export function FormRow({
  label,
  tooltip,
  required,
  description,
  error,
  children,
  htmlFor,
  className,
  span,
}: FormRowProps) {
  const hasLabel = label !== undefined && label !== null && label !== '';

  return (
    <div className={cn('flex flex-col gap-1.5 py-2', span === 2 && 'xl:col-span-2', className)}>
      {hasLabel ? (
        <div className="flex items-center gap-1.5 text-sm font-medium leading-5 text-foreground">
          <label htmlFor={htmlFor} className="cursor-pointer select-none">
            {label}
            {required ? <span className="ml-0.5 text-destructive">*</span> : null}
          </label>
          {tooltip ? (
            <span
              title={tooltip}
              aria-label={tooltip}
              className="inline-flex text-muted-foreground transition-colors hover:text-foreground"
            >
              <HelpCircle className="h-3.5 w-3.5" />
            </span>
          ) : null}
        </div>
      ) : null}
      <div
        className={cn(
          'min-w-0',
          error && '[&_input]:border-destructive [&_input]:ring-destructive/20',
        )}
      >
        {children}
        {description ? <p className="mt-1.5 text-xs text-muted-foreground">{description}</p> : null}
        {error ? <p className="mt-1 text-xs font-medium text-destructive">{error}</p> : null}
      </div>
    </div>
  );
}

export function FormGrid({
  children,
  className,
}: {
  readonly children: React.ReactNode;
  readonly className?: string;
}) {
  return (
    <div className={cn('grid grid-cols-1 gap-x-10 xl:grid-cols-2', className)}>{children}</div>
  );
}

export interface FormSectionProps {
  readonly title?: React.ReactNode;
  readonly description?: React.ReactNode;
  readonly actions?: React.ReactNode;
  readonly children: React.ReactNode;
  readonly className?: string;
}

export function FormSection({
  title,
  description,
  actions,
  children,
  className,
}: FormSectionProps) {
  return (
    <section className={cn('space-y-3 pt-4 first:pt-0 xl:col-span-2', className)}>
      {title || description || actions ? (
        <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border pb-2">
          <div>
            {title ? <h3 className="text-sm font-semibold text-foreground">{title}</h3> : null}
            {description ? (
              <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <div className="space-y-1">{children}</div>
    </section>
  );
}

export interface EditPageShellProps {
  readonly title: React.ReactNode;
  readonly subtitle?: React.ReactNode;
  readonly onSave?: () => void;
  readonly onSaveAndExit?: () => void;
  readonly onCancel?: () => void;
  readonly saving?: boolean;
  readonly saveDisabled?: boolean;
  readonly saveLabel?: string;
  readonly saveAndExitLabel?: string;
  readonly cancelLabel?: string;
  readonly headerActions?: React.ReactNode;
  readonly footerExtra?: React.ReactNode;
  readonly children: React.ReactNode;
  readonly loading?: boolean;
}

export function EditPageShell({
  title,
  subtitle,
  onSave,
  onSaveAndExit,
  onCancel,
  saving,
  saveDisabled,
  saveLabel = 'Save',
  saveAndExitLabel = 'Save & Exit',
  cancelLabel = 'Cancel',
  headerActions,
  footerExtra,
  children,
  loading,
}: EditPageShellProps) {
  return (
    <div className="space-y-4 pb-10">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0 border-b border-border py-4">
          <div className="min-w-0">
            <CardTitle className="truncate text-lg">{title}</CardTitle>
            {subtitle ? <CardDescription className="mt-0.5">{subtitle}</CardDescription> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {headerActions}
            {onCancel ? (
              <Button type="button" variant="outline" size="sm" onClick={onCancel}>
                {cancelLabel}
              </Button>
            ) : null}
            {onSave ? (
              <Button
                type="button"
                variant={onSaveAndExit ? 'outline' : 'default'}
                size="sm"
                onClick={onSave}
                disabled={saving || loading || saveDisabled}
              >
                {saveLabel}
              </Button>
            ) : null}
            {onSaveAndExit ? (
              <Button
                type="button"
                size="sm"
                onClick={onSaveAndExit}
                disabled={saving || loading || saveDisabled}
              >
                {saveAndExitLabel}
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="pt-5">
          {loading ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Loading...</div>
          ) : (
            <FormGrid>{children}</FormGrid>
          )}
        </CardContent>
        {(onSave || onSaveAndExit || onCancel || footerExtra) && !loading ? (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border bg-muted/30 px-5 py-3">
            <div>{footerExtra}</div>
            <div className="flex flex-wrap items-center gap-2">
              {onCancel ? (
                <Button type="button" variant="outline" size="sm" onClick={onCancel}>
                  {cancelLabel}
                </Button>
              ) : null}
              {onSave ? (
                <Button
                  type="button"
                  variant={onSaveAndExit ? 'outline' : 'default'}
                  size="sm"
                  onClick={onSave}
                  disabled={saving || saveDisabled}
                >
                  {saveLabel}
                </Button>
              ) : null}
              {onSaveAndExit ? (
                <Button
                  type="button"
                  size="sm"
                  onClick={onSaveAndExit}
                  disabled={saving || saveDisabled}
                >
                  {saveAndExitLabel}
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
