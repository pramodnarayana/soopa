/* eslint-disable */
export const CONTROL_PLANE_EVENT_ROUTER = 'CONTROL_PLANE_EVENT_ROUTER';

export interface IControlPlaneEventRouter {
  route(event: {
    id: string;
    tenantId: string | null;
    eventType: string;
    payload: any;
  }): Promise<void>;
}
