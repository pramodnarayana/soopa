import * as React from "react"
import { Check, ChevronsUpDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"

export interface ComboboxProps {
  options: string[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  emptyText?: string
  disabled?: boolean
  side?: "top" | "right" | "bottom" | "left"
}

export function Combobox({ options, value, onChange, placeholder = "Select option...", emptyText = "No results found.", disabled = false, side = "bottom" }: ComboboxProps) {
  const [open, setOpen] = React.useState(false)
  const [inputValue, setInputValue] = React.useState(value || "")

  // Sync internal input state with external value changes
  React.useEffect(() => {
    setInputValue(value || "")
  }, [value])

  const handleSelect = (currentValue: string) => {
    setInputValue(currentValue)
    onChange(currentValue)
    setOpen(false)
  }

  const handleInputChange = (e: string) => {
    setInputValue(e)
    onChange(e)
  }

  const optionsMap = React.useMemo(() => {
    return options.reduce((acc, opt) => {
      acc[opt.toLowerCase()] = opt;
      return acc;
    }, {} as Record<string, string>);
  }, [options]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between font-normal text-left px-3 h-10 shadow-sm"
          disabled={disabled}
        >
          <span className="truncate flex-1">
            {inputValue || <span className="text-muted-foreground">{placeholder}</span>}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent side={side} portaled={false} className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
        <Command>
          <CommandInput
            placeholder={placeholder}
            value={inputValue}
            onValueChange={handleInputChange}
          />
          <CommandList>
            <CommandEmpty>
              {inputValue ? (
                <div
                  className="px-2 py-1.5 text-sm cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800 rounded-sm"
                  onClick={() => {
                    onChange(inputValue);
                    setOpen(false);
                  }}
                >
                  Use "{inputValue}"
                </div>
              ) : (
                emptyText
              )}
            </CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option}
                  value={option}
                  onSelect={(currentValue) => {
                    // Shadcn CommandItem lowercases the value by default unless specified
                    // We need to pass the original case string back
                    const originalCaseOption = optionsMap[currentValue] || currentValue;
                    handleSelect(originalCaseOption);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      inputValue === option ? "opacity-100" : "opacity-0"
                    )}
                  />
                  {option}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
