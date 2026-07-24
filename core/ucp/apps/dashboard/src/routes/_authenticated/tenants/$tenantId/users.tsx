import { createFileRoute } from '@tanstack/react-router';
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { ChevronDown, ChevronRight, Send, Trash2, UserPlus, Users, X } from 'lucide-react';
import React, { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useGetRoles } from '@/domains/roles/api/queries';
import {
  useCreateTenantUser,
  useDeleteTenantUser,
  useToggleTenantUserStatus,
} from '@/domains/users/api/mutations';
import { TenantUser, useGetTenantUsers } from '@/domains/users/api/queries';

const columnHelper = createColumnHelper<TenantUser>();

export const Route = createFileRoute('/_authenticated/tenants/$tenantId/users')({
  component: TenantUsersPage,
});

import { UserDetailPanel } from '@/domains/users/components/user-detail-panel';

// --- Main Page ---
function TenantUsersPage() {
  const { tenantId } = Route.useParams();

  const [showModal, setShowModal] = useState(false);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [selectedRole, setSelectedRole] = useState<string>('');

  const { data: users = [], isLoading } = useGetTenantUsers(tenantId);
  const { data: roles = [], isLoading: rolesLoading } = useGetRoles();

  const createMutationObj = useCreateTenantUser();
  const deleteMutationObj = useDeleteTenantUser();
  const toggleStatusMutationObj = useToggleTenantUserStatus();

  const handleCreateUser = () => {
    createMutationObj.mutate(
      { tenantId, firstName, lastName, email, role: selectedRole },
      {
        onSuccess: () => {
          resetModal();
          toast.success('User created successfully!');
        },
        onError: (error: Error) => toast.error(`Error creating user: ${error.message}`),
      },
    );
  };

  const handleDeleteUser = React.useCallback(
    (userId: string, email: string) => {
      if (confirm(`Delete user ${email}? This cannot be undone.`)) {
        deleteMutationObj.mutate(
          { tenantId, userId },
          {
            onSuccess: () => toast.success('User deleted.'),
            onError: (error: Error) => toast.error(`Error deleting user: ${error.message}`),
          },
        );
      }
    },
    [tenantId, deleteMutationObj],
  );

  const handleToggleStatus = React.useCallback(
    (userId: string, isActive: boolean) => {
      toggleStatusMutationObj.mutate(
        { tenantId, userId, action: isActive ? 'deactivate' : 'activate' },
        {
          onSuccess: (_, vars) => {
            toast.success(`User ${vars.action === 'activate' ? 'activated' : 'deactivated'}.`);
          },
          onError: (error: Error) => toast.error(`Error toggling status: ${error.message}`),
        },
      );
    },
    [tenantId, toggleStatusMutationObj],
  );

  const resetModal = () => {
    setShowModal(false);
    setFirstName('');
    setLastName('');
    setEmail('');
    setSelectedRole('');
  };

  const tenantRoles = roles;

  const columns = React.useMemo(
    () => [
      columnHelper.display({
        id: 'expand',
        cell: (info) => {
          const isExpanded = info.row.getIsExpanded();
          return (
            <div className="flex items-center justify-center w-4">
              {isExpanded ? (
                <ChevronDown className="w-4 h-4 text-slate-400" />
              ) : (
                <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-slate-400 transition-colors" />
              )}
            </div>
          );
        },
      }),
      columnHelper.accessor('email', {
        header: 'User',
        cell: (info) => {
          const user = info.row.original;
          const isActive = user.state === 'USER_STATE_ACTIVE';
          const initials = user.displayName
            ? user.displayName
                .split(' ')
                .map((n: string) => n[0])
                .join('')
                .toUpperCase()
                .slice(0, 2)
            : user.email.slice(0, 2).toUpperCase();
          return (
            <div className="flex items-center gap-3">
              <div
                className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold ${isActive ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-400'}`}
              >
                {initials}
              </div>
              <div>
                {user.displayName && (
                  <p className="font-medium text-sm text-slate-900">{user.displayName}</p>
                )}
                <p
                  className={`text-xs ${user.displayName ? 'text-slate-500' : 'font-medium text-sm text-slate-900'}`}
                >
                  {info.getValue()}
                </p>
              </div>
            </div>
          );
        },
      }),
      columnHelper.accessor('role', {
        header: 'Role',
        cell: (info) => {
          const role = info.getValue();
          if (role === 'Unknown' || !role) {
            return (
              <span className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ring-1 ring-inset bg-red-100 text-red-700 ring-red-600/30 shadow-sm animate-pulse">
                Error: Missing Role
              </span>
            );
          }
          const roleData = roles.find((r: { key: string; displayName: string }) => r.key === role);
          const label = roleData ? roleData.displayName : role;
          const isTenantAdmin = role === 'TenantAdmin';
          return (
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${isTenantAdmin ? 'bg-violet-50 text-violet-700 ring-violet-600/20' : 'bg-sky-50 text-sky-700 ring-sky-600/20'}`}
            >
              {label}
            </span>
          );
        },
      }),
      columnHelper.display({
        id: 'actions',
        header: () => <span className="text-right w-full block pr-2">Actions</span>,
        cell: (info) => {
          const user = info.row.original;
          const isActive = user.state === 'USER_STATE_ACTIVE';
          const isPending = toggleStatusMutationObj.isPending || deleteMutationObj.isPending;
          return (
            <div className="flex items-center gap-2 justify-end pr-2">
              {/* Active/Inactive inline pill toggle */}
              <button
                disabled={isPending}
                title={isActive ? 'Click to Deactivate' : 'Click to Activate'}
                onClick={(e) => {
                  e.stopPropagation();
                  handleToggleStatus(user.id, isActive);
                }}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all duration-150 cursor-pointer select-none
                ${
                  isActive
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-amber-50 hover:text-amber-700 hover:border-amber-200'
                    : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-emerald-50 hover:text-emerald-700 hover:border-emerald-200'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full transition-colors ${isActive ? 'bg-emerald-500' : 'bg-slate-400'}`}
                />
                {isActive ? 'Active' : 'Inactive'}
              </button>

              {/* Send Invite */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50"
                disabled={isPending}
                title="Send Invite Email"
                onClick={(e) => {
                  e.stopPropagation();
                  toast.info('Email invitations coming soon!');
                }}
              >
                <Send className="w-4 h-4" />
              </Button>

              {/* Delete */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-slate-400 hover:text-red-600 hover:bg-red-50"
                disabled={isPending}
                title="Delete User"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteUser(user.id, user.email);
                }}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>
          );
        },
      }),
    ],
    [roles, handleDeleteUser, handleToggleStatus, deleteMutationObj, toggleStatusMutationObj],
  );

  const table = useReactTable({
    data: users,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
  });

  return (
    <>
      {/* Create User Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={resetModal} />
          <div className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200/60">
            <div className="flex items-center justify-between p-6 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center">
                  <UserPlus className="w-5 h-5 text-indigo-600" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Create User</h2>
                  <p className="text-xs text-slate-500 mt-0.5">Add a user to this tenant</p>
                </div>
              </div>
              <button
                onClick={resetModal}
                className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">First Name</label>
                  <Input
                    id="user-first-name"
                    placeholder="John"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    className="rounded-lg"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">Last Name</label>
                  <Input
                    id="user-last-name"
                    placeholder="Doe"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    className="rounded-lg"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">Email Address</label>
                <Input
                  id="user-email"
                  type="email"
                  placeholder="john.doe@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="rounded-lg"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">Role</label>
                <Select
                  value={selectedRole}
                  onValueChange={(v) => setSelectedRole(v || '')}
                  disabled={rolesLoading}
                >
                  <SelectTrigger id="user-role" className="w-full rounded-lg">
                    <SelectValue placeholder="Select a role" />
                  </SelectTrigger>
                  <SelectContent>
                    {tenantRoles.map((role: { key: string; displayName: string }) => (
                      <SelectItem key={role.key} value={role.key}>
                        {role.displayName}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="rounded-lg bg-slate-50 border border-slate-200 px-4 py-3">
                <p className="text-xs text-slate-500">
                  A default password will be set. The user can update it after first login.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 px-6 pb-6">
              <Button variant="outline" onClick={resetModal} className="rounded-lg">
                Cancel
              </Button>
              <Button
                id="create-user-submit"
                className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5"
                disabled={
                  !firstName || !lastName || !email || !selectedRole || createMutationObj.isPending
                }
                onClick={handleCreateUser}
              >
                {createMutationObj.isPending ? (
                  <span className="flex items-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    Creating...
                  </span>
                ) : (
                  'Create User'
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Page content */}
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-900">Users</h3>
            <p className="text-sm text-slate-500 mt-0.5">
              {users.length} user{users.length !== 1 ? 's' : ''} in this tenant
            </p>
          </div>
          <Button
            id="create-user-btn"
            onClick={() => setShowModal(true)}
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg flex items-center gap-2 px-4 h-9"
          >
            <UserPlus className="w-4 h-4" />
            Create User
          </Button>
        </div>

        <DataTable
          table={table}
          columnsLength={columns.length}
          isLoading={isLoading}
          dataLength={users.length}
          emptyIcon={<Users className="w-8 h-8" />}
          emptyTitle="No Users Yet"
          emptyDescription="Create the first user for this tenant to get started."
          renderExpandedRow={(row) => (
            <UserDetailPanel user={row.original} tenantId={tenantId} tenantRoles={tenantRoles} />
          )}
        />
      </div>
    </>
  );
}
