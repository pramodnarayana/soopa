import { describe, expect, it } from 'vitest';
import { createInMemoryIpWorkspaceSeed } from '../testing';

describe('Route / Stitch Legacy Navigation Alias', () => {
  it('maps legacy toRouteStitchWorkbench to route mapper', () => {
    const harness = createInMemoryIpWorkspaceSeed();
    harness.navigation.toRouteStitchWorkbench?.({
      sourceConnectionId: 'conn_source',
      streamName: 'events_stream',
    });
    expect(harness.navigation.visited).toContain(
      '/tenant/ip/stitches/mapper?sourceConnectionId=conn_source&stream=events_stream',
    );
  });
});
