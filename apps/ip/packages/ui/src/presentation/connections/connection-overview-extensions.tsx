import type { ApiProblem } from '@soopa/ui';
import React from 'react';
import type { Connection } from '../../domain/connection';
import { UNIVERSAL_SIMULATOR_APP_ID } from '../../domain/enums';
import { SimulatorEntitiesSection } from './SimulatorEntitiesSection';

export interface ConnectionOverviewExtensionProps {
  readonly connection: Connection;
  readonly onProblem: (problem: ApiProblem | null) => void;
}

function SimulatorConnectionOverviewExtension({
  connection,
  onProblem,
}: ConnectionOverviewExtensionProps) {
  return <SimulatorEntitiesSection connectionId={connection.id} onProblem={onProblem} />;
}

export const CONNECTION_OVERVIEW_EXTENSIONS: Readonly<
  Record<string, React.ComponentType<ConnectionOverviewExtensionProps>>
> = {
  [UNIVERSAL_SIMULATOR_APP_ID]: SimulatorConnectionOverviewExtension,
};

export function resolveConnectionOverviewExtension(
  appId: string,
): React.ComponentType<ConnectionOverviewExtensionProps> | null {
  return CONNECTION_OVERVIEW_EXTENSIONS[appId] ?? null;
}
