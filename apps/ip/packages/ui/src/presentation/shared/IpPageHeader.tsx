import { Badge, PageHeader } from '@soopa/ui';
import React from 'react';

export interface IpPageHeaderProps {
  readonly eyebrow?: string;
  readonly title: string;
  readonly subtitle?: string;
  readonly actions?: React.ReactNode;
}

export function IpPageHeader({ eyebrow, title, subtitle, actions }: IpPageHeaderProps) {
  return (
    <header className="space-y-1.5 border-b border-border pb-4">
      {eyebrow ? (
        <div>
          <Badge variant="secondary" className="font-medium text-muted-foreground">
            {eyebrow}
          </Badge>
        </div>
      ) : null}
      <PageHeader title={title} description={subtitle} actions={actions} />
    </header>
  );
}
