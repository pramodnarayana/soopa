import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import { Plus, X } from 'lucide-react';
import type { FilterRule } from '../types';

interface FilterBuilderProps {
  availableFields: { label: string; value: string }[];
  filters: FilterRule[];
  onChange: (filters: FilterRule[]) => void;
}

export function FilterBuilder({ availableFields, filters, onChange }: FilterBuilderProps) {
  const addFilter = () => {
    if (availableFields.length === 0) return;
    onChange([
      ...filters,
      { id: crypto.randomUUID(), field: availableFields[0].value, operator: 'eq', value: '' },
    ]);
  };

  const removeFilter = (index: number) => {
    const newFilters = [...filters];
    newFilters.splice(index, 1);
    onChange(newFilters);
  };

  const updateFilter = (index: number, key: keyof FilterRule, val: unknown) => {
    const newFilters = [...filters];
    newFilters[index] = { ...newFilters[index], [key]: val };
    onChange(newFilters);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <Button
          size="sm"
          variant="outline"
          onClick={addFilter}
          className="h-8 gap-1.5 text-xs bg-white"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Filter
        </Button>
      </div>

      {filters.length > 0 && (
        <div className="space-y-2">
          {filters.map((f, i) => (
            <div
              key={f.id || i}
              className="flex items-center justify-end gap-2 bg-white p-2 rounded-lg border border-slate-200"
            >
              <select
                className="flex h-9 w-[180px] items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
                value={f.field}
                onChange={(e) => updateFilter(i, 'field', e.target.value)}
              >
                {availableFields.map((field) => (
                  <option key={field.value} value={field.value}>
                    {field.label}
                  </option>
                ))}
              </select>

              <select
                className="flex h-9 w-[130px] items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
                value={f.operator}
                onChange={(e) => updateFilter(i, 'operator', e.target.value)}
              >
                <option value="eq">Equals</option>
                <option value="neq">Not Equals</option>
                <option value="contains">Contains</option>
              </select>

              <Input
                className="h-9 w-[180px]"
                placeholder="Value..."
                value={f.value as string}
                onChange={(e) => updateFilter(i, 'value', e.target.value)}
              />

              <Button
                size="icon"
                variant="ghost"
                className="h-9 w-9 text-slate-400 hover:text-red-500 hover:bg-red-50"
                onClick={() => removeFilter(i)}
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
