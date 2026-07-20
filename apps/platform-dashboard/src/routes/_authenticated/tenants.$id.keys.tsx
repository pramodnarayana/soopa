import { createFileRoute } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

export const Route = createFileRoute('/_authenticated/tenants/$id/keys')({
  component: ApiKeysPage,
});

function ApiKeysPage() {
  const { id } = Route.useParams();

  // Mock fetching API keys
  const { data: apiKeys, isLoading } = useQuery({
    queryKey: ['tenants', id, 'api-keys'],
    queryFn: async () => {
      return [
        { id: 'key_1', name: 'Production Backend', prefix: 'sk_prod_...', scopes: ['edi:*'], createdAt: new Date().toISOString() },
        { id: 'key_2', name: 'Staging Scraper', prefix: 'sk_test_...', scopes: ['idp:read'], createdAt: new Date().toISOString() },
      ];
    },
  });

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">API Keys</h1>
          <p className="text-gray-500 mt-2">Manage programmatic access tokens for this tenant.</p>
        </div>
        <Button>Generate New Key</Button>
      </div>

      <div className="border rounded-md bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Token Prefix</TableHead>
              <TableHead>Scopes</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-gray-500 h-24">Loading API keys...</TableCell>
              </TableRow>
            ) : apiKeys?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-gray-500 h-24">No API keys generated yet.</TableCell>
              </TableRow>
            ) : (
              apiKeys?.map((key) => (
                <TableRow key={key.id}>
                  <TableCell className="font-medium">{key.name}</TableCell>
                  <TableCell className="font-mono text-xs text-gray-500">{key.prefix}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      {key.scopes.map((scope) => (
                        <span key={scope} className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded-md">
                          {scope}
                        </span>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-gray-500">{new Date(key.createdAt).toLocaleDateString()}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="destructive" size="sm">Revoke</Button>
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
