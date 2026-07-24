import { Loader2, Power, Trash2 } from 'lucide-react';
import React from 'react';

export interface SharedRowActionsProps {
  isActive: boolean;
  isUpdating: boolean;
  isDeleting: boolean;
  onToggleActive: (e: React.MouseEvent) => void;
  onDelete: (e: React.MouseEvent) => void;
  entityName?: string;
}

export function SharedRowActions({
  isActive,
  isUpdating,
  isDeleting,
  onToggleActive,
  onDelete,
  entityName = 'Item',
}: SharedRowActionsProps) {
  return (
    <div
      className="flex items-center gap-4 pr-4"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        role="switch"
        aria-checked={isActive}
        onClick={onToggleActive}
        disabled={isUpdating}
        title={isActive ? `Deactivate ${entityName}` : `Activate ${entityName}`}
        aria-label={isActive ? `Deactivate ${entityName}` : `Activate ${entityName}`}
        className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 ${isActive ? 'bg-emerald-50 border-emerald-200' : 'bg-slate-100 border-slate-300'} ${isUpdating ? 'opacity-50 cursor-wait' : ''}`}
      >
        <span
          className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-100 text-emerald-700' : 'opacity-0'}`}
        >
          Active
        </span>
        <span
          className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isActive ? 'opacity-0' : 'opacity-100 text-slate-500'}`}
        >
          Inactive
        </span>
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${isActive ? 'translate-x-[62px] bg-emerald-600 text-white' : 'translate-x-0 bg-white text-slate-400'}`}
        >
          {isUpdating ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Power className="w-3 h-3" />
          )}
        </span>
      </button>
      <button
        type="button"
        onClick={onDelete}
        disabled={isDeleting}
        className="p-2 text-red-600 bg-red-50 hover:bg-red-100 rounded-md transition-colors"
        title={`Delete ${entityName}`}
        aria-label={`Delete ${entityName}`}
      >
        {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
      </button>
    </div>
  );
}
