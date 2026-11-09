import { Link, useLocation } from '@tanstack/react-router';
import type { LucideIcon } from 'lucide-react';

export interface NavItemProps {
  icon: LucideIcon;
  label: string;
  to: string;
  exact?: boolean;
}

export const NavItem = ({ icon: Icon, label, to, exact }: NavItemProps) => {
  const location = useLocation();
  const active = exact
    ? location.pathname === to
    : location.pathname === to || location.pathname.startsWith(`${to}/`);

  return (
    <Link
      to={to}
      className={`group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors ${
        active
          ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
          : 'text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground'
      }`}
    >
      <Icon
        className={`h-4 w-4 shrink-0 ${
          active
            ? 'text-sidebar-accent-foreground'
            : 'text-sidebar-foreground/75 group-hover:text-sidebar-accent-foreground'
        }`}
      />
      <span className="truncate">{label}</span>
    </Link>
  );
};
