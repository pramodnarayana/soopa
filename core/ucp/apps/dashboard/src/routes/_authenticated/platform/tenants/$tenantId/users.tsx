import { Button } from '@soopa/ui/components/ui/button';
import { DataTable } from '@soopa/ui/components/ui/data-table';
import { Input } from '@soopa/ui/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { createFileRoute } from '@tanstack/react-router';
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Power,
  Send,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import React, { useState } from 'react';
import { toast } from 'sonner';
import { useGetRoles } from '@/domains/roles/api/queries';
import {
  useCreateTenantUser,
  useDeleteTenantUser,
  useToggleTenantUserStatus,
} from '@/domains/users/api/mutations';
import { TenantUser, useGetTenantUsers } from '@/domains/users/api/queries';

const USER_STATUS_THEME = {
  USER_STATE_ACTIVE: {
    badge: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    dot: 'bg-emerald-500',
    toggleBg: 'bg-emerald-50 border-emerald-200',
    toggleText: 'text-emerald-700',
    toggleSwitch: 'translate-x-[62px] bg-emerald-600 text-white',
    icon: 'text-white',
  },
  USER_STATE_INACTIVE: {
    badge: 'bg-slate-50 text-slate-700 border-slate-200',
    dot: 'bg-slate-400',
    toggleBg: 'bg-slate-100 border-slate-300',
    toggleText: 'text-slate-500',
    toggleSwitch: 'translate-x-0 bg-white text-slate-400',
    icon: 'text-slate-400',
  },
  unknown: {
    badge: 'bg-amber-50 text-amber-700 border-amber-200',
    dot: 'bg-amber-500',
    toggleBg: 'bg-slate-100 border-slate-300',
    toggleText: 'text-slate-500',
    toggleSwitch: 'translate-x-0 bg-white text-slate-400',
    icon: 'text-slate-400',
  },
};

const columnHelper = createColumnHelper<TenantUser>();

export const Route = createFileRoute('/_authenticated/platform/tenants/$tenantId/users')({
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
      columnHelper.accessor('state', {
        header: 'Status',
        cell: (info) => {
          const status = info.getValue() || 'unknown';
          const theme =
            USER_STATUS_THEME[status as keyof typeof USER_STATUS_THEME] ??
            USER_STATUS_THEME.unknown;
          const displayText =
            status === 'USER_STATE_ACTIVE'
              ? 'Active'
              : status === 'USER_STATE_INACTIVE'
                ? 'Inactive'
                : 'Unknown';
          return (
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${theme.badge}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${theme.dot}`} />
              {displayText}
            </span>
          );
        },
      }),
      columnHelper.display({
        id: 'actions',
        header: () => <span className="text-right w-full block pr-2">Actions</span>,
        cell: (info) => {
          const user = info.row.original;
          const status = user.state;
          const isActive = status === 'USER_STATE_ACTIVE';
          const isInactive = status === 'USER_STATE_INACTIVE';
          const isKnownStatus = isActive || isInactive;
          const isPending = toggleStatusMutationObj.isPending || deleteMutationObj.isPending;
          const theme =
            USER_STATUS_THEME[status as keyof typeof USER_STATUS_THEME] ??
            USER_STATUS_THEME.unknown;

          return (
            <div className="flex items-center gap-2 justify-end pr-2">
              <div className="flex items-center gap-4 mr-2" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  role="switch"
                  aria-checked={isActive}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isKnownStatus) {
                      handleToggleStatus(user.id, isActive);
                    }
                  }}
                  disabled={isPending || !isKnownStatus}
                  title={
                    !isKnownStatus
                      ? 'Unknown status - toggle disabled'
                      : isActive
                        ? 'Deactivate User'
                        : 'Activate User'
                  }
                  className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 ${theme.toggleBg} ${isPending || !isKnownStatus ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <span
                    className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-100 ' + theme.toggleText : 'opacity-0'}`}
                  >
                    Active
                  </span>
                  <span
                    className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-0' : 'opacity-100 ' + theme.toggleText}`}
                  >
                    Inactive
                  </span>
                  <span
                    aria-hidden="true"
                    className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${theme.toggleSwitch}`}
                  >
                    {isPending ? (
                      <Loader2 className="w-3 h-3 animate-spin text-slate-400" />
                    ) : (
                      <Power className={`w-3 h-3 ${theme.icon}`} />
                    )}
                  </span>
                </button>
              </div>

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
      <div className="space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-2xl font-bold tracking-tight text-foreground">Users</h3>
            <p className="text-[15px] text-muted-foreground mt-1">
              {users.length} user{users.length !== 1 ? 's' : ''} in this tenant
            </p>
          </div>
          <Button
            id="create-user-btn"
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2.5 bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm rounded-xl h-11 px-6 text-[15px] font-semibold"
          >
            <UserPlus className="w-5 h-5" />
            Create User
          </Button>
        </div>

        <div className="bg-card border border-border shadow-[0_2px_8px_rgb(0,0,0,0.04)] rounded-2xl overflow-hidden">
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
      </div>
    </>
  );
}
