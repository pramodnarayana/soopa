export const MESSAGE_BUS = 'MESSAGE_BUS';

export interface IMessageBus {
  publish(
    topic: string,
    message: any,
    groupId?: string,
    deduplicationId?: string,
  ): Promise<void>;
}
