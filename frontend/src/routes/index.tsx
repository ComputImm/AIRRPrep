import { createFileRoute, Link } from "@tanstack/react-router";
import { Layers, Microscope, ArrowRight } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { WorkflowVisual } from "@/components/WorkflowVisual";
import { TagList } from "@/components/TagList";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "AIRR Data Preprocessor — Immune Repertoire Preprocessing" },
      {
        name: "description",
        content:
          "Prepare immune receptor repertoire sequencing data for downstream analysis through guided preprocessing workflows.",
      },
    ],
  }),
  component: Index,
});

function Index() {
  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main
        className="mx-auto max-w-6xl px-6 py-16 sm:py-24"
        style={{ background: "var(--gradient-hero)" }}
      >
        <div className="mx-auto max-w-3xl text-center">
          <span className="inline-flex items-center rounded-full bg-card px-3 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border">
            Guided bioinformatics workflows
          </span>
          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
            AIRR Data Preprocessor
          </h1>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground sm:text-lg">
            Prepare immune receptor repertoire sequencing data for downstream analysis
            through guided preprocessing workflows.
          </p>
        </div>

        <div className="mx-auto mt-14 grid max-w-5xl gap-6 md:grid-cols-2">
          <DataTypeCard
            icon={<Layers className="h-6 w-6" />}
            title="Bulk AIRR-seq"
            description="For pooled BCR/TCR repertoire sequencing data generated from bulk immune receptor libraries."
            steps={[]}
            tags={["Paired-end reads", "UMI support", "Primer processing", "Repertoire assembly"]}
            cta="Start bulk preprocessing"
            to="/bulk"
          />
          <DataTypeCard
            icon={<Microscope className="h-6 w-6" />}
            title="Single-cell AIRR"
            description="For single-cell V(D)J immune receptor data with cell barcodes, paired chains, and cell-level receptor annotations."
            steps={["Cell barcodes", "Chain pairing", "Receptor validation", "Final repertoire"]}
            tags={["Cell barcode", "Chain pairing", "TRA/TRB", "IGH/IGK/IGL"]}
            cta="Start single-cell preprocessing"
            to="/single-cell"
            accent="purple"
          />
        </div>
      </main>
    </div>
  );
}

function DataTypeCard({
  icon,
  title,
  description,
  steps,
  tags,
  cta,
  to,
  accent = "blue",
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  steps: string[];
  tags: string[];
  cta: string;
  to: string;
  accent?: "blue" | "purple";
}) {
  const iconBg =
    accent === "purple"
      ? "bg-[oklch(0.95_0.04_290)] text-[color:var(--accent-purple)] ring-[oklch(0.85_0.08_290)]"
      : "bg-[oklch(0.94_0.04_210)] text-primary ring-[oklch(0.85_0.08_220)]";

  return (
    <div
      className="group flex flex-col rounded-2xl border border-border bg-card p-7 transition-all duration-200 hover:-translate-y-0.5"
      style={{ boxShadow: "var(--shadow-card)" }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.boxShadow = "var(--shadow-card-hover)")
      }
      onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "var(--shadow-card)")}
    >
      <div
        className={`mb-5 flex h-12 w-12 items-center justify-center rounded-xl ring-1 ${iconBg}`}
      >
        {icon}
      </div>
      <h2 className="text-xl font-semibold tracking-tight text-foreground">{title}</h2>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</p>


      <div className="mt-7 flex-1" />
      <Link to={to}>
        <Button className="w-full justify-between" size="lg">
          {cta}
          <ArrowRight className="h-4 w-4" />
        </Button>
      </Link>
    </div>
  );
}
