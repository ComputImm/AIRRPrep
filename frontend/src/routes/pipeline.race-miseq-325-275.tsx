import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
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
  buildRace325275Payload,
  RACE_325275_PROGRESS_STEPS,
} from "@/pipelines/racemiseq325275";
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

export const Route = createFileRoute("/pipeline/race-miseq-325-275")({
  head: () => ({
    meta: [
      { title: "UMI-barcoded MiSeq 325+275 5′ RACE BCR mRNA — Pipeline" },
      {
        name: "description",
        content:
          "Preprocessing workflow for UMI-barcoded paired-end 5′ RACE BCR mRNA repertoire data with template-switching.",
      },
    ],
  }),
  component: PipelinePage,
});

type InputKey = "read1" | "read2" | "cprimer" | "tsseq" | "internalC" | "refrence";
type UploadState = "default" | "uploading" | "uploaded" | "error";

type InputConfig = {
  key: InputKey;
  label: string;
  helper: string;
  accept: string;
  highlights: string[];
};

const INPUTS: InputConfig[] = [
  {
    key: "read1",
    label: "Read 1",
    helper: "FASTQ file for Read 1",
    accept: ".fastq,.fq,.gz",
    highlights: ["read1"],
  },
  {
    key: "read2",
    label: "Read 2",
    helper: "FASTQ file for Read 2",
    accept: ".fastq,.fq,.gz",
    highlights: ["read2"],
  },
  {
    key: "cprimer",
    label: "C-primer",
    helper: "Primer file for C-region primer sequences",
    accept: ".fasta,.fa,.txt , .fastq,.fq",
    highlights: ["maskC"],
  },
  {
    key: "tsseq",
    label: "Template-switching sequence",
    helper: "File containing template-switching sequence information",
    accept: ".fasta,.fa,.txt,.fastq,.fq",
    highlights: ["maskTS"],
  },
  {
    key: "internalC",
    label: "Internal IG C-region",
    helper: "Internal immunoglobulin C-region reference file",
    accept: ".fasta,.fa,.txt ,.fastq,.fq",
    highlights: ["maskAlign"],
  },
  {
    key: "refrence",
    label: "Assemble Sequential Refrence",
    helper: "Refrnce file to assemble two pairs",
    accept: ".fasta,.fa,.txt , fastq,fq",
    highlights: ["assembleRef"],
  },
];

type FileEntry = {
    id?: string;
    file?: File;
    name: string;
    state: UploadState;
}

function PipelinePage() {
  const [files, setFiles] = useState<Record<InputKey, FileEntry | null>>({
    read1: null,
    read2: null,
    cprimer: null,
    tsseq: null,
    internalC: null,
    refrence: null,
  });
  const queryClient = useQueryClient();
  const startJobMutation = useStartJob();
  const validateMutation = useValidatePipeline();
  const [jobId, setJobId] = useState<string | null>(null);
  const [trackingCode, setTrackingCode] = useState<string | null>(null);
  const progress = useJobProgress(jobId, RACE_325275_PROGRESS_STEPS.length);
  const historyQuery = useSessionHistory();

  // Arriving here from a tracking code (/track) shows that run's progress.
  useResumedJob(jobId, setJobId);

  const buildPayload = (sessionId: string) =>
    buildRace325275Payload(
      {
        read1: files.read1,
        read2: files.read2,
        primerR1: files.cprimer,
        primerR2: files.tsseq,
        reference: files.refrence,
        cRegion: files.internalC,
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
        route: "/pipeline/race-miseq-325-275",
        label: "5′ RACE MiSeq 325+275",
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
  const [hoverKey, setHoverKey] = useState<InputKey | null>(null);
  const [validated, setValidated] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const uploadMutation = useFileUpload();
  const [validating, setValidating] = useState(false);

  const allUploaded = useMemo(
    () => INPUTS.every((i) => files[i.key]?.state === "uploaded"),
    [files],
  );

  const uploadedSteps = useMemo(() => {
    const set = new Set<string>();
    INPUTS.forEach((i) => {
      if (files[i.key]?.state === "uploaded") {
        i.highlights.forEach((h) => set.add(h));
      }
    });
    return set;
  }, [files]);

  const hoverSteps = useMemo(() => {
    if (!hoverKey) return new Set<string>();
    const cfg = INPUTS.find((i) => i.key === hoverKey);
    return new Set<string>(cfg?.highlights ?? []);
  }, [hoverKey]);

  const isActive = (id: string) => uploadedSteps.has(id) || hoverSteps.has(id);
  const isUploaded = (id: string) => uploadedSteps.has(id);
  const isHovered = (id: string) => hoverSteps.has(id);

  const handleUpload = async (key: InputKey, file: File) => {
      setFiles((prev) => ({
        ...prev,
        [key]: {
          name: file.name,
          file,
          state: "uploading",
        },
      }));

      try {
        const result = await uploadMutation.mutateAsync(file);

        setFiles((prev) => ({
          ...prev,
          [key]: {
            id: result.file_id,
            file,
            name: file.name,
            state: "uploaded",
          },
        }));
      } catch (error) {
        setFiles((prev) => ({
          ...prev,
          [key]: {
            file,
            name: file.name,
            state: "error",
          },
        }));
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
            UMI-barcoded Illumina MiSeq 325+275 paired-end 5′ RACE BCR mRNA
          </h1>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-muted-foreground">
            Preprocessing workflow for UMI-barcoded paired-end 5′ RACE BCR mRNA
            repertoire data with template-switching and internal C-region structure.
          </p>
        </header>

        <section className="mt-10">
          <SectionHeading
            eyebrow="Section 1"
            title="Data structure"
            description="Asymmetric paired-end (325 bp / 275 bp) library with UMI, template-switching site, leader, V(D)J, and internal IG C-region."
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
                <LibrarySchematic variant="race" />
              </div>
            </div>
          </div>
        </section>

        <section className="mt-12">
          <SectionHeading
            eyebrow="Section 2"
            title={jobId ? "Workflow and live progress" : "Workflow and required inputs"}
            description={
              jobId
                ? "Live status of each step is shown on the left next to the workflow."
                : "Upload the five required files. The workflow on the left will highlight the steps each file feeds into."
            }
          />

          <div
            className={cn(
              "mt-5 grid gap-5",
              jobId
                ? "lg:grid-cols-[17rem_1fr]"
                : "lg:grid-cols-[1.2fr_1fr]",
            )}
          >
            {jobId && (
              <div className="flex min-w-0 flex-col gap-4">
                <PipelineProgress
                  progress={progress}
                  steps={RACE_325275_PROGRESS_STEPS}
                  jobId={jobId}
                  onReset={handleReset}
                />
                {trackingCode && <TrackingCodeCard trackingCode={trackingCode} />}
              </div>
            )}
            <div
              className="rounded-2xl border border-border bg-card p-6"
              style={{ boxShadow: "var(--shadow-card)" }}
            >
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Preprocessing workflow
              </h3>

              <div className="mt-6 flex flex-col items-center gap-2">
                {/* Two-column branch */}
                <div className="grid w-full grid-cols-2 gap-3">
                  <FlowInputNode
                    title="Read 1"
                    sub="C-Region Primer"
                    format="FASTQ"
                    uploaded={isUploaded("read1")}
                    hovered={isHovered("read1")}
                  />
                  <FlowInputNode
                    title="Read 2"
                    sub="UMI, TS Site"
                    format="FASTQ"
                    uploaded={isUploaded("read2")}
                    hovered={isHovered("read2")}
                  />

                  <BranchArrow active={isActive("filter1")} />
                  <BranchArrow active={isActive("filter2")} />

                  <BranchNode
                    label="FilterSeq quality"
                    kind="pink"
                    uploaded={isUploaded("filter1")}
                    hovered={isHovered("filter1")}
                  />
                  <BranchNode
                    label="FilterSeq quality"
                    kind="pink"
                    uploaded={isUploaded("filter2")}
                    hovered={isHovered("filter2")}
                  />

                  <BranchArrow active={isActive("maskC")} />
                  <BranchArrow active={isActive("maskTS")} />

                  <BranchNode
                    label="MaskPrimers score"
                    sub="C-region primer"
                    kind="pink"
                    uploaded={isUploaded("maskC")}
                    hovered={isHovered("maskC")}
                  />
                  <BranchNode
                    label="MaskPrimers score"
                    sub="Template-switching"
                    kind="pink"
                    uploaded={isUploaded("maskTS")}
                    hovered={isHovered("maskTS")}
                  />
                </div>

                <ConvergeArrows active={isActive("pair1")} idSuffix="a" />

                <FullWidthNode
                  label="PairSeq"
                  kind="orange"
                  uploaded={isUploaded("pair1")}
                  hovered={isHovered("pair1")}
                />

                <DiverArrows active={false} />

                <div className="grid w-full grid-cols-2 gap-3">
                  <BranchNode
                    label="BuildConsensus"
                    kind="orange"
                    uploaded={false}
                    hovered={false}
                  />
                  <BranchNode
                    label="BuildConsensus"
                    kind="orange"
                    uploaded={false}
                    hovered={false}
                  />
                </div>

                <ConvergeArrows active={false} idSuffix="b" />

                <FullWidthNode label="PairSeq" kind="green" uploaded={false} hovered={false} />
                <FlowArrow active={false} />
                <FullWidthNode
                  label="AssemblePairs sequential"
                  kind="green"
                  uploaded={isUploaded("assembleRef")}
                  hovered={isHovered("assembleRef")}
                />
                <FlowArrow active={false} />
                <FullWidthNode
                  label="MaskPrimers align"
                  sub="Internal IG C-region"
                  kind="blue"
                  uploaded={isUploaded("maskAlign")}
                  hovered={isHovered("maskAlign")}
                />
                <FlowArrow active={isActive("maskAlign")} />
                <FullWidthNode
                  label="ParseHeaders collapse"
                  kind="blue"
                  uploaded={false}
                  hovered={false}
                />
                <FlowArrow active={false} />
                <FullWidthNode label="CollapseSeq" kind="blue" uploaded={false} hovered={false} />
                <FlowArrow active={false} />
                <FullWidthNode
                  label="SplitSeq group"
                  kind="blue"
                  uploaded={false}
                  hovered={false}
                />
                <FlowArrow active={false} />
                <FullWidthNode
                  label="ParseHeaders table"
                  kind="blue"
                  uploaded={false}
                  hovered={false}
                />
                <FlowArrow active={false} />
                <FlowOutputNode />
              </div>
            </div>

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
                <StepFunnel stepStats={progress.stepStats} showDownload={true} />
              </div>
            </div>
          </section>
        )}

        {!jobId && (
        <>
        <section className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap gap-3">
            <Button onClick={handleValidate} disabled={!allUploaded || validating} className="gap-2">
              {validating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : validated ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {validating ? "Validating…" : validated ? "Inputs validated" : "Validate inputs"}
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
                    <span className="font-medium text-foreground">{input.label}</span>
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
      <p className="text-xs font-semibold uppercase tracking-wider text-primary/80">{eyebrow}</p>
      <h2 className="mt-1 text-xl font-semibold tracking-tight text-foreground">{title}</h2>
      {description && <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>}
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
            <h4 className="text-sm font-semibold text-foreground">{input.label}</h4>
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
            state === "uploaded" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
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
          <span className="truncate text-xs text-muted-foreground">{entry.name}</span>
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
  title: string;
  sub: string;
  format: string;
  uploaded: boolean;
  hovered: boolean;
}) {
  return (
    <div
      className={cn(
        "relative rounded-2xl border bg-muted/60 px-3 py-2.5 text-center transition-all duration-300",
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

type NodeKind = "pink" | "orange" | "green" | "blue";

const KIND_STYLES: Record<NodeKind, string> = {
  pink: "border-[oklch(0.72_0.18_0)] bg-[oklch(0.94_0.06_5)] text-[oklch(0.38_0.16_0)]",
  orange:
    "border-[oklch(0.78_0.14_60)] bg-[oklch(0.95_0.08_65)] text-[oklch(0.38_0.13_50)]",
  green:
    "border-[oklch(0.72_0.13_165)] bg-[oklch(0.93_0.09_170)] text-[oklch(0.32_0.11_165)]",
  blue: "border-[oklch(0.65_0.13_230)] bg-[oklch(0.92_0.08_225)] text-[oklch(0.3_0.13_235)]",
};

function BranchNode({
  label,
  sub,
  kind,
  uploaded,
  hovered,
}: {
  label: string;
  sub?: string;
  kind: NodeKind;
  uploaded: boolean;
  hovered: boolean;
}) {
  return (
    <div
      className={cn(
        "relative rounded-xl border-2 px-3 py-2.5 text-center transition-all duration-300",
        KIND_STYLES[kind],
        uploaded && "ring-2 ring-primary/40 scale-[1.01]",
        hovered && "ring-2 ring-primary scale-[1.03]",
      )}
      style={
        uploaded || hovered
          ? { boxShadow: "var(--shadow-card-hover)" }
          : { boxShadow: "var(--shadow-card)" }
      }
    >
      <div className="text-xs font-semibold leading-tight">{label}</div>
      {sub && <div className="text-[10px] font-medium opacity-75">{sub}</div>}
      {hovered && (
        <span className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-primary/50 animate-pulse" />
      )}
    </div>
  );
}

function FullWidthNode({
  label,
  sub,
  kind,
  uploaded,
  hovered,
}: {
  label: string;
  sub?: string;
  kind: NodeKind;
  uploaded: boolean;
  hovered: boolean;
}) {
  return (
    <div
      className={cn(
        "relative w-full rounded-xl border-2 px-4 py-2.5 text-center transition-all duration-300",
        KIND_STYLES[kind],
        uploaded && "ring-2 ring-primary/40 scale-[1.005]",
        hovered && "ring-2 ring-primary scale-[1.02]",
      )}
      style={
        uploaded || hovered
          ? { boxShadow: "var(--shadow-card-hover)" }
          : { boxShadow: "var(--shadow-card)" }
      }
    >
      <div className="text-sm font-semibold leading-tight">{label}</div>
      {sub && <div className="text-[11px] font-medium opacity-75">{sub}</div>}
      {hovered && (
        <span className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-primary/50 animate-pulse" />
      )}
    </div>
  );
}

function BranchArrow({ active }: { active: boolean }) {
  return (
    <div className="flex flex-col items-center justify-self-center">
      <div className={cn("h-3 w-px transition-colors", active ? "bg-primary/60" : "bg-border")} />
      <div
        className={cn(
          "h-0 w-0 border-l-[4px] border-r-[4px] border-t-[5px] border-l-transparent border-r-transparent transition-colors",
          active ? "border-t-primary/60" : "border-t-border",
        )}
      />
    </div>
  );
}

function FlowArrow({ active }: { active: boolean }) {
  return (
    <div className="flex flex-col items-center">
      <div className={cn("h-3 w-px transition-colors", active ? "bg-primary/60" : "bg-border")} />
      <div
        className={cn(
          "h-0 w-0 border-l-[4px] border-r-[4px] border-t-[5px] border-l-transparent border-r-transparent transition-colors",
          active ? "border-t-primary/60" : "border-t-border",
        )}
      />
    </div>
  );
}

function ConvergeArrows({ active, idSuffix }: { active: boolean; idSuffix: string }) {
  const stroke = active ? "oklch(0.55 0.13 230)" : "oklch(0.6 0.02 250)";
  const id = `arrowhead-converge-race-${idSuffix}`;
  return (
    <svg viewBox="0 0 200 40" className="my-1 h-8 w-full" aria-hidden>
      <defs>
        <marker
          id={id}
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
        markerEnd={`url(#${id})`}
      />
      <path
        d="M 150 0 Q 150 30 100 32"
        stroke={stroke}
        strokeWidth={active ? 2.5 : 1.75}
        fill="none"
        markerEnd={`url(#${id})`}
      />
    </svg>
  );
}

function DiverArrows({ active }: { active: boolean }) {
  const stroke = active ? "oklch(0.55 0.13 230)" : "oklch(0.6 0.02 250)";
  return (
    <svg viewBox="0 0 200 40" className="my-1 h-8 w-full" aria-hidden>
      <defs>
        <marker
          id="arrowhead-diver-race"
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
        d="M 100 0 Q 100 30 50 32"
        stroke={stroke}
        strokeWidth={active ? 2.5 : 1.75}
        fill="none"
        markerEnd="url(#arrowhead-diver-race)"
      />
      <path
        d="M 100 0 Q 100 30 150 32"
        stroke={stroke}
        strokeWidth={active ? 2.5 : 1.75}
        fill="none"
        markerEnd="url(#arrowhead-diver-race)"
      />
    </svg>
  );
}

function FlowOutputNode() {
  return (
    <div
      className="rounded-2xl border border-border bg-muted/60 px-5 py-3 text-center"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="text-sm font-bold tracking-tight text-foreground">Final Repertoire</div>
      <div className="text-[11px] italic text-muted-foreground">FASTQ</div>
    </div>
  );
}

