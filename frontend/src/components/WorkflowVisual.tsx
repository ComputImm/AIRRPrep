import { ChevronRight } from "lucide-react";

export function WorkflowVisual({ steps }: { steps: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg bg-muted/60 px-3 py-2.5 text-xs font-medium text-muted-foreground">
      {steps.map((step, i) => (
        <div key={step} className="flex items-center gap-1.5">
          <span className="rounded-md bg-card px-2 py-1 text-foreground/80 shadow-sm ring-1 ring-border">
            {step}
          </span>
          {i < steps.length - 1 && (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60" />
          )}
        </div>
      ))}
    </div>
  );
}
