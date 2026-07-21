import { useState, useEffect } from 'react';
import { useUpdateTenantUser } from '@/domains/users/api/mutations';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Save } from 'lucide-react';
import { toast } from 'sonner';

import { TenantUser } from '@/domains/users/api/queries';

const normalizeRole = (role?: string) => role === 'Unknown' ? '' : (role || '');

export function UserDetailPanel({ user, tenantId, tenantRoles }: {
  user: TenantUser;
  tenantId: string;
  tenantRoles: any[];
}) {
  const [editFirst, setEditFirst] = useState(user.firstName || '');
  const [editLast, setEditLast] = useState(user.lastName || '');
  const [editRole, setEditRole] = useState(normalizeRole(user.role));
  const isDirty = editFirst !== (user.firstName || '') || editLast !== (user.lastName || '') || editRole !== normalizeRole(user.role);

  useEffect(() => {
    setEditFirst(user.firstName || '');
    setEditLast(user.lastName || '');
    setEditRole(normalizeRole(user.role));
  }, [user.id, user.firstName, user.lastName, user.role]);

  const updateMutationObj = useUpdateTenantUser();

  const handleSave = () => {
    updateMutationObj.mutate(
      { tenantId, userId: user.id, firstName: editFirst, lastName: editLast, role: editRole },
      {
        onSuccess: () => {
          toast.success('User updated successfully.');
        },
        onError: (error: any) => {
          toast.error(`Error updating user: ${error.message}`);
        }
      }
    );
  };

  const handleCancel = () => {
    setEditFirst(user.firstName || '');
    setEditLast(user.lastName || '');
    setEditRole(normalizeRole(user.role));
  };

  return (
    <div className="bg-slate-50/70 border-t border-slate-100 px-6 py-5">
      <div className="max-w-2xl space-y-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">User Details</p>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600">First Name</label>
            <Input
              value={editFirst}
              onChange={(e) => setEditFirst(e.target.value)}
              className="h-9 rounded-lg text-sm bg-white"
              placeholder="First name"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600">Last Name</label>
            <Input
              value={editLast}
              onChange={(e) => setEditLast(e.target.value)}
              className="h-9 rounded-lg text-sm bg-white"
              placeholder="Last name"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600">Email Address</label>
            <Input
              value={user.email}
              disabled
              className="h-9 rounded-lg text-sm bg-slate-100 text-slate-500 cursor-not-allowed"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600">Role</label>
            <Select value={editRole} onValueChange={(v) => setEditRole(v || '')}>
              <SelectTrigger className="w-full h-9 rounded-lg text-sm bg-white">
                <SelectValue placeholder="Select a role" />
              </SelectTrigger>
              <SelectContent>
                {tenantRoles.map((r: any) => (
                  <SelectItem key={r.key} value={r.key}>{r.displayName}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {user.createdAt && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-600">Created At</label>
              <Input
                value={new Date(user.createdAt).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}
                disabled
                className="h-9 rounded-lg text-sm bg-slate-100 text-slate-500 cursor-not-allowed"
              />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-1">
          <Button
            size="sm"
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg h-8 px-4 text-xs flex items-center gap-1.5"
            disabled={!isDirty || updateMutationObj.isPending}
            onClick={handleSave}
          >
            {updateMutationObj.isPending ? (
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : <Save className="w-3.5 h-3.5" />}
            Save Changes
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="rounded-lg h-8 px-4 text-xs"
            disabled={!isDirty || updateMutationObj.isPending}
            onClick={handleCancel}
          >
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
