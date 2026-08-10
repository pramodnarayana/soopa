import * as React from 'react';
import { SearchableSelect } from './searchable-select';

export interface ComboboxProps {
  options: string[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  emptyText?: string;
  disabled?: boolean;
  side?: 'top' | 'right' | 'bottom' | 'left';
}

export function Combobox({
  options,
  value,
  onChange,
  placeholder = 'Select option...',
  emptyText = 'No results found.',
  disabled = false,
  side = 'bottom',
}: ComboboxProps) {
  const searchableOptions = React.useMemo(() => {
    return options.map((opt) => ({
      label: opt,
      value: opt,
    }));
  }, [options]);

  return (
    <SearchableSelect
      options={searchableOptions}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      emptyText={emptyText}
      disabled={disabled}
      side={side}
      allowCustomValue={true}
    />
  );
}
