import { ChevronDown, ChevronRight } from 'lucide-react';
import React, { useState } from 'react';

export interface NavGroupProps {
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}

export function NavGroup({ label, icon: Icon, defaultExpanded = false, children }: NavGroupProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className="flex w-full flex-col gap-0.5">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        className="group flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-sidebar-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground focus:outline-none"
      >
        {Icon ? (
          <Icon className="h-4 w-4 shrink-0 text-sidebar-foreground/75 transition-colors group-hover:text-sidebar-accent-foreground" />
        ) : null}
        <span className="flex-1 truncate text-left text-sm">{label}</span>
        {isExpanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
      </button>

      <div
        aria-hidden={!isExpanded}
        className={`overflow-hidden transition-all duration-200 ease-in-out ${
          isExpanded ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'
        }`}
        inert={!isExpanded ? true : undefined}
      >
        <div className="mt-0.5 ml-3.5 flex flex-col gap-0.5 border-l border-sidebar-border pl-2">
          {children}
        </div>
      </div>
    </div>
  );
}
