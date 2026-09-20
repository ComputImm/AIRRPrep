import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Upload,
  FileUp,
  AlertCircle,
  Loader2,
  PlayCircle,
  ShieldCheck,
} from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LibrarySchematic } from "@/components/LibrarySchematic";
import { useQueryClient } from "@tanstack/react-query";
import { useFileUpload } from "@/hooks/useFileUpload";
import { useStartJob } from "@/hooks/useStartJob";
import { useJobProgress } from "@/hooks/useJobProgress";
import { useJobLaunch } from "@/hooks/useJobLaunch";
import { useResumedJob } from "@/hooks/useResumedJob";
import { useValidatePipeline } from "@/hooks/useValidatePipeline";
import { useSessionHistory } from "@/hooks/useSessionHistory";
import { getSessionId } from "@/api/session";
import { readApiError } from "@/api/jobs";
import { JobLaunchGate, TrackingCodeCard } from "@/components/JobLaunchGate";
import { PipelineProgress } from "@/components/PipelineProgress";
import { StepFunnel } from "@/components/StepFunnel";
import { SessionHistory } from "@/components/SessionHistory";
import {
  buildUmi2x250Payload,
  UMI_2X250_PROGRESS_STEPS,
} from "@/pipelines/umimiseq2x250";

export const Route = createFileRoute("/pipeline/umi-miseq-2x250")({
  head: () => ({
    meta: [
      { title: "UMI-barcoded Illumina MiSeq 2×250 BCR mRNA — Pipeline" },
      {
        name: "description",
        content:
          "Preprocessing workflow for paired-end bulk BCR mRNA repertoire data with UMI barcodes.",
      },
    ],
  }),
  component: PipelinePage,
});

type InputKey = "read1" | "read2" | "vprimer" | "cprimer";
type UploadState = "default" | "uploading" | "uploaded" | "error";

type InputConfig = {
  key: InputKey;
  label: string;
  helper: string;
  accept: string;
  highlights: string[]; // workflow step ids
};

const INPUTS: InputConfig[] = [
  {
    key: "read1",
    label: "Read 1",
    helper: "FASTQ file for read 1 (C-Region primer side)",
    accept: ".fastq,.fq,.gz",
    highlights: ["read1", "assemble"],
  },
  {
    key: "read2",
    label: "Read 2",
    helper: "FASTQ file for read 2 (V-Segment primer side)",
    accept: ".fastq,.fq,.gz",
    highlights: ["read2", "assemble"],
  },
  {
    key: "cprimer",
    label: "C-primer",
    helper: "Primer file for C-region primer sequences",
    accept: ".fasta,.fa,.txt",
    highlights: ["maskC"],
  },
  {
    key: "vprimer",
    label: "V-primer",
    helper: "Primer file for V-region primer sequences",
    accept: ".fasta,.fa,.txt",
    highlights: ["maskV"],
  },
  
];

type FlowNode = {
  id: string;
  label: string;
  sub?: string;
  kind: "assemble" | "process" | "collapse";
  log?: { label: string; side: "left" | "right" };
};

const FLOW: FlowNode[] = [
  { id: "assemble", label: "AssemblePairs align", kind: "assemble",  },
  { id: "filterseq", label: "FilterSeq quality", kind: "process",  },
  { id: "maskC", label: "MaskPrimers score", sub: "C-region primer", kind: "process", },
  { id: "maskV", label: "MaskPrimers score", sub: "V-segment primer", kind: "process", },
  { id: "collapse", label: "CollapseSeq", kind: "collapse" },
  { id: "split", label: "SplitSeq group", kind: "collapse" },
  { id: "table", label: "ParseHeaders table", kind: "collapse" },
];

type FileEntry = { id?: string; name: string; state: UploadState };

function PipelinePage() {
  const [files, setFiles] = useState<Record<InputKey, FileEntry | null>>({
    read1: null,
    read2: null,
    vprimer: null,
    cprimer: null,
  });
  const [hoverKey, setHoverKey] = useState<InputKey | null>(null);
  const [validated, setValidated] = useState(false);
  const [validating, setValidating] = useState(false);

  const queryClient = useQueryClient();
  const uploadMutation = useFileUpload();
  const startJobMutation = useStartJob();
  const validateMutation = useValidatePipeline();
  const [jobId, setJobId] = useState<string | null>(null);
  const [trackingCode, setTrackingCode] = useState<string | null>(null);
  const progress = useJobProgress(jobId, UMI_2X250_PROGRESS_STEPS.length);
  const historyQuery = useSessionHistory();
  const [validationError, setValidationError] = useState<string | null>(null);

  // Arriving here from a tracking code (/track) shows that run's progress.
  useResumedJob(jobId, setJobId);

  const buildPayload = (sessionId: string) =>
    buildUmi2x250Payload(
      {
        read1: files.read1,
        read2: files.read2,
        cprimer: files.cprimer,
        vprimer: files.vprimer,
      },
      { sessionId, convertToFasta: false },
    );

  const launch = useJobLaunch({
    // The estimator wants the same files and steps the run itself will use,
    // so it is sized off the very payload that is about to be submitted.
    buildEstimate: () => {
      const { file_ids, steps } = buildPayload("");
      return { file_ids, steps };
    },
    start: async () => {
      const sessionId = await getSessionId();
      return startJobMutation.mutateAsync({
        ...buildPayload(sessionId),
        route: "/pipeline/umi-miseq-2x250",
        label: "UMI-barcoded MiSeq 2×250",
      });
    },
    onStarted: (result) => {
      // The gate dialog can sit between the click and the start, so scroll
      // again once the run is really under way.
      window.scrollTo({ top: 0, behavior: "smooth" });
      setJobId(result.job_id);
      setTrackingCode(result.tracking_code ?? null);
      queryClient.invalidateQueries({ queryKey: ["session-history"] });
    },
  });

  /**
   * Run, having first scrolled back to the top.
   *
   * The button is at the bottom of a long page and starting a run replaces the
   * view with the progress panel, which renders above the fold.
   */
  const handleRun = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    launch.launch();
  };

  const handleReset = () => {
    setJobId(null);
    setTrackingCode(null);
    setValidated(false);
  };

  const allUploaded = useMemo(
    () => INPUTS.every((i) => files[i.key]?.state === "uploaded"),
    [files],
  );

  // Steps highlighted because corresponding file was just uploaded (persistent glow)
  const uploadedHighlightedSteps = useMemo(() => {
    const set = new Set<string>();
    INPUTS.forEach((i) => {
      if (files[i.key]?.state === "uploaded") {
        i.highlights.forEach((h) => set.add(h));
      }
    });
    return set;
  }, [files]);

  // Steps highlighted via hover preview
  const hoverHighlightedSteps = useMemo(() => {
    if (!hoverKey) return new Set<string>();
    const cfg = INPUTS.find((i) => i.key === hoverKey);
    return new Set<string>(cfg?.highlights ?? []);
  }, [hoverKey]);

  const handleUpload = async (key: InputKey, file: File) => {
    setFiles((prev) => ({ ...prev, [key]: { name: file.name, state: "uploading" } }));
    setValidated(false);
    try {
      const result = await uploadMutation.mutateAsync(file);
      setFiles((prev) => ({
        ...prev,
        [key]: { id: result.file_id, name: file.name, state: "uploaded" },
      }));
    } catch {
      setFiles((prev) => ({ ...prev, [key]: { name: file.name, state: "error" } }));
    }
  };

  const handleValidate = async () => {
    setValidating(true);
    setValidationError(null);
    try {
      const sessionId = await getSessionId();
      const payload = buildPayload(sessionId);
      const summary = await validateMutation.mutateAsync({
        chains: 2,
        file_ids: payload.file_ids,
        steps: payload.steps,
      });
      const missing = summary.missing_required_uploads ?? [];
      if (missing.length > 0) {
        setValidationError(
          "Missing required uploads: " +
            missing.map((m) => `${m.step_name}.${m.param}`).join(", "),
        );
        setValidated(false);
      } else {
        setValidated(true);
      }
    } catch (e) {
      setValidationError(readApiError(e));
      setValidated(false);
    } finally {
      setValidating(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-6 py-10">
        <Link
          to="/bulk"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to bulk AIRR-seq data types
        </Link>

        <header className="mt-6">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-[2rem]">
            UMI-barcoded Illumina MiSeq 2×250 BCR mRNA
          </h1>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-muted-foreground">
            Preprocessing workflow for paired-end bulk BCR mRNA repertoire data
            with UMI barcodes, V-region primer, and C-region primer structure.
          </p>
        </header>

        {/* Data structure */}
        <section className="mt-10">
          <SectionHeading
            eyebrow="Section 1"
            title="Data structure"
            description="Library design for this sequencing protocol."
          />
          <div
            className="mt-5 rounded-2xl border border-border bg-card p-6"
            style={{ boxShadow: "var(--shadow-card)" }}
          >
            <div
              className="flex items-center justify-center rounded-xl border border-border/60 px-8 py-8"
              style={{
                background:
                  "linear-gradient(135deg, oklch(0.985 0.012 220) 0%, oklch(0.97 0.02 200) 100%)",
              }}
            >
              <div className="w-full max-w-2xl">
                <LibrarySchematic variant="umi" />
              </div>
            </div>
          </div>
        </section>

        {/* Workflow + inputs */}
        <section className="mt-12">
          <SectionHeading
            eyebrow="Section 2"
            title={jobId ? "Workflow and live progress" : "Workflow and required inputs"}
            description={
              jobId
                ? "Live status of each step is shown on the left next to the workflow."
                : "Upload the four required files. The workflow on the left will highlight the steps each file feeds into."
            }
          />

          <div
            className={cn(
              "mt-5 grid gap-5",
              jobId ? "lg:grid-cols-[17rem_1fr]" : "lg:grid-cols-[1.2fr_1fr]",
            )}
          >
            {jobId && (
              <div className="flex min-w-0 flex-col gap-4">
                <PipelineProgress
                  progress={progress}
                  steps={UMI_2X250_PROGRESS_STEPS}
                  jobId={jobId}
                  onReset={handleReset}
                />
                {trackingCode && <TrackingCodeCard trackingCode={trackingCode} />}
              </div>
            )}
            {/* Workflow */}
            <div
              className="rounded-2xl border border-border bg-card p-6"
              style={{ boxShadow: "var(--shadow-card)" }}
            >
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Preprocessing workflow
              </h3>

              <div className="mt-6 flex flex-col items-center">
                {/* Read 1 / Read 2 inputs */}
                <div className="grid w-full max-w-md grid-cols-2 gap-4">
                  <FlowInputNode
                    id="read1"
                    title="Read 1"
                    sub="C-Region Primer"
                    format="FASTQ"
                    uploaded={uploadedHighlightedSteps.has("read1")}
                    hovered={hoverHighlightedSteps.has("read1")}
                  />
                  <FlowInputNode
                    id="read2"
                    title="Read 2"
                    sub="V-Segment Primer"
                    format="FASTQ"
                    uploaded={uploadedHighlightedSteps.has("read2")}
                    hovered={hoverHighlightedSteps.has("read2")}
                  />
                </div>

                {/* Converging arrows */}
                <ConvergeArrows
                  active={
                    uploadedHighlightedSteps.has("assemble") ||
                    hoverHighlightedSteps.has("assemble")
                  }
                />

                {/* Main flow nodes */}
                {FLOW.map((node, idx) => {
                  const uploaded = uploadedHighlightedSteps.has(node.id);
                  const hovered = hoverHighlightedSteps.has(node.id);
                  return (
                    <div key={node.id} className="flex w-full flex-col items-center">
                      <FlowNodeBox
                        node={node}
                        uploaded={uploaded}
                        hovered={hovered}
                      />
                      {idx < FLOW.length - 1 && <FlowArrow active={uploaded} />}
                    </div>
                  );
                })}

                <FlowArrow active={false} />

                {/* Final repertoire */}
                <FlowOutputNode />
              </div>
            </div>

            {/* Inputs */}
            {!jobId && (
            <div className="flex flex-col gap-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Required inputs
              </h3>
              {INPUTS.map((input) => (
                <UploadCard
                  key={input.key}
                  input={input}
                  entry={files[input.key]}
                  onHover={(h) => setHoverKey(h ? input.key : null)}
                  onUpload={(file) => handleUpload(input.key, file)}
                />
              ))}
            </div>
            )}
          </div>
        </section>

        {jobId && progress.stepStats.length > 0 && (
          <section className="mt-8">
            <SectionHeading
              eyebrow="Live"
              title="Sequence retention"
              description="How many sequences survive each step of this run."
            />
            <div
              className="mt-5 rounded-2xl border border-border bg-card p-6"
              style={{ boxShadow: "var(--shadow-card)" }}
            >
              <div className="mx-auto max-w-md">
                <StepFunnel stepStats={progress.stepStats} showDownload={true}  />
              </div>
            </div>
          </section>
        )}

        {/* Actions */}
        {!jobId && (
        <>
        <section className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap gap-3">
            <Button
              onClick={handleValidate}
              disabled={!allUploaded || validating}
              className="gap-2"
            >
              {validating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : validated ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {validating
                ? "Validating…"
                : validated
                  ? "Inputs validated"
                  : "Validate inputs"}
            </Button>
            <Button
              variant="outline"
              disabled={!validated || launch.isLaunching}
              onClick={handleRun}
              className="gap-2"
            >
              <PlayCircle className="h-4 w-4" />
              {launch.isLaunching ? "Starting…" : "Run pipeline"}
            </Button>
          </div>
          {launch.error ? (
            <div className="inline-flex items-center gap-2 rounded-full bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive">
              <AlertCircle className="h-3.5 w-3.5" />
              {launch.error}
            </div>
          ) : validationError ? (
            <div className="inline-flex items-center gap-2 rounded-full bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive">
              <AlertCircle className="h-3.5 w-3.5" />
              {validationError}
            </div>
          ) : validated ? (
            <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary">
              <CheckCircle2 className="h-3.5 w-3.5" />
              All inputs passed validation
            </div>
          ) : null}
        </section>

        {/* Upload summary */}
        <section className="mt-8">
          <div
            className="rounded-2xl border border-border bg-card p-5"
            style={{ boxShadow: "var(--shadow-card)" }}
          >
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Upload summary
            </h3>
            <ul className="mt-3 grid gap-2 sm:grid-cols-2">
              {INPUTS.map((input) => {
                const entry = files[input.key];
                const done = entry?.state === "uploaded";
                return (
                  <li
                    key={input.key}
                    className="flex items-center justify-between rounded-lg border border-border/60 bg-background px-3 py-2 text-sm"
                  >
                    <span className="font-medium text-foreground">
                      {input.label}
                    </span>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 text-xs font-medium",
                        done ? "text-primary" : "text-muted-foreground",
                      )}
                    >
                      {done ? (
                        <>
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Uploaded
                        </>
                      ) : (
                        <>
                          <AlertCircle className="h-3.5 w-3.5" />
                          Missing
                        </>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </section>
        </>
        )}

        <SessionHistory entries={historyQuery.data ?? []} />
      </main>

      <JobLaunchGate
        open={launch.gateOpen}
        estimate={launch.estimate}
        onOpenChange={launch.setGateOpen}
        onVerified={launch.startNow}
      />
    </div>
  );
}

function SectionHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description?: string;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-primary/80">
        {eyebrow}
      </p>
      <h2 className="mt-1 text-xl font-semibold tracking-tight text-foreground">
        {title}
      </h2>
      {description && (
        <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>
      )}
    </div>
  );
}

function UploadCard({
  input,
  entry,
  onUpload,
  onHover,
}: {
  input: InputConfig;
  entry: FileEntry | null;
  onUpload: (file: File) => void;
  onHover: (hovered: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const state: UploadState = entry?.state ?? "default";

  return (
    <div
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      className={cn(
        "group rounded-2xl border bg-card p-5 transition-all duration-200",
        state === "uploaded"
          ? "border-primary/50 ring-1 ring-primary/20"
          : "border-border hover:border-primary/40",
      )}
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-semibold text-foreground">
              {input.label}
            </h4>
            {state === "uploaded" && (
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                <CheckCircle2 className="h-3 w-3" />
                Loaded
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{input.helper}</p>
        </div>
        <div
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
            state === "uploaded"
              ? "bg-primary/10 text-primary"
              : "bg-muted text-muted-foreground",
          )}
        >
          {state === "uploading" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : state === "uploaded" ? (
            <CheckCircle2 className="h-4 w-4" />
          ) : state === "error" ? (
            <AlertCircle className="h-4 w-4 text-destructive" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept={input.accept}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onUpload(file);
          }}
        />
        <Button
          variant={state === "uploaded" ? "outline" : "default"}
          size="sm"
          onClick={() => inputRef.current?.click()}
          className="gap-1.5"
        >
          <FileUp className="h-3.5 w-3.5" />
          {state === "uploaded" ? "Replace file" : "Choose file"}
        </Button>
        {entry && (
          <span className="truncate text-xs text-muted-foreground">
            {entry.name}
          </span>
        )}
      </div>
    </div>
  );
}

function FlowInputNode({
  title,
  sub,
  format,
  uploaded,
  hovered,
}: {
  id: string;
  title: string;
  sub: string;
  format: string;
  uploaded: boolean;
  hovered: boolean;
}) {
  return (
    <div
      className={cn(
        "relative rounded-2xl border bg-muted/60 px-4 py-3 text-center transition-all duration-300",
        uploaded && "border-primary/60 bg-primary/10 ring-2 ring-primary/30",
        hovered && "scale-[1.03] border-primary ring-2 ring-primary/50",
      )}
      style={
        uploaded || hovered
          ? { boxShadow: "var(--shadow-card-hover)" }
          : { boxShadow: "var(--shadow-card)" }
      }
    >
      <div className="text-sm font-bold tracking-tight text-foreground">{title}</div>
      <div className="text-[11px] leading-tight text-muted-foreground">{sub}</div>
      <div className="text-[10px] italic text-muted-foreground/80">{format}</div>
      {hovered && (
        <span className="pointer-events-none absolute inset-0 rounded-2xl ring-2 ring-primary/40 animate-pulse" />
      )}
    </div>
  );
}

function ConvergeArrows({ active }: { active: boolean }) {
  const stroke = active ? "oklch(0.55 0.13 230)" : "oklch(0.6 0.02 250)";
  return (
    <svg
      viewBox="0 0 200 40"
      className="my-1 h-10 w-full max-w-md"
      aria-hidden
    >
      <defs>
        <marker
          id="arrowhead-converge"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill={stroke} />
        </marker>
      </defs>
      <path
        d="M 50 0 Q 50 30 100 32"
        stroke={stroke}
        strokeWidth={active ? 2.5 : 1.75}
        fill="none"
        markerEnd="url(#arrowhead-converge)"
        className="transition-all"
      />
      <path
        d="M 150 0 Q 150 30 100 32"
        stroke={stroke}
        strokeWidth={active ? 2.5 : 1.75}
        fill="none"
        markerEnd="url(#arrowhead-converge)"
        className="transition-all"
      />
    </svg>
  );
}

function FlowArrow({ active }: { active: boolean }) {
  return (
    <div className="flex flex-col items-center">
      <div
        className={cn(
          "h-4 w-px transition-colors",
          active ? "bg-primary/60" : "bg-border",
        )}
      />
      <div
        className={cn(
          "h-0 w-0 border-l-[4px] border-r-[4px] border-t-[5px] border-l-transparent border-r-transparent transition-colors",
          active ? "border-t-primary/60" : "border-t-border",
        )}
      />
    </div>
  );
}

function FlowNodeBox({
  node,
  uploaded,
  hovered,
}: {
  node: FlowNode;
  uploaded: boolean;
  hovered: boolean;
}) {
  const kindStyles: Record<FlowNode["kind"], string> = {
    assemble:
      "border-[oklch(0.78_0.14_60)] bg-[oklch(0.95_0.08_65)] text-[oklch(0.38_0.13_50)]",
    process:
      "border-[oklch(0.72_0.13_165)] bg-[oklch(0.93_0.09_170)] text-[oklch(0.32_0.11_165)]",
    collapse:
      "border-[oklch(0.65_0.13_230)] bg-[oklch(0.92_0.08_225)] text-[oklch(0.3_0.13_235)]",
  };

  return (
    <div className="relative flex w-full max-w-md items-center justify-center">
      {/* Left log */}
      {node.log?.side === "left" && (
        <>
          <LogBubble label={node.log.label} />
          <DashedConnector />
        </>
      )}

      <div
        className={cn(
          "relative flex-1 rounded-xl border-2 px-4 py-3 text-center transition-all duration-300",
          kindStyles[node.kind],
          uploaded && "ring-2 ring-primary/40 scale-[1.01]",
          hovered && "ring-2 ring-primary scale-[1.03]",
        )}
        style={
          uploaded || hovered
            ? { boxShadow: "var(--shadow-card-hover)" }
            : { boxShadow: "var(--shadow-card)" }
        }
      >
        <div className="text-sm font-semibold leading-tight">{node.label}</div>
        {node.sub && (
          <div className="text-[11px] font-medium opacity-75">{node.sub}</div>
        )}
        {hovered && (
          <span className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-primary/50 animate-pulse" />
        )}
      </div>

      {/* Right log */}
      {node.log?.side === "right" && (
        <>
          <DashedConnector />
          <LogBubble label={node.log.label} />
        </>
      )}
    </div>
  );
}

function LogBubble({ label }: { label: string }) {
  return (
    <div className="shrink-0 rounded-full border border-[oklch(0.72_0.13_165)] bg-[oklch(0.93_0.09_170)] px-2.5 py-1 text-[10px] font-medium text-[oklch(0.32_0.11_165)]">
      {label}
    </div>
  );
}

function DashedConnector() {
  return (
    <div
      className="mx-1.5 h-px w-4 shrink-0"
      style={{
        backgroundImage:
          "linear-gradient(to right, oklch(0.6 0.02 250) 50%, transparent 50%)",
        backgroundSize: "4px 1px",
        backgroundRepeat: "repeat-x",
      }}
    />
  );
}

function FlowOutputNode() {
  return (
    <div
      className="rounded-2xl border border-border bg-muted/60 px-5 py-3 text-center"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="text-sm font-bold tracking-tight text-foreground">
        Final Repertoire
      </div>
      <div className="text-[11px] italic text-muted-foreground">FASTQ</div>
    </div>
  );
}

