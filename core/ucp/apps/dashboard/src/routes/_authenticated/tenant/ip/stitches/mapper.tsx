import { IpStitchFieldMapperPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export interface IpStitchMapperSearchParams {
  readonly sourceConnectionId?: string;
  readonly stream?: string;
  readonly streamName?: string;
  readonly targetConnectionId?: string;
  readonly targetTopic?: string;
  readonly targetEntity?: string;
}

export const Route = createFileRoute('/_authenticated/tenant/ip/stitches/mapper')({
  validateSearch: (search: Record<string, unknown>): IpStitchMapperSearchParams => ({
    sourceConnectionId:
      typeof search.sourceConnectionId === 'string' && search.sourceConnectionId.length > 0
        ? search.sourceConnectionId
        : undefined,
    stream:
      typeof search.stream === 'string' && search.stream.length > 0
        ? search.stream
        : typeof search.streamName === 'string' && search.streamName.length > 0
          ? (search.streamName as string)
          : undefined,
    targetConnectionId:
      typeof search.targetConnectionId === 'string' && search.targetConnectionId.length > 0
        ? search.targetConnectionId
        : undefined,
    targetTopic:
      typeof search.targetTopic === 'string' && search.targetTopic.length > 0
        ? search.targetTopic
        : typeof search.targetEntity === 'string' && search.targetEntity.length > 0
          ? (search.targetEntity as string)
          : undefined,
  }),
  component: IpStitchMapperRoute,
});

function IpStitchMapperRoute() {
  const { sourceConnectionId, stream, targetConnectionId, targetTopic } = Route.useSearch();
  return (
    <IpStitchFieldMapperPage
      key={`${sourceConnectionId ?? 'none'}:${stream ?? 'none'}:${targetConnectionId ?? 'none'}:${targetTopic ?? 'none'}`}
      initialSourceConnectionId={sourceConnectionId}
      initialStreamName={stream}
      initialTargetConnectionId={targetConnectionId}
      initialTargetTopic={targetTopic}
    />
  );
}
