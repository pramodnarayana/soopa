import { createFileRoute } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

export const Route = createFileRoute('/_authenticated/tenants/$id/webhooks')({
  component: WebhooksPage,
});

function WebhooksPage() {
  const { id } = Route.useParams();

  // Mock fetching webhooks
  const { data: webhooks, isLoading } = useQuery({
    queryKey: ['tenants', id, 'webhooks'],
    queryFn: async () => {
      return [
        { id: 'wh_1', url: 'https://api.acme.com/webhooks/soopa', events: ['document.processed', 'invoice.created'], status: 'active', lastFired: new Date().toISOString() },
      ];
    },
  });

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Webhooks</h1>
          <p className="text-gray-500 mt-2">Configure event subscriptions for this tenant.</p>
        </div>
        <Button>Add Webhook Endpoint</Button>
      </div>

      <div className="border rounded-md bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Endpoint URL</TableHead>
              <TableHead>Events</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last Fired</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-gray-500 h-24">Loading webhooks...</TableCell>
              </TableRow>
            ) : webhooks?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-gray-500 h-24">No webhooks configured.</TableCell>
              </TableRow>
            ) : (
              webhooks?.map((webhook) => (
                <TableRow key={webhook.id}>
                  <TableCell className="font-medium text-blue-600">{webhook.url}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {webhook.events.map((evt) => (
                        <span key={evt} className="px-2 py-0.5 bg-gray-100 border text-gray-600 text-[10px] rounded-md uppercase tracking-wider">
                          {evt}
                        </span>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded-full">
                      {webhook.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-gray-500">{new Date(webhook.lastFired).toLocaleString()}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm">Edit</Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
