import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { ArrowRight, Boxes, Dna, FileQuestion } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SingleCellFormatFlow } from "@/components/SingleCellFormatFlow";
import { KIND_STYLE } from "@/lib/stepColors";
import {
  CATEGORY_INFO,
  SINGLE_CELL_FORMAT_DOCS,
  type SingleCellCategory,
  type SingleCellFormatDoc,
} from "@/lib/singleCellDocs";

// NOTE: intentionally a flat filename (hyphen), not "documentation.single-cell.tsx"
// (dot). TanStack Router's file-based routing treats a dot-segment as a CHILD
// of "documentation.tsx", but documentation.tsx is a full leaf page with no
// <Outlet/> -- nesting under it just renders the parent's own content and
// this page never shows. A flat "/documentation-single-cell" path sidesteps
// that without having to turn documentation.tsx into a layout route.
export const Route = createFileRoute("/documentation-single-cell")({
  head: () => ({
    meta: [
      { title: "Single-cell component documentation — AIRR Preprocessor" },
      {
        name: "description",
        content:
          "Visual reference for every single-cell input format: exactly which files go in, what the adapter extracts and strips, and what comes out.",
      },
    ],
  }),
  component: SingleCellDocumentation,
});

const CATEGORY_ORDER: SingleCellCategory[] = ["cellranger", "raw_reads", "generic"];
const CATEGORY_ICON: Record<SingleCellCategory, React.ReactNode> = {
  cellranger: <Boxes className="h-4 w-4" />,
  raw_reads: <Dna className="h-4 w-4" />,
  generic: <FileQuestion className="h-4 w-4" />,
};

function SingleCellDocumentation() {
  const [active, setActive] = useState<SingleCellFormatDoc | null>(null);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />

      <main className="mx-auto max-w-6xl px-6 py-12">
        <div className="max-w-3xl">
          <div className="flex items-center gap-2">
            <Link
              to="/documentation-bulk"
              className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              Bulk AIRR-seq documentation
            </Link>
            <span className="inline-flex items-center rounded-full bg-card px-3 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border">
              Single-cell documentation 
            </span>

          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            What each input format does
          </h1>
          <p className="mt-3 text-base leading-relaxed text-muted-foreground">
            Single-cell inputs are <strong className="text-foreground">detected automatically</strong>,
            not composed step-by-step like bulk. Every format below is handled by its own adapter that
            converts its specific files into one normalized record. Click a card to see exactly which
            files go in, what gets extracted, which annotation fields are deliberately dropped, and what
            comes out.
          </p>
        </div>

        <div className="mt-7 flex flex-wrap items-center gap-4 rounded-xl border border-border bg-card px-4 py-3 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Legend</span>
          <span>
            <strong className="text-foreground">Input file(s)</strong> → adapter steps →{" "}
            <strong className="text-foreground">final.fasta + metadata.tsv</strong>
          </span>
          <span className="hidden h-4 w-px bg-border sm:block" />
          <span>
            Fields like <code className="text-muted-foreground/90">v_call</code>,{" "}
            <code className="text-muted-foreground/90">junction</code>, and their vendor-specific
            equivalents are never carried into the output — IMGT infers them downstream.
          </span>
        </div>

        {CATEGORY_ORDER.map((category) => (
          <CategorySection
            key={category}
            category={category}
            docs={SINGLE_CELL_FORMAT_DOCS.filter((d) => d.category === category)}
            onPick={setActive}
          />
        ))}
      </main>

      <FormatDialog doc={active} onClose={() => setActive(null)} />
    </div>
  );
}

function CategorySection({
  category,
  docs,
  onPick,
}: {
  category: SingleCellCategory;
  docs: SingleCellFormatDoc[];
  onPick: (d: SingleCellFormatDoc) => void;
}) {
  const info = CATEGORY_INFO[category];

  return (
    <section className="mt-12">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[color:var(--accent-purple)]/10 text-[color:var(--accent-purple)] ring-1 ring-[color:var(--accent-purple)]/20">
          {CATEGORY_ICON[category]}
        </div>
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">{info.title}</h2>
          <p className="text-sm font-medium text-muted-foreground">{info.tagline}</p>
        </div>
      </div>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted-foreground">{info.blurb}</p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {docs.map((doc) => (
          <FormatCard key={doc.id} doc={doc} onPick={onPick} />
        ))}
      </div>
    </section>
  );
}

function FormatCard({
  doc,
  onPick,
}: {
  doc: SingleCellFormatDoc;
  onPick: (d: SingleCellFormatDoc) => void;
}) {
  const style = KIND_STYLE[doc.kind];
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
          {doc.id}
        </span>
        <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      <h3 className="mt-2 text-sm font-semibold text-foreground">{doc.title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{doc.short}</p>
    </button>
  );
}

function FormatDialog({
  doc,
  onClose,
}: {
  doc: SingleCellFormatDoc | null;
  onClose: () => void;
}) {
  const style = doc ? KIND_STYLE[doc.kind] : null;
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
                  {doc.id}
                </span>
              </div>
              <DialogTitle className="mt-1 text-xl">{doc.title}</DialogTitle>
            </DialogHeader>

            <div className="rounded-xl border border-border bg-[oklch(0.99_0.003_240)] p-6">
              <SingleCellFormatFlow spec={doc.flow} />
            </div>

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
