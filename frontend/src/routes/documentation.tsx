import { createFileRoute, Link } from "@tanstack/react-router";
import { Layers, Microscope, ArrowRight } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/documentation")({
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
      <div className="fixed inset-x-0 top-0 z-50">
        <AppHeader />
      </div>

      <main
        className="mx-auto max-w-6xl px-6 py-16 sm:py-24"
        style={{
          background: "linear-gradient(180deg, #f0fdf4 0%, #dcfce7 100%)",
        }}
      >
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
            Documentation for AIRR Data Preprocessor
          </h1>
        </div>

        <div className="mx-auto mt-14 grid max-w-5xl gap-6 md:grid-cols-2">
          <DataTypeCard
            icon={<Layers className="h-6 w-6" />}
            title="Bulk AIRR-seq documentation"
            description="For pooled BCR/TCR repertoire sequencing data generated from bulk immune receptor libraries."
            cta="Go to bulk preprocessing documentation"
            to="/documentation-bulk"
          />

          <DataTypeCard
            icon={<Microscope className="h-6 w-6" />}
            title="Single-cell documentation"
            description="For single-cell V(D)J immune receptor data with cell barcodes, paired chains, and cell-level receptor annotations."
            cta="Go to single-cell preprocessing documentation"
            to="/documentation-single-cell"
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
  cta,
  to,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  cta: string;
  to: string;
}) {
  return (
    <div
      className="group flex flex-col rounded-2xl border border-border bg-card p-7 transition-all duration-200 hover:-translate-y-1"
      style={{ boxShadow: "var(--shadow-card)" }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.boxShadow = "var(--shadow-card-hover)")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.boxShadow = "var(--shadow-card)")
      }
    >
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-green-100 text-green-700 ring-1 ring-green-200">
        {icon}
      </div>

      <h2 className="text-xl font-semibold tracking-tight text-foreground">
        {title}
      </h2>

      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        {description}
      </p>

      <div className="mt-8 flex-1" />

      <Link to={to}>
        <Button
          size="lg"
          className="w-full justify-between bg-green-600 text-white hover:bg-green-700"
        >
          {cta}
          <ArrowRight className="h-4 w-4" />
        </Button>
      </Link>
    </div>
  );
}