import { Button } from '@soopa/ui/components/ui/button';
import { Filter, Plus } from 'lucide-react';
import * as React from 'react';
import { cn } from '../../../lib/utils';
import { FilterBadge } from './FilterBadge';
import { FilterForm } from './FilterForm';
import { FieldDef, FilterRule } from './types';

export interface QueryBuilderProps {
  fields: FieldDef[];
  rules: FilterRule[];
  onChange: (rules: FilterRule[]) => void;
  className?: string;
}

export function QueryBuilder({ fields, rules, onChange, className }: QueryBuilderProps) {
  const [isAdding, setIsAdding] = React.useState(false);

  const handleAddRule = (rule: FilterRule) => {
    onChange([...rules, rule]);
    setIsAdding(false);
  };

  const handleRemoveRule = (id: string) => {
    onChange(rules.filter((r) => r.id !== id));
  };

  const hasRules = rules.length > 0;

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {/* Active Rules List */}
      <div className="flex flex-wrap items-center gap-2">
        {rules.map((rule) => {
          const field = fields.find((f) => f.id === rule.field);
          return (
            <FilterBadge
              key={rule.id}
              rule={rule}
              field={field}
              onRemove={() => handleRemoveRule(rule.id)}
            />
          );
        })}

        {!isAdding && (
          <Button
            variant="outline"
            onClick={() => setIsAdding(true)}
            className="h-9 px-4 gap-2 text-sm font-medium bg-white text-slate-700 border-dashed hover:border-solid hover:bg-slate-50 transition-all shadow-sm rounded-lg"
          >
            {hasRules ? (
              <Plus className="w-4 h-4 text-slate-500" />
            ) : (
              <Filter className="w-4 h-4 text-slate-500" />
            )}
            {hasRules ? 'Add Filter' : 'Filter'}
          </Button>
        )}
      </div>

      {/* Add Rule Form (Inline) */}
      {isAdding && (
        <div className="mt-1">
          <FilterForm fields={fields} onAdd={handleAddRule} onCancel={() => setIsAdding(false)} />
        </div>
      )}
    </div>
  );
}
