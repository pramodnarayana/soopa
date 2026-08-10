import { X } from 'lucide-react';
import { FieldDef, FilterRule } from './types';
import { getOperatorLabel } from './utils';

interface FilterBadgeProps {
  rule: FilterRule;
  field?: FieldDef;
  onRemove: () => void;
}

const getValueLabel = (rule: FilterRule, field?: FieldDef): string => {
  if (rule.operator === 'is_null' || rule.operator === 'is_not_null') return '';
  if (field?.type === 'enum' && field.options) {
    const opt = field.options.find((o) => String(o.value) === String(rule.value));
    if (opt) return opt.label;
  }
  return String(rule.value);
};

export function FilterBadge({ rule, field, onRemove }: FilterBadgeProps) {
  const fieldLabel = field?.label || rule.field;
  const operatorLabel = getOperatorLabel(rule.operator);
  const valueLabel = getValueLabel(rule, field);

  return (
    <div className="group flex items-center gap-1.5 bg-indigo-50/80 hover:bg-indigo-100/80 border border-indigo-200/60 text-indigo-700 px-2.5 py-1 rounded-lg text-sm transition-all duration-200 shadow-sm animate-in zoom-in-95 fade-in">
      <span className="font-medium">{fieldLabel}</span>
      <span className="text-indigo-400/80 text-xs font-mono">{operatorLabel}</span>
      {valueLabel && <span className="font-semibold">{valueLabel}</span>}
      <button
        type="button"
        onClick={onRemove}
        className="ml-1 -mr-1 p-0.5 rounded-md text-indigo-400 hover:text-indigo-700 hover:bg-indigo-200/50 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
