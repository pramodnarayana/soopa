import { createNetworkContext } from './createNetworkContext';

const { Provider, useNetwork } = createNetworkContext('useUcpNetwork');

export const UcpNetworkProvider = Provider;
export const useUcpNetwork = useNetwork;
