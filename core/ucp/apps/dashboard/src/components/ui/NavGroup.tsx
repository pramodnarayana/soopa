import { ChevronDown, ChevronRight } from 'lucide-react';
import React, { useState } from 'react';

export interface NavGroupProps {
  label: string;
  icon?: any;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}

export function NavGroup({ label, icon: Icon, defaultExpanded = false, children }: NavGroupProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className="flex flex-col gap-1 w-full">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        className="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 w-full group text-slate-600 hover:bg-slate-50 hover:text-slate-900 focus:outline-none"
      >
        {Icon && (
          <Icon className="w-5 h-5 text-slate-400 group-hover:text-slate-600 transition-colors" />
        )}
        <span className="font-medium text-sm text-left flex-1">{label}</span>
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-slate-600" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-slate-600" />
        )}
      </button>

      <div
        aria-hidden={!isExpanded}
        className={`overflow-hidden transition-all duration-300 ease-in-out ${
          isExpanded ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'
        }`}
        inert={!isExpanded ? true : undefined}
      >
        <div className="ml-5 mt-1 border-l-2 border-slate-100 pl-2 flex flex-col gap-1">
          {children}
        </div>
      </div>
    </div>
  );
}
