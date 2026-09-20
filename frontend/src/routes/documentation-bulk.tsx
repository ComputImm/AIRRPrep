import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { ArrowRight, Pencil, Filter as FilterIcon } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { StepVisual } from "@/components/StepVisual";
import { stepStyle } from "@/lib/stepColors";
import {
  CATEGORY_INFO,
  FILTER_DOCS,
  TRANSFORM_DOCS,
  type StepCategory,
  type StepDoc,
} from "@/lib/stepDocs";

export const Route = createFileRoute("/documentation-bulk")({
  head: () => ({
    meta: [
      { title: "Component documentation — AIRR Preprocessor" },
      {
        name: "description",
        content:
          "Visual reference for every pipeline step: which steps edit the reads and which only filter or reorganize them.",
      },
    ],
  }),
  component: Documentation,
});

const BASE_LEGEND: { base: string; color: string }[] = [
  { base: "A", color: "#34d399" },
  { base: "C", color: "#60a5fa" },
  { base: "G", color: "#fbbf24" },
  { base: "T", color: "#fb7185" },
  { base: "N", color: "#cbd5e1" },
];

function Documentation() {
  const [active, setActive] = useState<StepDoc | null>(null);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />

      <main className="mx-auto max-w-6xl px-6 py-12">
        {/* hero */}
        <div className="max-w-3xl">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center rounded-full bg-card px-3 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border">
              Bulk AIRR-seq documentation
            </span>
            <Link
              to="/documentation-single-cell"
              className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              Single-cell documentation
            </Link>
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            What each component does
          </h1>
          <p className="mt-3 text-base leading-relaxed text-muted-foreground">
            Every preprocessing step falls into one of two groups. Some components{" "}
            <strong className="text-foreground">change the reads</strong> themselves; others only{" "}
            <strong className="text-foreground">filter or reorganize</strong> them without ever
            editing a record. Click any component to see a before → after illustration of exactly
            what it does.
          </p>
        </div>

        {/* base legend */}
        <div className="mt-7 flex flex-wrap items-center gap-4 rounded-xl border border-border bg-card px-4 py-3 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Legend</span>
          <span className="flex items-center gap-1.5">
            {BASE_LEGEND.map((b) => (
              <span
                key={b.base}
                className="flex h-5 w-5 items-center justify-center rounded font-mono text-[10px] text-slate-800"
                style={{ background: b.color }}
              >
                {b.base}
              </span>
            ))}
            <span className="ml-1">nucleotides (N = ambiguous)</span>
          </span>
          <span className="hidden h-4 w-px bg-border sm:block" />
          <span>
            <strong className="text-foreground">INPUT</strong> → step →{" "}
            <strong className="text-foreground">OUTPUT</strong>
          </span>
        </div>

        <CategorySection
          category="transform"
          docs={TRANSFORM_DOCS}
          icon={<Pencil className="h-4 w-4" />}
          onPick={setActive}
        />
        <CategorySection
          category="filter"
          docs={FILTER_DOCS}
          icon={<FilterIcon className="h-4 w-4" />}
          onPick={setActive}
        />
      </main>

      <StepDialog doc={active} onClose={() => setActive(null)} />
    </div>
  );
}

function CategorySection({
  category,
  docs,
  icon,
  onPick,
}: {
  category: StepCategory;
  docs: StepDoc[];
  icon: React.ReactNode;
  onPick: (d: StepDoc) => void;
}) {
  const info = CATEGORY_INFO[category];
  const tone =
    category === "transform"
      ? "bg-[oklch(0.95_0.05_25)] text-[oklch(0.45_0.18_25)] ring-[oklch(0.85_0.09_25)]"
      : "bg-[oklch(0.94_0.05_235)] text-[oklch(0.4_0.14_235)] ring-[oklch(0.82_0.09_235)]";

  return (
    <section className="mt-12">
      <div className="flex items-start gap-3">
        <div
          className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ring-1 ${tone}`}
        >
          {icon}
        </div>
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">{info.title}</h2>
          <p className="text-sm font-medium text-muted-foreground">{info.tagline}</p>
        </div>
      </div>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted-foreground">{info.blurb}</p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {docs.map((doc) => (
          <StepCard key={doc.name} doc={doc} onPick={onPick} />
        ))}
      </div>
    </section>
  );
}

function StepCard({ doc, onPick }: { doc: StepDoc; onPick: (d: StepDoc) => void }) {
  const style = stepStyle(doc.name);
  return (
    <button
      type="button"
      onClick={() => onPick(doc)}
      className="group flex flex-col items-start rounded-xl border border-border bg-card p-4 text-left transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md"
      style={{ borderLeftColor: style.color, borderLeftWidth: 4 }}
    >
      <div className="flex w-full items-center justify-between gap-2">
        <span
          className="rounded-md px-2 py-0.5 text-[11px] font-semibold"
          style={{ background: style.tint, color: style.text }}
        >
          {doc.family}
        </span>
        <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      <h3 className="mt-2 text-sm font-semibold text-foreground">{doc.title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{doc.short}</p>
      <code className="mt-2 text-[10px] text-muted-foreground/70">{doc.name}</code>
    </button>
  );
}

function StepDialog({ doc, onClose }: { doc: StepDoc | null; onClose: () => void }) {
  const style = doc ? stepStyle(doc.name) : null;
  return (
    <Dialog open={!!doc} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        {doc && style && (
          <>
            <DialogHeader>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className="rounded-md px-2 py-0.5 text-[11px] font-semibold"
                  style={{ background: style.tint, color: style.text }}
                >
                  {doc.family}
                </span>
                <span
                  className="rounded-md px-2 py-0.5 text-[11px] font-medium"
                  style={{
                    background:
                      doc.category === "transform" ? "oklch(0.95 0.05 25)" : "oklch(0.94 0.05 235)",
                    color:
                      doc.category === "transform" ? "oklch(0.45 0.18 25)" : "oklch(0.4 0.14 235)",
                  }}
                >
                  {doc.category === "transform" ? "Changes the reads" : "Filter / reorganize only"}
                </span>
                <code className="text-[11px] text-muted-foreground">{doc.name}</code>
              </div>
              <DialogTitle className="mt-1 text-xl">{doc.title}</DialogTitle>
            </DialogHeader>

            {/* visual */}
            <div className="rounded-xl border border-border bg-[oklch(0.99_0.003_240)] p-4">
              <StepVisual
                kind={doc.visual}
                accent={style}
                headerBefore={doc.headerBefore}
                headerAfter={doc.headerAfter}
              />
            </div>

            {/* what changes */}
            <div
              className="rounded-lg border-l-4 px-3 py-2 text-sm"
              style={{
                background: style.tint,
                color: style.text,
                borderLeftColor: style.color,
              }}
            >
              <span className="font-semibold">What changes: </span>
              {doc.changes}
            </div>

            {/* detail */}
            <div className="space-y-2">
              {doc.detail.map((p, i) => (
                <p key={i} className="text-sm leading-relaxed text-muted-foreground">
                  {p}
                </p>
              ))}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
