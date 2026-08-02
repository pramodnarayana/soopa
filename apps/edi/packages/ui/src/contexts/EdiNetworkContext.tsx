import { createNetworkContext } from './createNetworkContext';

const { Provider, useNetwork } = createNetworkContext('useEdiNetwork');

export const EdiNetworkProvider = Provider;
export const useEdiNetwork = useNetwork;
