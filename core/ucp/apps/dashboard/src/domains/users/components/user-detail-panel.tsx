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

function deriveUserFormValues(user: TenantUser): {
  readonly firstName: string;
  readonly lastName: string;
  readonly role: string;
} {
  return {
    firstName: user.firstName || '',
    lastName: user.lastName || '',
    role: normalizeRole(user.role),
  };
}

export function UserDetailPanel({
  user,
  tenantId,
  roles,
}: {
  user: TenantUser;
  tenantId: string;
  roles: { id: string; name: string }[];
}) {
  const baseline = deriveUserFormValues(user);
  const [editFirst, setEditFirst] = useState(baseline.firstName);
  const [editLast, setEditLast] = useState(baseline.lastName);
  const [editRole, setEditRole] = useState(baseline.role);
  const isDirty =
    editFirst !== baseline.firstName ||
    editLast !== baseline.lastName ||
    editRole !== baseline.role;

  useEffect(() => {
    const next = deriveUserFormValues(user);
    setEditFirst(next.firstName);
    setEditLast(next.lastName);
    setEditRole(next.role);
  }, [user]);

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
    setEditFirst(baseline.firstName);
    setEditLast(baseline.lastName);
    setEditRole(baseline.role);
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
            disabled={!isDirty || updateMutationObj.isPending}
            onClick={handleCancel}
          >
            Cancel
          </Button>
          <Button
            type="button"
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
              placeholder="First name"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600">Last Name</label>
            <Input
              value={editLast}
              onChange={(e) => setEditLast(e.target.value)}
              placeholder="Last name"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600">Email Address</label>
            <Input value={user.email} disabled />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600">Role</label>
            <Select value={editRole} onValueChange={(v) => setEditRole(v || '')}>
              <SelectTrigger className="w-full h-9 rounded-lg text-sm bg-white">
                <SelectValue placeholder="Select a role" />
              </SelectTrigger>
              <SelectContent>
                {roles.map((r: { id: string; name: string }) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.name}
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
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
