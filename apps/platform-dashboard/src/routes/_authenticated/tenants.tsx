import { createFileRoute, Link } from '@tanstack/react-router';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { fetchTenants, provisionTenant } from '@/lib/api';

interface Tenant {
  id: string;
  name: string;
  createdAt: string;
}

export const Route = createFileRoute('/_authenticated/tenants')({
  component: TenantsPage,
});

function TenantsPage() {
  const queryClient = useQueryClient();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [formData, setFormData] = useState({ name: '', adminEmail: '', apps: ['edi'] });

  const { data: tenants, isLoading } = useQuery({
    queryKey: ['tenants'],
    queryFn: fetchTenants,
  });

  const provisionMutation = useMutation({
    mutationFn: provisionTenant,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenants'] });
      setIsDialogOpen(false);
      setFormData({ name: '', adminEmail: '', apps: ['edi'] });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    provisionMutation.mutate({
      name: formData.name,
      adminEmail: formData.adminEmail,
      appSlugs: formData.apps,
    });
  };

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Tenants</h1>
          <p className="text-gray-500 mt-2">Manage all sub-organizations within the platform.</p>
        </div>
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger render={<Button />}>Provision Tenant</DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Provision New Tenant</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSubmit} className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="name">Tenant Name</Label>
                <Input id="name" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} required placeholder="e.g. Acme Corp" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Admin Email</Label>
                <Input id="email" type="email" value={formData.adminEmail} onChange={e => setFormData({...formData, adminEmail: e.target.value})} required placeholder="admin@acme.com" />
              </div>
              <div className="space-y-2">
                <Label>App Subscriptions</Label>
                <div className="flex gap-4 mt-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={formData.apps.includes('edi')} onChange={e => {
                      const apps = e.target.checked ? [...formData.apps, 'edi'] : formData.apps.filter(a => a !== 'edi');
                      setFormData({...formData, apps});
                    }} className="rounded border-gray-300" />
                    B2B EDI App
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={formData.apps.includes('idp')} onChange={e => {
                      const apps = e.target.checked ? [...formData.apps, 'idp'] : formData.apps.filter(a => a !== 'idp');
                      setFormData({...formData, apps});
                    }} className="rounded border-gray-300" />
                    Intelligent Document Processing
                  </label>
                </div>
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setIsDialogOpen(false)}>Cancel</Button>
                <Button type="submit" disabled={provisionMutation.isPending}>
                  {provisionMutation.isPending ? 'Provisioning...' : 'Provision'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="border rounded-md bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Tenant ID</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={4} className="text-center h-24">Loading...</TableCell></TableRow>
            ) : (
              tenants?.map((tenant: Tenant) => (
                <TableRow key={tenant.id}>
                  <TableCell className="font-medium">{tenant.name}</TableCell>
                  <TableCell className="font-mono text-sm text-gray-500">{tenant.id}</TableCell>
                  <TableCell className="text-gray-500">{new Date(tenant.createdAt).toLocaleDateString()}</TableCell>
                  <TableCell className="text-right space-x-3">
                    <Link to="/tenants/$id/webhooks" params={{ id: tenant.id }} className="text-gray-600 hover:text-black hover:underline text-sm font-medium">
                      Webhooks
                    </Link>
                    <Link to="/tenants/$id/keys" params={{ id: tenant.id }} className="text-blue-600 hover:underline text-sm font-medium">
                      API Keys
                    </Link>
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
