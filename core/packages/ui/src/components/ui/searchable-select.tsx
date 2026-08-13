import { Button } from '@soopa/ui/components/ui/button';
import { Check, ChevronsUpDown } from 'lucide-react';
import * as React from 'react';
import { cn } from '../../lib/utils';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from './command';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

export interface SearchableSelectOption {
  label: string | React.ReactNode;
  value: string;
  searchString?: string;
}

export interface SearchableSelectProps {
  options: SearchableSelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  emptyText?: string;
  disabled?: boolean;
  side?: 'top' | 'right' | 'bottom' | 'left';
  allowCustomValue?: boolean;
}

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = 'Select option...',
  emptyText = 'No results found.',
  disabled = false,
  side,
  allowCustomValue = false,
}: SearchableSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [inputValue, setInputValue] = React.useState('');

  const selectedOption = options.find((opt) => opt.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between font-normal text-left px-3 h-10 rounded-xl shadow-sm border-input hover:bg-accent hover:text-accent-foreground bg-background"
          disabled={disabled}
        >
          <span className="truncate flex-1 text-left">
            {selectedOption ? (
              selectedOption.label
            ) : allowCustomValue && value ? (
              value
            ) : (
              <span className="text-slate-400">{placeholder}</span>
            )}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 text-slate-400" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side={side}
        portaled={false}
        className="w-[var(--radix-popover-trigger-width)] p-0 rounded-xl shadow-lg border border-border overflow-hidden"
        align="start"
      >
        <Command>
          <CommandInput placeholder="Search..." value={inputValue} onValueChange={setInputValue} />
          <CommandList>
            <CommandEmpty>
              {allowCustomValue && inputValue ? (
                <button
                  type="button"
                  className="w-full px-3 py-2 text-sm cursor-pointer hover:bg-accent hover:text-accent-foreground text-foreground transition-colors m-1 rounded-md text-left"
                  onClick={() => {
                    onChange(inputValue);
                    setOpen(false);
                  }}
                >
                  Create "{inputValue}"
                </button>
              ) : (
                emptyText
              )}
            </CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.value}
                  className="cursor-pointer m-1 rounded-md aria-selected:bg-accent aria-selected:text-accent-foreground text-foreground transition-colors"
                  value={
                    option.searchString ||
                    (typeof option.label === 'string' ? option.label : option.value)
                  }
                  onSelect={() => {
                    onChange(option.value);
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      'mr-2 h-4 w-4',
                      value === option.value ? 'opacity-100' : 'opacity-0',
                    )}
                  />
                  {option.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
