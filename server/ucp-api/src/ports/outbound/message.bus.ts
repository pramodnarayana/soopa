export const MESSAGE_BUS = Symbol('MESSAGE_BUS');

export interface IMessageBus {
  publish(
    topic: string,
    message: unknown,
    groupId?: string,
    deduplicationId?: string,
  ): Promise<void>;
}
