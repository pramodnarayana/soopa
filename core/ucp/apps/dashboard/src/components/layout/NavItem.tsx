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
      className={`group relative flex items-center gap-4 overflow-hidden rounded-lg px-4 py-3 transition-all duration-300 ease-out ${
        active
          ? 'bg-primary/5 font-medium text-primary'
          : 'text-muted-foreground hover:bg-slate-100/50 hover:text-foreground'
      }`}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-6 w-1.5 -translate-y-1/2 rounded-r-full bg-primary shadow-[0_0_8px_rgba(79,70,229,0.4)]" />
      )}
      <Icon
        className={`h-5 w-5 transition-transform duration-300 group-hover:scale-110 ${
          active ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'
        }`}
      />
      <span className="text-[17px] tracking-wide">{label}</span>
    </Link>
  );
};
