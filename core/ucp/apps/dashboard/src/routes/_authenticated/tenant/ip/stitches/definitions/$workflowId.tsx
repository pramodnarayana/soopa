import { IpStitchDefinitionPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/stitches/definitions/$workflowId')({
  component: IpStitchDefinitionRoute,
});

function IpStitchDefinitionRoute() {
  const { workflowId } = Route.useParams();
  return <IpStitchDefinitionPage key={workflowId} workflowId={workflowId} />;
}
