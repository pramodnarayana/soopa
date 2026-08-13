import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { Check, X } from 'lucide-react';
import * as React from 'react';
import { Icon } from '../icon';
import { HStack, VStack } from '../layout';
import { FieldDef, FilterOperator, FilterRule } from './types';
import { getOperatorLabel } from './utils';

interface FilterFormProps {
  fields: FieldDef[];
  onAdd: (rule: FilterRule) => void;
  onCancel: () => void;
}

const getOperatorsForType = (type: string = 'text'): { label: string; value: FilterOperator }[] => {
  switch (type) {
    case 'number':
    case 'date':
      return [
        { label: 'Equals', value: 'eq' },
        { label: 'Not Equals', value: 'neq' },
        { label: 'Greater Than', value: 'gt' },
        { label: 'Less Than', value: 'lt' },
        { label: 'Greater or Equal', value: 'gte' },
        { label: 'Less or Equal', value: 'lte' },
        { label: 'Is Null', value: 'is_null' },
        { label: 'Is Not Null', value: 'is_not_null' },
      ];
    case 'boolean':
      return [
        { label: 'Equals', value: 'eq' },
        { label: 'Is Null', value: 'is_null' },
        { label: 'Is Not Null', value: 'is_not_null' },
      ];
    case 'enum':
      return [
        { label: 'Equals', value: 'eq' },
        { label: 'Not Equals', value: 'neq' },
        { label: 'In', value: 'in' },
        { label: 'Not In', value: 'not_in' },
      ];
    case 'text':
    default:
      return [
        { label: 'Equals', value: 'eq' },
        { label: 'Not Equals', value: 'neq' },
        { label: 'Contains', value: 'contains' },
        { label: 'Not Contains', value: 'not_contains' },
        { label: 'Is Null', value: 'is_null' },
        { label: 'Is Not Null', value: 'is_not_null' },
      ];
  }
};

export function FilterForm({ fields, onAdd, onCancel }: FilterFormProps) {
  const [selectedFieldId, setSelectedFieldId] = React.useState<string>(fields[0]?.id || '');
  const [operator, setOperator] = React.useState<FilterOperator>('eq');
  const [value, setValue] = React.useState<string>('');

  const selectedField = React.useMemo(
    () => fields.find((f) => f.id === selectedFieldId),
    [fields, selectedFieldId],
  );

  const operators = React.useMemo(() => {
    if (selectedField?.operators && selectedField.operators.length > 0) {
      return selectedField.operators.map((op) => ({
        label: getOperatorLabel(op),
        value: op,
      }));
    }
    return getOperatorsForType(selectedField?.type);
  }, [selectedField]);

  // Reset operator and value when field changes
  React.useEffect(() => {
    let defaultOp: FilterOperator = 'eq';
    if (selectedField?.operators && selectedField.operators.length > 0) {
      defaultOp = selectedField.operators[0];
    } else {
      defaultOp = getOperatorsForType(selectedField?.type)[0]?.value || 'eq';
    }
    setOperator(defaultOp);
    setValue('');
  }, [selectedField]);

  const handleAdd = () => {
    if (!selectedFieldId || !operator) return;

    // For is_null / is_not_null, value is not needed
    if (operator !== 'is_null' && operator !== 'is_not_null' && value === '') return;

    onAdd({
      id: crypto.randomUUID(),
      field: selectedFieldId,
      operator,
      value: operator === 'is_null' || operator === 'is_not_null' ? null : value,
    });
  };

  const requiresValue = operator !== 'is_null' && operator !== 'is_not_null';

  return (
    <div className="bg-slate-50/50 p-2 rounded-xl border border-slate-200/60 shadow-sm animate-in fade-in slide-in-from-top-2">
      <HStack wrap="wrap" gap={2}>
        <Select value={selectedFieldId} onValueChange={(v) => setSelectedFieldId(v || '')}>
          <SelectTrigger className="w-[180px] bg-white">
            <SelectValue placeholder="Select field">{selectedField?.label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {fields.map((f) => (
              <SelectItem key={f.id} value={f.id}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={operator} onValueChange={(val) => setOperator(val as FilterOperator)}>
          <SelectTrigger className="w-[160px] bg-white">
            <SelectValue placeholder="Condition">
              {operators.find((o) => o.value === operator)?.label}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {operators.map((op) => (
              <SelectItem key={op.value} value={op.value}>
                {op.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {requiresValue && (
          <div className="w-[200px] shrink-0">
            {selectedField?.type === 'enum' && selectedField.options ? (
              operator === 'in' || operator === 'not_in' ? (
                <Input
                  type="text"
                  className="bg-white h-10 w-full"
                  placeholder="Comma-separated values..."
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleAdd();
                    if (e.key === 'Escape') onCancel();
                  }}
                />
              ) : (
                <Select value={value} onValueChange={(v) => setValue(v || '')}>
                  <SelectTrigger className="w-full bg-white">
                    <SelectValue placeholder="Select value">
                      {selectedField.options.find((o) => String(o.value) === String(value))?.label}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {selectedField.options.map((opt) => (
                      <SelectItem key={String(opt.value)} value={String(opt.value)}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )
            ) : (
              <Input
                type={selectedField?.type === 'number' ? 'number' : 'text'}
                className="bg-white h-10 w-full"
                placeholder="Value..."
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAdd();
                  if (e.key === 'Escape') onCancel();
                }}
              />
            )}
          </div>
        )}

        <HStack gap={1} className="shrink-0">
          <Button
            size="icon"
            variant="ghost"
            onClick={handleAdd}
            className="h-10 w-10 text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 rounded-lg"
            disabled={requiresValue && !value}
            aria-label="Add filter"
          >
            <Icon icon={Check} size="sm" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={onCancel}
            className="h-10 w-10 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg"
            aria-label="Cancel filter"
          >
            <Icon icon={X} size="sm" />
          </Button>
        </HStack>
      </HStack>
    </div>
  );
}
