import { createNetworkContext } from './createNetworkContext';

const { Provider, useNetwork } = createNetworkContext('useEdiPlatformNetwork');

export const EdiPlatformNetworkProvider = Provider;
export const useEdiPlatformNetwork = useNetwork;
