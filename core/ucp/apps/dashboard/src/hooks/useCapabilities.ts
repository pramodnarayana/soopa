import { useAuthorizationContext } from '../contexts/AuthorizationContext';

export function useCapabilities() {
  const { capabilities, isPlatformAdmin } = useAuthorizationContext();

  const hasCapability = (capability: string) => {
    // Platform admins implicitly have all capabilities
    if (isPlatformAdmin) return true;
    return capabilities.includes(capability);
  };

  const hasAnyCapability = (caps: string[]) => {
    if (isPlatformAdmin) return true;
    return caps.some((cap) => capabilities.includes(cap));
  };

  const hasAllCapabilities = (caps: string[]) => {
    if (isPlatformAdmin) return true;
    return caps.every((cap) => capabilities.includes(cap));
  };

  return {
    capabilities,
    isPlatformAdmin,
    hasCapability,
    hasAnyCapability,
    hasAllCapabilities,
  };
}
