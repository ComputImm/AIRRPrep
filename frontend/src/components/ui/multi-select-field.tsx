import { useState } from "react";
import { ChevronsUpDown, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Multi-value field-name picker: a checkable list of the pipeline's known
 * fields at this stage, plus a free-text row for one not yet in that list
 * (an unconfident lane, or a field about to be created by this very step).
 *
 * Value stays the same comma-joined string the plain array `<Input>` already
 * used, so this only changes how the value is edited, not the wire format —
 * DraftDialog's submit-time parsing needs no changes.
 */
export function MultiSelectField({
  value,
  onChange,
  options,
  placeholder = "Select fields…",
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [customInput, setCustomInput] = useState("");
  const selected = parseList(value);

  const setSelected = (next: string[]) => onChange(next.join(", "));

  const toggle = (name: string) => {
    if (selected.includes(name)) setSelected(selected.filter((s) => s !== name));
    else setSelected([...selected, name]);
  };

  const addCustom = () => {
    const name = customInput.trim().toUpperCase();
    if (name && !selected.includes(name)) setSelected([...selected, name]);
    setCustomInput("");
  };

  // A field already chosen (e.g. loaded from a saved pipeline predating this
  // dropdown, or picked while the lane was unconfident) but absent from the
  // known list is still shown, checked and removable, so nothing silently
  // drops off the value just because the registry didn't know it.
  const extra = selected.filter((s) => !options.includes(s));
  const allOptions = [...options, ...extra];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="h-9 w-full justify-between rounded-md border-input px-3 py-1 text-sm font-normal shadow-xs"
        >
          <span className="truncate text-left text-foreground">
            {selected.length ? selected.join(", ") : (
              <span className="text-muted-foreground">{placeholder}</span>
            )}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command>
          <CommandList>
            <CommandEmpty>No known fields yet — add one below.</CommandEmpty>
            <CommandGroup>
              {allOptions.map((name) => (
                <CommandItem key={name} onSelect={() => toggle(name)}>
                  <Checkbox checked={selected.includes(name)} className="pointer-events-none mr-1" />
                  {name}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
          <div className="flex items-center gap-1.5 border-t border-border p-1.5">
            <input
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addCustom();
                }
              }}
              placeholder="Custom field…"
              className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 px-2"
              onClick={addCustom}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
