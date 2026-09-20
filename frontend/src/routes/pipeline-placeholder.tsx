import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, Upload } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Button } from "@/components/ui/button";

type PipelineSearch = { title?: string };

export const Route = createFileRoute("/pipeline-placeholder")({
  validateSearch: (search: Record<string, unknown>): PipelineSearch => ({
    title: typeof search.title === "string" ? search.title : undefined,
  }),
  head: () => ({
    meta: [{ title: "Pipeline details — Coming soon" }],
  }),
  component: Placeholder,
});

function Placeholder() {
  const { title } = Route.useSearch();
  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto flex max-w-3xl flex-col items-center px-6 py-24 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[oklch(0.94_0.04_210)] text-primary ring-1 ring-[oklch(0.85_0.08_220)]">
          <Upload className="h-7 w-7" />
        </div>
        <p className="mt-6 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Page 3
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-foreground">
          {title ?? "Pipeline details"}
        </h1>
        <p className="mt-3 text-base text-muted-foreground">
          The full pipeline diagram, required input files, upload buttons, and run
          controls will appear here.
        </p>
        <Link to="/bulk" className="mt-8">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" />
            Back to data types
          </Button>
        </Link>
      </main>
    </div>
  );
}
