import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, SlidersHorizontal } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { LibrarySchematic } from "@/components/LibrarySchematic";

type Variant = "umi" | "nonumi" | "race";


export const Route = createFileRoute("/bulk")({
  head: () => ({
    meta: [
      { title: "Bulk AIRR-seq data types" },
      {
        name: "description",
        content:
          "Select the sequencing design that matches your bulk BCR mRNA dataset.",
      },
    ],
  }),
  component: BulkDataTypes,
});

type DataType = {
  title: string;
  subtitle: string;
  variant: Variant;
};

const dataTypes: DataType[] = [
  {
    title: "UMI-barcoded Illumina MiSeq 2×250 BCR mRNA",
    subtitle:
      "Paired-end BCR mRNA data with UMI barcoding, V-region primer, C-region primer, and V(D)J structure.",
    variant: "umi",
  },
  {
    title: "Illumina MiSeq 2×250 BCR mRNA",
    subtitle:
      "Paired-end BCR mRNA data without UMI barcoding, with V-region primer, C-region primer, and V(D)J structure.",
    variant: "nonumi",
  },
  {
    title: "UMI-barcoded Illumina MiSeq 325+275 paired-end 5′ RACE BCR mRNA",
    subtitle:
      "UMI-barcoded 5′ RACE BCR mRNA data with template-switching sequence, leader, V(D)J, C-primer, and internal C-region structure.",
    variant: "race",
  },
];



const customWorkflow = {
  title: "Custom workflow",
  subtitle:
    "For non-standard bulk AIRR-seq designs that require user-defined preprocessing.",
};

function BulkDataTypes() {
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

        <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-3xl">
            <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              Bulk AIRR-seq data types
            </h1>
            <p className="mt-3 text-base leading-relaxed text-muted-foreground">
              Select the sequencing design that matches your bulk BCR mRNA dataset.
            </p>
          </div>
          <Link
            to="/pipeline/custom-bulk"
            className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
            style={{ boxShadow: "var(--shadow-card)" }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.boxShadow = "var(--shadow-card-hover)")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.boxShadow = "var(--shadow-card)")
            }
          >
            <SlidersHorizontal className="h-4 w-4" />
            Custom workflow
          </Link>
        </div>

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {dataTypes.map((d) => (
            <DataTypeCard key={d.title} data={d} />
          ))}
        </div>
      </main>
    </div>
  );
}

function DataTypeCard({ data }: { data: DataType }) {
  const linkProps = data.title.startsWith("UMI-barcoded Illumina MiSeq 2×250")
    ? ({ to: "/pipeline/umi-miseq-2x250" } as const)
    : data.title.startsWith("UMI-barcoded Illumina MiSeq 325+275")
      ? ({ to: "/pipeline/race-miseq-325-275" } as const)
      : data.title === "Illumina MiSeq 2×250 BCR mRNA"
        ? ({ to: "/pipeline/nonumi-miseq-2x250" } as const)
        : ({ to: "/pipeline-placeholder", search: { title: data.title } } as const);
  return (
    <Link
      {...linkProps}
      className="group flex h-full flex-col rounded-2xl border border-border bg-card p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40"
      style={{ boxShadow: "var(--shadow-card)" }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.boxShadow = "var(--shadow-card-hover)")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.boxShadow = "var(--shadow-card)")
      }
    >
      <h2 className="min-h-[3.25rem] text-lg font-semibold leading-snug tracking-tight text-foreground">
        {data.title}
      </h2>
      <p className="mt-2 min-h-[5rem] text-sm leading-relaxed text-muted-foreground">
        {data.subtitle}
      </p>

      <div
        className="mt-5 flex h-[150px] items-center justify-center rounded-xl border border-border/60 px-4 py-5"
        style={{
          background:
            "linear-gradient(135deg, oklch(0.985 0.012 220) 0%, oklch(0.97 0.02 200) 100%)",
        }}
      >
        <LibrarySchematic variant={data.variant} />
      </div>

      <div className="mt-auto pt-5 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
        Click to continue
        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
      </div>

    </Link>
  );
}

