import React from 'react';
import { useCapabilities } from '../../hooks/useCapabilities';

export interface HasCapabilityProps {
  /**
   * The capability required to render the children.
   */
  capability?: string;
  /**
   * An array of capabilities. If provided, the user must have AT LEAST ONE of these.
   */
  anyOf?: string[];
  /**
   * An array of capabilities. If provided, the user must have ALL of these.
   */
  allOf?: string[];
  /**
   * Optional fallback content to render if the user lacks the required capabilities.
   */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * A declarative component that renders its children only if the current user
 * has the required PBAC capabilities.
 */
export function HasCapability({
  capability,
  anyOf,
  allOf,
  fallback = null,
  children,
}: HasCapabilityProps) {
  const { hasCapability, hasAnyCapability, hasAllCapabilities } = useCapabilities();

  let isAuthorized = true;

  if (capability && !hasCapability(capability)) {
    isAuthorized = false;
  }
  if (anyOf && !hasAnyCapability(anyOf)) {
    isAuthorized = false;
  }
  if (allOf && !hasAllCapabilities(allOf)) {
    isAuthorized = false;
  }

  if (!isAuthorized) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}
