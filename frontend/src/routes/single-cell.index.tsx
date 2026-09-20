import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { KIND_STYLE } from "@/lib/stepColors";
import {
  SINGLE_CELL_WORKFLOWS,
  type SingleCellWorkflow,
} from "@/lib/singleCellWorkflows";

export const Route = createFileRoute("/single-cell/")({
  head: () => ({
    meta: [
      { title: "Single-cell AIRR data types" },
      {
        name: "description",
        content:
          "Select the single-cell V(D)J input format that matches your data: Cell Ranger, TRUST4, raw 10x FASTQ/BAM, or a generic FASTA.",
      },
    ],
  }),
  component: SingleCellDataTypes,
});

function SingleCellDataTypes() {
  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-6 py-12">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to data type selection
        </Link>

        <div className="mt-6 max-w-3xl">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Single-cell AIRR data types
          </h1>
          <p className="mt-3 text-base leading-relaxed text-muted-foreground">
            Select the input format that matches your single-cell V(D)J data.
            Each one is converted into the same normalized FASTA + metadata
            table (AIRRPrep's internal schema), ready for re-annotation, e.g.
            with IMGT/HighV-QUEST.
          </p>
        </div>

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {SINGLE_CELL_WORKFLOWS.map((w) => (
            <WorkflowCard key={w.id} workflow={w} />
          ))}
        </div>
      </main>
    </div>
  );
}

function WorkflowCard({ workflow }: { workflow: SingleCellWorkflow }) {
  const style = KIND_STYLE[workflow.kind];

  return (
    <Link
      to="/single-cell/$formatId"
      params={{ formatId: workflow.id }}
      className="group flex h-full flex-col rounded-2xl border border-border bg-card p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40"
      style={{ boxShadow: "var(--shadow-card)" }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.boxShadow = "var(--shadow-card-hover)")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.boxShadow = "var(--shadow-card)")
      }
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="min-h-[3.25rem] text-lg font-semibold leading-snug tracking-tight text-foreground">
          {workflow.title}
        </h2>
        {workflow.needsTrust4 && (
          <span
            className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{ background: style.tint, color: style.text }}
          >
            TRUST4
          </span>
        )}
      </div>
      <p className="mt-2 min-h-[5rem] text-sm leading-relaxed text-muted-foreground">
        {workflow.subtitle}
      </p>

      {/* Inputs -> outputs, not the full pipeline: the whole diagram is
          380-520px tall, so any scale that fits a card renders the labels
          illegibly. What the card has to answer is "which files do I need",
          and the full flow is one click away on the workflow page. */}
      <div
        className="mt-5 flex h-[150px] flex-col items-center justify-center gap-1.5 overflow-hidden rounded-xl border border-border/60 px-4 py-4"
        style={{
          background:
            "linear-gradient(135deg, oklch(0.985 0.012 220) 0%, oklch(0.97 0.02 200) 100%)",
        }}
      >
        {workflow.inputs.map((input) => (
          <div
            key={input.role}
            className="w-full max-w-[13rem] truncate rounded-lg border bg-card/80 px-2.5 py-1 text-center text-[11px] font-medium"
            style={{ borderColor: style.border, color: style.text }}
          >
            {input.label}
            {!input.required && (
              <span className="font-normal opacity-60"> (optional)</span>
            )}
          </div>
        ))}

        <ThumbArrow steps={workflow.flow.steps.length} />

        <div className="w-full max-w-[13rem] rounded-lg border border-border bg-muted/70 px-2.5 py-1 text-center text-[11px] font-medium text-muted-foreground">
          final.fasta + metadata.tsv
        </div>
      </div>

      <div className="mt-auto inline-flex items-center gap-1.5 pt-5 text-sm font-medium text-primary">
        Click to continue
        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
      </div>
    </Link>
  );
}

/** Downward connector labelled with how many processing steps it stands in for. */
function ThumbArrow({ steps }: { steps: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex flex-col items-center">
        <div className="h-3 w-px bg-border" />
        <div className="h-0 w-0 border-l-[4px] border-r-[4px] border-t-[5px] border-l-transparent border-r-transparent border-t-border" />
      </div>
      <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/80">
        {steps} step{steps === 1 ? "" : "s"}
      </span>
    </div>
  );
}
