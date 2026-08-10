import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useUpdateTenantUser } from '@/domains/users/api/mutations';

import { TenantUser } from '@/domains/users/api/queries';

const normalizeRole = (role?: string) => (role === 'Unknown' ? '' : role || '');

export function UserDetailPanel({
  user,
  tenantId,
  tenantRoles,
}: {
  user: TenantUser;
  tenantId: string;
  tenantRoles: { key: string; displayName: string }[];
}) {
  const [editFirst, setEditFirst] = useState(user.firstName || '');
  const [editLast, setEditLast] = useState(user.lastName || '');
  const [editRole, setEditRole] = useState(normalizeRole(user.role));
  const isDirty =
    editFirst !== (user.firstName || '') ||
    editLast !== (user.lastName || '') ||
    editRole !== normalizeRole(user.role);

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
        onError: (error: Error) => {
          toast.error(`Error updating user: ${error.message}`);
        },
      },
    );
  };

  const handleCancel = () => {
    setEditFirst(user.firstName || '');
    setEditLast(user.lastName || '');
    setEditRole(normalizeRole(user.role));
  };

  return (
    <div className="p-6 bg-slate-50/50 border-t border-slate-100">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-1">
            User Details
          </h4>
        </div>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            className="rounded-xl h-10 px-5 text-[14px] font-semibold"
            disabled={!isDirty || updateMutationObj.isPending}
            onClick={handleCancel}
          >
            Cancel
          </Button>
          <Button
            type="button"
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl h-10 px-5 text-[14px] font-semibold min-w-[80px]"
            disabled={!isDirty || updateMutationObj.isPending}
            onClick={handleSave}
          >
            {updateMutationObj.isPending ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>
      <div className="max-w-2xl space-y-4">
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
                {tenantRoles.map((r: { key: string; displayName: string }) => (
                  <SelectItem key={r.key} value={r.key}>
                    {r.displayName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {user.createdAt && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-600">Created At</label>
              <Input
                value={new Date(user.createdAt).toLocaleDateString('en-US', {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })}
                disabled
                className="h-9 rounded-lg text-sm bg-slate-100 text-slate-500 cursor-not-allowed"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
