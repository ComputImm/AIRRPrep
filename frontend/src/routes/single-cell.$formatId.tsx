import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileUp,
  Loader2,
  PlayCircle,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { getSessionId } from "@/api/session";
import { getJobProgress, readApiError } from "@/api/jobs";
import { useFileUpload } from "@/hooks/useFileUpload";
import { useJobProgress } from "@/hooks/useJobProgress";
import { useJobLaunch } from "@/hooks/useJobLaunch";
import { useResumedJob } from "@/hooks/useResumedJob";
import { useSessionHistory } from "@/hooks/useSessionHistory";
import { JobLaunchGate, TrackingCodeCard } from "@/components/JobLaunchGate";
import { SessionHistory } from "@/components/SessionHistory";
import { SingleCellProgress } from "@/components/SingleCellProgress";
import { SingleCellFormatFlow } from "@/components/SingleCellFormatFlow";
import { Trust4OptionsCard } from "@/components/Trust4OptionsCard";
import {
  getSingleCellWorkflow,
  type SingleCellWorkflow,
  type WorkflowInput,
} from "@/lib/singleCellWorkflows";
import {
  detectSingleCell,
  getTrust4Status,
  startSingleCellJob,
  validateSingleCell,
  DEFAULT_TRUST4_OPTIONS,
  type Trust4Options,
  type ValidateResult,
} from "@/api/singleCell";

export const Route = createFileRoute("/single-cell/$formatId")({
  loader: ({ params }) => {
    const workflow = getSingleCellWorkflow(params.formatId);
    if (!workflow) throw notFound();
    return { workflow };
  },
  head: ({ loaderData }) => ({
    meta: [
      { title: `${loaderData?.workflow.title ?? "Single-cell"} — Preprocessing` },
      { name: "description", content: loaderData?.workflow.subtitle ?? "" },
    ],
  }),
  component: SingleCellWorkflowPage,
});

type UploadState = "default" | "uploading" | "uploaded" | "error";
type FileEntry = { id?: string; name: string; state: UploadState };

function SingleCellWorkflowPage() {
  const { workflow } = Route.useLoaderData();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [files, setFiles] = useState<Record<string, FileEntry | null>>({});
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [validating, setValidating] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [trackingCode, setTrackingCode] = useState<string | null>(null);
  const [trust4Options, setTrust4Options] = useState<Trust4Options>(
    DEFAULT_TRUST4_OPTIONS,
  );
  const [allowProductive, setAllowProductive] = useState(false);
  const [barcodeHeaderRegex, setBarcodeHeaderRegex] = useState("");

  const uploadMutation = useFileUpload();
  const queryClient = useQueryClient();
  const historyQuery = useSessionHistory();

  useEffect(() => {
    getSessionId().then(setSessionId);
  }, []);

  // Switching workflows must not carry the previous one's uploads over.
  useEffect(() => {
    setFiles({});
    setValidation(null);
    setJobId(null);
    setTrackingCode(null);
  }, [workflow.id]);

  const uploaded = useMemo(
    () =>
      workflow.inputs
        .map((i) => ({ input: i, entry: files[i.role] }))
        .filter((x) => x.entry?.state === "uploaded" && x.entry.id),
    [files, workflow.inputs],
  );

  const roleFileIds = useMemo(() => {
    const map: Record<string, string> = {};
    uploaded.forEach(({ input, entry }) => {
      map[input.role] = entry!.id as string;
    });
    return map;
  }, [uploaded]);

  const fileIds = useMemo(() => Object.values(roleFileIds), [roleFileIds]);

  const allRequiredUploaded = workflow.inputs
    .filter((i) => i.required)
    .every((i) => files[i.role]?.state === "uploaded");

  // Server-side TRUST4 availability — a property of the deployment, so it is
  // fetched only for the two workflows that actually assemble.
  const trust4StatusQuery = useQuery({
    queryKey: ["trust4-status"],
    queryFn: getTrust4Status,
    enabled: workflow.needsTrust4,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    const preferred = trust4StatusQuery.data?.default_species;
    if (preferred === "human" || preferred === "mouse") {
      setTrust4Options((prev) => ({ ...prev, species: preferred }));
    }
  }, [trust4StatusQuery.data?.default_species]);

  // The card already fixed the format, so detection is no longer what picks
  // the adapter — it is only a sanity check that the uploaded files look like
  // what this workflow expects. Advisory: it never blocks the run.
  const detectionQuery = useQuery({
    queryKey: ["singlecell-detect", sessionId, fileIds.join(",")],
    queryFn: () => detectSingleCell(sessionId as string, fileIds),
    enabled: !!sessionId && allRequiredUploaded && fileIds.length > 0,
  });
  const mismatch =
    detectionQuery.data?.ready &&
    detectionQuery.data.format_id &&
    detectionQuery.data.format_id !== workflow.id
      ? detectionQuery.data.label
      : null;

  const totalStages = workflow.needsTrust4 ? 4 : 3;
  const progress = useJobProgress(jobId, totalStages);

  // Arriving here from a tracking code (/track) shows that run's progress.
  useResumedJob(jobId, setJobId);
  // Shares useJobProgress's cache entry, so this is not an extra round trip —
  // it just reads the fields JobProgress does not surface.
  const jobDocQuery = useQuery({
    queryKey: ["job-progress", jobId],
    queryFn: () => getJobProgress(jobId as string),
    enabled: !!jobId,
  });

  const stages = workflow.needsTrust4
    ? ["Assemble (TRUST4)", "Parse", "Validate", "Write FASTA + metadata"]
    : ["Parse", "Validate", "Write FASTA + metadata"];

  const selectedSpeciesReady =
    !workflow.needsTrust4 ||
    (trust4StatusQuery.data?.species.find((s) => s.id === trust4Options.species)
      ?.available ??
      false);

  // Generic FASTA cannot run without a declared way to recover the barcode:
  // a mapping file or a header regex. Substituting the sequence_id would
  // manufacture one fake "cell" per sequence, so the run is blocked instead.
  const barcodeRuleDeclared =
    !workflow.needsBarcodeRule ||
    files["barcode_map"]?.state === "uploaded" ||
    barcodeHeaderRegex.trim().length > 0;

  const canValidate =
    allRequiredUploaded && selectedSpeciesReady && barcodeRuleDeclared;
  const canRun = canValidate && validation?.valid === true;

  const runOptions = {
    roleFileIds,
    trust4Options: workflow.needsTrust4 ? trust4Options : undefined,
    allowProductive: workflow.supportsProductive ? allowProductive : undefined,
    barcodeHeaderRegex: workflow.needsBarcodeRule
      ? barcodeHeaderRegex
      : undefined,
  };

  const handleUpload = async (role: string, file: File) => {
    setFiles((prev) => ({ ...prev, [role]: { name: file.name, state: "uploading" } }));
    setValidation(null);
    try {
      const result = await uploadMutation.mutateAsync(file);
      setFiles((prev) => ({
        ...prev,
        [role]: { id: result.file_id, name: file.name, state: "uploaded" },
      }));
    } catch {
      setFiles((prev) => ({ ...prev, [role]: { name: file.name, state: "error" } }));
    }
  };

  const handleValidate = async () => {
    if (!sessionId) return;
    setValidating(true);
    launch.clearError();
    try {
      setValidation(
        await validateSingleCell(sessionId, fileIds, workflow.id, runOptions),
      );
    } catch (e) {
      setValidation({
        valid: false,
        errors: [readApiError(e)],
        warnings: [],
        record_count_estimate: null,
      });
    } finally {
      setValidating(false);
    }
  };

  const launch = useJobLaunch({
    buildEstimate: () => ({ file_ids: fileIds, format_id: workflow.id }),
    start: () =>
      startSingleCellJob(sessionId as string, fileIds, workflow.id, {
        ...runOptions,
        route: `/single-cell/${workflow.id}`,
        label: workflow.title,
      }),
    onStarted: (result) => {
      // The gate dialog can sit between the click and the start, so scroll
      // again once the run is really under way.
      window.scrollTo({ top: 0, behavior: "smooth" });
      setJobId(result.job_id);
      setTrackingCode(result.tracking_code ?? null);
      queryClient.invalidateQueries({ queryKey: ["session-history"] });
    },
  });

  const handleRun = () => {
    if (!sessionId) return;
    // The progress panel renders above the fold; the button is well below it.
    window.scrollTo({ top: 0, behavior: "smooth" });
    launch.launch();
  };

  const handleReset = () => {
    setJobId(null);
    setTrackingCode(null);
    setValidation(null);
  };

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-6 py-10">
        <Link
          to="/single-cell"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to single-cell data types
        </Link>

        <header className="mt-6">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-[2rem]">
            {workflow.title}
          </h1>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-muted-foreground">
            {workflow.subtitle}
          </p>
        </header>

        <section className="mt-10">
          <SectionHeading
            eyebrow="Section 1"
            title={jobId ? "Workflow and live progress" : "Workflow and required inputs"}
            description={
              jobId
                ? "Live status of each stage is shown on the left next to the workflow."
                : "Upload each file into its slot on the right. The workflow on the left is what will run."
            }
          />

          <div
            className={cn(
              "mt-5 grid gap-5",
              jobId ? "lg:grid-cols-[19rem_1fr]" : "lg:grid-cols-[1.2fr_1fr]",
            )}
          >
            {jobId && (
              <div className="flex min-w-0 flex-col gap-4">
                <SingleCellProgress
                  progress={progress}
                  stages={stages}
                  sessionId={sessionId ?? ""}
                  jobId={jobId}
                  recordCount={jobDocQuery.data?.record_count as number | undefined}
                  warnings={jobDocQuery.data?.warnings as string[] | undefined}
                  hasSourceAnnotations={Boolean(
                    jobDocQuery.data?.source_annotations_file,
                  )}
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
              <div className="mt-6">
                <SingleCellFormatFlow spec={workflow.flow} />
              </div>
            </div>

            {!jobId && (
              <div className="flex flex-col gap-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Required inputs
                </h3>
                {workflow.inputs.map((input) => (
                  <UploadCard
                    key={input.role}
                    input={input}
                    entry={files[input.role] ?? null}
                    onUpload={(file) => handleUpload(input.role, file)}
                  />
                ))}

                {mismatch && (
                  <p className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-700">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    These files look like {mismatch}, not {workflow.title}. They
                    will still be processed as {workflow.title} — go back and
                    pick the other workflow if that is not what you want.
                  </p>
                )}
              </div>
            )}
          </div>
        </section>

        {!jobId && (workflow.needsBarcodeRule || workflow.supportsProductive) && (
          <section className="mt-10">
            <SectionHeading
              eyebrow="Section 2"
              title="Field handling"
              description="How the cell barcode is recovered, and which annotation-derived fields may be carried through."
            />
            <div
              className="mt-5 flex flex-col gap-5 rounded-2xl border border-border bg-card p-5"
              style={{ boxShadow: "var(--shadow-card)" }}
            >
              {workflow.needsBarcodeRule && (
                <div className="grid gap-2">
                  <label className="text-xs font-medium text-foreground">
                    Barcode header regex
                  </label>
                  <Input
                    value={barcodeHeaderRegex}
                    placeholder="e.g.  ^([ACGT]+-\d+)_contig"
                    onChange={(e) => {
                      setBarcodeHeaderRegex(e.target.value);
                      setValidation(null);
                    }}
                  />
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    One capture group, matched against each FASTA header. Use
                    this <em>or</em> upload a barcode mapping file — at least
                    one is required. A sequence with no recoverable barcode
                    stops the run rather than being given an invented{" "}
                    <span className="font-mono">cell_id</span>, because that
                    would turn every sequence into its own fake cell.
                  </p>
                  {!barcodeRuleDeclared && (
                    <p className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-700">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      Declare a barcode rule to continue: upload a mapping file
                      above, or enter a regex here.
                    </p>
                  )}
                </div>
              )}

              {workflow.supportsProductive && (
                <label className="flex cursor-pointer items-start gap-3">
                  <input
                    type="checkbox"
                    checked={allowProductive}
                    onChange={(e) => {
                      setAllowProductive(e.target.checked);
                      setValidation(null);
                    }}
                    className="mt-0.5 h-4 w-4 shrink-0 accent-[oklch(0.55_0.13_230)]"
                  />
                  <span>
                    <span className="text-xs font-medium text-foreground">
                      Carry Cell Ranger's{" "}
                      <span className="font-mono">productive</span> call through
                    </span>
                    <span className="mt-1 block text-[11px] leading-relaxed text-muted-foreground">
                      Off by default. Deciding a sequence is productive requires
                      knowing the reading frame, which makes it
                      annotation-derived — IMGT's job, not the assembler's. Left
                      off, the column is written empty.
                    </span>
                  </span>
                </label>
              )}
            </div>
          </section>
        )}

        {!jobId && workflow.needsTrust4 && (
          <section className="mt-10">
            <SectionHeading
              eyebrow="Section 2"
              title="Assembly settings"
              description="Raw reads have to be assembled into per-cell contigs before they can be normalized. These settings control that TRUST4 run."
            />
            <div className="mt-5">
              <Trust4OptionsCard
                status={trust4StatusQuery.data}
                isLoading={trust4StatusQuery.isLoading}
                formatId={workflow.id}
                options={trust4Options}
                onChange={(next) => {
                  setTrust4Options(next);
                  setValidation(null);
                }}
              />
            </div>
          </section>
        )}

        {!jobId && (
          <>
            <section className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap gap-3">
                <Button
                  onClick={handleValidate}
                  disabled={!canValidate || validating}
                  className="gap-2"
                >
                  {validating ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : validation?.valid ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <ShieldCheck className="h-4 w-4" />
                  )}
                  {validating
                    ? "Validating…"
                    : validation?.valid
                      ? "Inputs validated"
                      : "Validate inputs"}
                </Button>
                <Button
                  variant="outline"
                  disabled={!canRun || launch.isLaunching}
                  onClick={handleRun}
                  className="gap-2"
                >
                  <PlayCircle className="h-4 w-4" />
                  {launch.isLaunching ? "Starting…" : "Run preprocessing"}
                </Button>
              </div>
              {launch.error || (validation && !validation.valid) ? (
                <div className="inline-flex items-center gap-2 rounded-full bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive">
                  <AlertCircle className="h-3.5 w-3.5" />
                  {launch.error ?? validation?.errors.join("; ")}
                </div>
              ) : validation?.valid ? (
                <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {/* Raw-read formats can't report a count until TRUST4 has
                      actually assembled, so the backend sends null there. */}
                  {validation.record_count_estimate === null
                    ? "Inputs ready to process"
                    : `${validation.record_count_estimate} sequences ready to process`}
                </div>
              ) : null}
            </section>

            {validation?.valid && validation.warnings.length > 0 && (
              <ul className="mt-4 flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-700">
                {validation.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}

            <section className="mt-8">
              <div
                className="rounded-2xl border border-border bg-card p-5"
                style={{ boxShadow: "var(--shadow-card)" }}
              >
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Upload summary
                </h3>
                <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                  {workflow.inputs.map((input) => {
                    const entry = files[input.role];
                    const done = entry?.state === "uploaded";
                    return (
                      <li
                        key={input.role}
                        className="flex items-center justify-between rounded-lg border border-border/60 bg-background px-3 py-2 text-sm"
                      >
                        <span className="font-medium text-foreground">
                          {input.label}
                          {!input.required && (
                            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                              optional
                            </span>
                          )}
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
                              {input.required ? "Missing" : "Not provided"}
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
}: {
  input: WorkflowInput;
  entry: FileEntry | null;
  onUpload: (file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const state: UploadState = entry?.state ?? "default";

  return (
    <div
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
            {!input.required && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Optional
              </span>
            )}
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
            e.target.value = "";
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
