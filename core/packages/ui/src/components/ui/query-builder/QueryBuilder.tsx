import { Button } from '@soopa/ui/components/ui/button';
import { Filter, Plus } from 'lucide-react';
import * as React from 'react';
import { Icon } from '../icon';
import { HStack, VStack } from '../layout';
import { FilterBadge } from './FilterBadge';
import { FilterForm } from './FilterForm';
import { FieldDef, FilterRule } from './types';

export interface QueryBuilderProps {
  fields: FieldDef[];
  rules: FilterRule[];
  onChange: (rules: FilterRule[]) => void;
}

export function QueryBuilder({ fields, rules, onChange }: QueryBuilderProps) {
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
    <VStack gap={3}>
      <HStack wrap="wrap" gap={2}>
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
          <Button variant="outline" onClick={() => setIsAdding(true)}>
            {hasRules ? (
              <Icon icon={Plus} size="sm" color="muted" />
            ) : (
              <Icon icon={Filter} size="sm" color="muted" />
            )}
            {hasRules ? 'Add Filter' : 'Filter'}
          </Button>
        )}
      </HStack>

      {isAdding && (
        <FilterForm fields={fields} onAdd={handleAddRule} onCancel={() => setIsAdding(false)} />
      )}
    </VStack>
  );
}
