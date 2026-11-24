import { IpDataExplorerPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/data-explorer')({
  component: IpDataExplorerPage,
});
