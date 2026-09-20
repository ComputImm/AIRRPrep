import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toPng } from "html-to-image";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileUp,
  History,
  Loader2,
  Lock,
  Plus,
  RotateCcw,
  Scissors,
  ShieldCheck,
  Trash2,
  Upload,
  Workflow,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { useFileUpload } from "@/hooks/useFileUpload";
import { useStartJob } from "@/hooks/useStartJob";
import { useJobProgress } from "@/hooks/useJobProgress";
import { useJobLaunch } from "@/hooks/useJobLaunch";
import { useResumedJob } from "@/hooks/useResumedJob";
import { useSessionHistory } from "@/hooks/useSessionHistory";
import { getSessionId } from "@/api/session";
import { readApiError, validatePipeline, type PipelineStep } from "@/api/jobs";
import type { SessionFile } from "@/api/sessionFiles";
import type { RequiredUpload } from "@/api/savedPipelines";
import { PreviousUploadPicker } from "@/components/PreviousUploadPicker";
import { PipelineLibrary } from "@/components/PipelineLibrary";
import {
  splitHint,
  splitWarning,
  stepSplitsOutput,
  type SplitMode,
} from "@/lib/splitting";
import { JobLaunchGate, TrackingCodeCard } from "@/components/JobLaunchGate";
import {
  getAllSteps,
  customInit,
  customNextSteps,
  type StepMeta,
  type StepMetaParam,
  type PlannerStateResponse,
  type ValidNextStep,
} from "@/api/customPipeline";
import {
  categoryForStep,
  groupSteps,
  stepShortLabel,
  humanizeParam,
  userParams,
  fieldKind,
} from "@/lib/customCatalog";
import { paramChoices, paramGuide } from "@/lib/paramGuide";
import { MultiSelectField } from "@/components/ui/multi-select-field";
import { stepStyle } from "@/lib/stepColors";
import { PipelineProgress, type ProgressStepDescriptor } from "@/components/PipelineProgress";
import { StepFunnel, kindForStep } from "@/components/StepFunnel";
import { SessionHistory } from "@/components/SessionHistory";

type Mode = "single" | "paired";
type UploadState = "default" | "uploading" | "uploaded" | "error";
type FileEntry = { id?: string; name: string; state: UploadState } | null;
type ParamValue = string | boolean;

interface UiStep {
  uid: string;
  name: string;
  lanes: string;
  params: Record<string, unknown>;
}

let uidCounter = 0;
const nextUid = () => `s${++uidCounter}`;

function initDraft(meta: StepMeta): Record<string, ParamValue> {
  const v: Record<string, ParamValue> = {};
  userParams(meta).forEach((p) => {
    const k = fieldKind(meta, p);
    if (k === "boolean") v[p.name] = Boolean(p.default);
    else if (k === "array") v[p.name] = Array.isArray(p.default) ? p.default.join(", ") : "";
    else if (k === "file") v[p.name] = "";
    else v[p.name] = p.default == null ? "" : String(p.default);
  });
  return v;
}

function laneOptions(valid: ValidNextStep | undefined, streamMode: string): string[] {
  if (!valid) return [];
  if (valid.stream_behavior !== "per_lane") return ["paired"];
  if (streamMode !== "dual") return ["R1"];
  const allowed = valid.allowed_lanes ?? [];
  if (allowed.length > 1) return [...allowed, "both"];
  return allowed;
}

// A handful of params reference one *specific* lane's fields regardless of
// which lane the step itself is applied to -- PairSeq copies fields_1 from R1
// into R2 (and vice versa), AssembleSeq reads head_fields from the R1/head
// side and tail_fields from R2/tail (see contracts.py's field_effects). Every
// other field-name param uses whichever lane is selected in the dialog.
const PARAM_SOURCE_LANE: Record<string, string> = {
  fields_1: "R1",
  fields_2: "R2",
  head_fields: "R1",
  tail_fields: "R2",
};

/** The known field names (and whether that list is trustworthy) a field-name
 * param should offer, given the lane selected in the draft dialog. */
function fieldOptionsFor(
  paramName: string,
  laneFields: Record<string, string[]>,
  laneFieldsConfident: Record<string, boolean>,
  selectedLane: string,
): { options: string[]; confident: boolean } {
  const forced = PARAM_SOURCE_LANE[paramName];
  const lanes = forced
    ? [forced]
    : selectedLane === "R1" || selectedLane === "R2"
      ? [selectedLane]
      : Object.keys(laneFields); // "both" / "paired": every active lane

  const options = Array.from(new Set(lanes.flatMap((l) => laneFields[l] ?? [])));
  const confident = lanes.length > 0 && lanes.every((l) => laneFieldsConfident[l]);
  return { options, confident };
}

export function CustomWorkflowBuilder() {
  const queryClient = useQueryClient();
  const stepsMetaQuery = useQuery({ queryKey: ["all-steps"], queryFn: getAllSteps });
  const uploadMutation = useFileUpload();
  const startJobMutation = useStartJob();
  const historyQuery = useSessionHistory();

  const [mode, setMode] = useState<Mode | null>(null);
  const [files, setFiles] = useState<{ r1: FileEntry; r2: FileEntry }>({ r1: null, r2: null });
  const [planner, setPlanner] = useState<PlannerStateResponse | null>(null);
  const [steps, setSteps] = useState<UiStep[]>([]);
  const [initializing, setInitializing] = useState(false);
  const [initError, setInitError] = useState<string | null>(null);

  const [draftStep, setDraftStep] = useState<StepMeta | null>(null);

  // Reusing an upload instead of sending the same 200 MB FASTQ again.
  const [pickerLane, setPickerLane] = useState<"r1" | "r2" | null>(null);

  // A pipeline loaded from the library cannot be replayed against the planner
  // until the reads are up, so it waits here until they are.
  const [pendingLoad, setPendingLoad] = useState<UiStep[] | null>(null);
  const [loadedName, setLoadedName] = useState<string | null>(null);
  const [loadNotice, setLoadNotice] = useState<string | null>(null);
  const [neededUploads, setNeededUploads] = useState<RequiredUpload[]>([]);

  // Uploading a file straight onto an already-committed step (e.g. the primer
  // FASTA a loaded pipeline is missing) instead of forcing the whole pipeline
  // to be torn down to reach it. Keyed "<uid>:<param>" so two steps needing
  // the same param name don't share a spinner.
  const [stepUploadBusy, setStepUploadBusy] = useState<string | null>(null);
  const [stepUploadError, setStepUploadError] = useState<string | null>(null);

  const [validating, setValidating] = useState(false);
  const [validated, setValidated] = useState(false);
  const [showDiagram, setShowDiagram] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const [jobId, setJobId] = useState<string | null>(null);
  const [trackingCode, setTrackingCode] = useState<string | null>(null);
  const progress = useJobProgress(jobId, steps.length || 1);

  // Arriving here from a tracking code (/track) shows that run's progress.
  useResumedJob(jobId, setJobId);

  // Unlike the fixed pipelines, a custom run has no static step table — the
  // step list only exists in this component's state. A run resumed from a
  // tracking code arrives with that state empty, so fall back to the steps
  // the backend recorded when the job was created.
  const progressSteps: ProgressStepDescriptor[] = useMemo(() => {
    const source = steps.length
      ? steps.map((s) => s.name)
      : ((progress.raw?.steps as Array<{ name: string }> | undefined) ?? []).map(
          (s) => s.name,
        );

    return source.map((name) => ({
      name,
      label: name.replace(/\./g, " "),
      color: kindForStep(name),
    }));
  }, [steps, progress.raw]);

  const chains: 1 | 2 = mode === "paired" ? 2 : 1;
  const fileIds = useMemo(() => {
    if (mode === "paired") return [files.r1?.id, files.r2?.id].filter(Boolean) as string[];
    return [files.r1?.id].filter(Boolean) as string[];
  }, [mode, files]);
  const filesReady =
    mode === "paired"
      ? files.r1?.state === "uploaded" && files.r2?.state === "uploaded"
      : files.r1?.state === "uploaded";

  const metas = stepsMetaQuery.data ?? [];
  const grouped = useMemo(() => groupSteps(metas), [metas]);
  const validMap = useMemo(() => {
    const m = new Map<string, ValidNextStep>();
    planner?.valid_next_steps.forEach((v) => m.set(v.step, v));
    return m;
  }, [planner]);

  const stepsPayload: PipelineStep[] = steps.map((s) => ({
    id: s.uid,
    name: s.name,
    lanes: s.lanes,
    params: s.params,
  }));

  // ── Actions ──
  // Picking a file already on the server is the same state change as a
  // finished upload, minus the transfer.
  const handleReuse = (lane: "r1" | "r2", file: SessionFile) => {
    setPlanner(null);
    setDraftStep(null);
    setValidated(false);
    setShowDiagram(false);
    initKeyRef.current = "";
    setFiles((p) => ({
      ...p,
      [lane]: { id: file.file_id, name: file.filename, state: "uploaded" },
    }));
  };

  const handleUpload = async (lane: "r1" | "r2", file: File) => {
    setFiles((p) => ({ ...p, [lane]: { name: file.name, state: "uploading" } }));
    setPlanner(null);
    setSteps([]);
    setDraftStep(null);
    setValidated(false);
    setShowDiagram(false);
    try {
      const res = await uploadMutation.mutateAsync(file);
      setFiles((p) => ({ ...p, [lane]: { id: res.file_id, name: file.name, state: "uploaded" } }));
    } catch {
      setFiles((p) => ({ ...p, [lane]: { name: file.name, state: "error" } }));
    }
  };

  // Auto-initialise the planner once the file(s) are uploaded. A ref dedupes so
  // the in-flight request is never cancelled by our own state updates.
  const initKeyRef = useRef<string>("");
  useEffect(() => {
    if (!mode || !filesReady || planner) return;
    const key = `${chains}:${fileIds.join(",")}`;
    if (initKeyRef.current === key) return;
    initKeyRef.current = key;
    setInitializing(true);
    setInitError(null);
    customInit({ chains, file_ids: fileIds })
      .then((res) => {
        setPlanner(res);
        // A pipeline loaded from the library is replayed by the effect below
        // once the planner exists; clearing here would throw it away.
        if (!pendingLoad) setSteps([]);
      })
      .catch((e) => {
        setInitError(readApiError(e));
        initKeyRef.current = ""; // allow retry
      })
      .finally(() => setInitializing(false));
  }, [mode, filesReady, planner, chains, fileIds]);

  // Replay a loaded pipeline through the planner so the builder ends up in
  // exactly the state it would be in had the steps been added by hand -- and
  // so a workflow that no longer fits these reads fails here, with a reason,
  // rather than at launch.
  useEffect(() => {
    if (!pendingLoad || !planner || !filesReady) return;
    const list = pendingLoad;
    setPendingLoad(null);
    setInitError(null);
    customNextSteps({
      chains,
      file_ids: fileIds,
      steps: list.map((s) => ({
        id: s.uid,
        name: s.name,
        lanes: s.lanes,
        params: s.params,
      })),
    })
      .then((res) => {
        setSteps(list);
        setPlanner(res);
        setLoadNotice(
          `Loaded ${list.length} step${list.length === 1 ? "" : "s"}. Validate the pipeline to enable Run.`,
        );
      })
      .catch((e) => {
        setSteps([]);
        setInitError(
          `That pipeline does not fit these reads: ${readApiError(e)}`,
        );
      });
  }, [pendingLoad, planner, filesReady, chains, fileIds]);

  const handleLoadPipeline = ({
    steps: loaded,
    chains: loadedChains,
    name,
    requiresUploads,
  }: {
    steps: PipelineStep[];
    chains: 1 | 2;
    name: string;
    requiresUploads: RequiredUpload[];
  }) => {
    const targetMode: Mode = loadedChains === 2 ? "paired" : "single";
    const uiSteps: UiStep[] = loaded.map((step) => ({
      uid: nextUid(),
      name: step.name,
      lanes: (typeof step.lanes === "string" && step.lanes) || "R1",
      params: step.params ?? {},
    }));

    setLoadedName(name);
    setNeededUploads(requiresUploads ?? []);
    setLoadNotice(null);
    setValidated(false);
    setShowDiagram(false);
    setValidationError(null);
    setSteps([]);

    if (mode !== targetMode) {
      // A different read configuration invalidates the uploads as well.
      setMode(targetMode);
      setPlanner(null);
      initKeyRef.current = "";
    }
    setPendingLoad(uiSteps);
  };

  const commitStep = async (draft: UiStep) => {
    const payloadOf = (s: UiStep): PipelineStep => ({
      id: s.uid,
      name: s.name,
      lanes: s.lanes,
      params: s.params,
    });

    // When the user targets "both" lanes, materialise two independent steps —
    // one per channel — that share the same parameters, instead of a single
    // dual-lane step. Each is validated against the backend in sequence.
    if (draft.lanes === "both") {
      const r1: UiStep = { ...draft, uid: nextUid(), lanes: "R1" };
      const r2: UiStep = { ...draft, uid: nextUid(), lanes: "R2" };
      await customNextSteps({
        chains,
        file_ids: fileIds,
        steps: stepsPayload,
        draft_step: payloadOf(r1),
      });
      const res = await customNextSteps({
        chains,
        file_ids: fileIds,
        steps: [...stepsPayload, payloadOf(r1)],
        draft_step: payloadOf(r2),
      });
      setSteps((prev) => [...prev, r1, r2]);
      setPlanner(res);
      setDraftStep(null);
      setShowDiagram(false);
      setValidated(false);
      setValidationError(null);
      return;
    }

    const res = await customNextSteps({
      chains,
      file_ids: fileIds,
      steps: stepsPayload,
      draft_step: payloadOf(draft),
    });
    setSteps((prev) => [...prev, draft]);
    setPlanner(res);
    setDraftStep(null);
    setShowDiagram(false);
    setValidated(false);
    setValidationError(null);
  };

  const removeLastStep = async () => {
    const trimmed = steps.slice(0, -1);
    setInitError(null);
    setShowDiagram(false);
    setValidated(false);
    setValidationError(null);
    try {
      const res = await customNextSteps({
        chains,
        file_ids: fileIds,
        steps: trimmed.map((s) => ({ id: s.uid, name: s.name, lanes: s.lanes, params: s.params })),
      });
      setSteps(trimmed);
      setPlanner(res);
    } catch (e) {
      setInitError(readApiError(e));
    }
  };

  const handleValidatePipeline = async () => {
    setValidating(true);
    launch.clearError();
    setValidationError(null);
    setValidated(false);
    try {
      // Validate the whole pipeline against the backend like the ready-made
      // pipelines do: resolves every transition (raises on invalid) and reports
      // any required-but-missing file uploads.
      const summary = await validatePipeline({
        chains,
        file_ids: fileIds,
        steps: stepsPayload,
      });
      const missing = summary.missing_required_uploads ?? [];
      if (missing.length > 0) {
        setValidationError(
          "Missing required uploads: " + missing.map((m) => `${m.step_name}.${m.param}`).join(", "),
        );
        // Same shape the pipeline library reports after a load -- reusing it
        // means the "upload it right on the step" control below works
        // whether the file went missing because the pipeline was just loaded
        // or because validation is what caught it.
        setNeededUploads(
          missing.map((m) => ({
            step_index: m.step_index,
            step_name: m.step_name,
            param: m.param,
            required: true,
          })),
        );
        setShowDiagram(false);
        return;
      }
      setNeededUploads([]);
      setValidated(true);
      setShowDiagram(true);
    } catch (e) {
      setShowDiagram(false);
      setValidationError(readApiError(e));
    } finally {
      setValidating(false);
    }
  };

  // Supplies a missing file straight onto the committed step that needs it
  // (primer_file, reference file, ...) instead of forcing "Start over" just to
  // re-reach that step in the builder.
  const handleStepFileUpload = async (uid: string, param: string, file: File) => {
    const key = `${uid}:${param}`;
    setStepUploadBusy(key);
    setStepUploadError(null);
    try {
      const res = await uploadMutation.mutateAsync(file);
      setSteps((prev) =>
        prev.map((s) =>
          s.uid === uid ? { ...s, params: { ...s.params, [param]: res.file_id } } : s,
        ),
      );
      const idx = steps.findIndex((s) => s.uid === uid);
      setNeededUploads((prev) =>
        prev.filter((u) => !(u.step_index === idx && u.param === param)),
      );
      // The step changed underneath it, so the last validate result no
      // longer speaks for this pipeline.
      setValidated(false);
      setValidationError(null);
    } catch (e) {
      setStepUploadError(readApiError(e));
    } finally {
      setStepUploadBusy(null);
    }
  };

  const launch = useJobLaunch({
    buildEstimate: () => ({ file_ids: fileIds, steps: stepsPayload }),
    start: async () => {
      const sessionId = await getSessionId();
      return startJobMutation.mutateAsync({
        session_id: sessionId,
        file_ids: fileIds,
        steps: stepsPayload,
        convert_to_fasta: false,
        route: "/pipeline/custom-bulk",
        label: "custom bulk pipeline",
      });
    },
    onStarted: (result) => {
      setJobId(result.job_id);
      setTrackingCode(result.tracking_code ?? null);
      queryClient.invalidateQueries({ queryKey: ["session-history"] });
    },
  });

  /**
   * Run, having first put the top of the page back on screen.
   *
   * The button sits at the bottom of a long builder, and pressing it swaps the
   * whole view for the progress panel -- which renders above the fold. Without
   * this the user is left staring at empty space wondering whether anything
   * happened.
   */
  const handleRun = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    launch.launch();
  };

  // The gate dialog can delay the start by a minute or two, so scroll again
  // when the run actually begins rather than only when the button was pressed.
  useEffect(() => {
    if (jobId) window.scrollTo({ top: 0, behavior: "smooth" });
  }, [jobId]);

  const handleStartOver = () => {
    setMode(null);
    setFiles({ r1: null, r2: null });
    setPlanner(null);
    setSteps([]);
    setDraftStep(null);
    setJobId(null);
    setTrackingCode(null);
    setInitError(null);
    setShowDiagram(false);
    setValidated(false);
    setValidationError(null);
    setPendingLoad(null);
    setLoadedName(null);
    setLoadNotice(null);
    setNeededUploads([]);
    launch.clearError();
    initKeyRef.current = "";
  };

  const resetForNewMode = (m: Mode) => {
    setMode(m);
    setPlanner(null);
    setSteps([]);
    setDraftStep(null);
    setValidated(false);
    setShowDiagram(false);
    initKeyRef.current = "";
  };

  // ── Running / finished view ──
  // Keep the process bar on the left and the workflow flowchart on the right;
  // the retention funnel sits underneath the flowchart.
  if (jobId) {
    return (
      <div className="flex flex-col gap-6">
        <div className="grid gap-5 lg:grid-cols-[17rem_1fr]">
          <div className="flex min-w-0 flex-col gap-4">
            <PipelineProgress
              progress={progress}
              steps={progressSteps}
              jobId={jobId}
              onReset={() => setJobId(null)}
            />
            {trackingCode && <TrackingCodeCard trackingCode={trackingCode} />}
          </div>
          <div className="flex flex-col gap-5">
            {steps.length > 0 && (
              <GeneratedWorkflowCard
                title={mode === "paired" ? "Custom · paired-end" : "Custom · single-read"}
                filename="custom-workflow.png"
              >
                {(showArgs) => (
                  <PipelineDiagram
                    steps={steps}
                    paired={mode === "paired"}
                    showArgs={showArgs}
                  />
                )}
              </GeneratedWorkflowCard>
            )}
            {progress.stepStats.length > 0 && (
              <div
                className="rounded-2xl border border-border bg-card p-6"
                style={{ boxShadow: "var(--shadow-card)" }}
              >
                <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Sequence retention
                </h3>
                <div className={cn("mx-auto", mode === "paired" ? "max-w-2xl" : "max-w-md")}>
                  <StepFunnel stepStats={progress.stepStats} showDownload={true}  />
                </div>
              </div>
            )}
          </div>
        </div>
        <SessionHistory entries={historyQuery.data ?? []} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-10">
      {/* Step 1 — read configuration */}
      <section>
        <SectionHeading
          eyebrow="Step 1"
          title="Select read configuration"
          description="How many reads does your dataset have?"
        />
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <ReadModeCard
            active={mode === "single"}
            onClick={() => resetForNewMode("single")}
            title="Single-read data"
            description="Use this option if your dataset contains one FASTQ/FASTA read file per sample."
          />
          <ReadModeCard
            active={mode === "paired"}
            onClick={() => resetForNewMode("paired")}
            title="Paired-end / two-read data"
            description="Use this option if your dataset contains Read 1 and Read 2 files per sample."
          />
        </div>
      </section>

      {/* Step 2 — upload */}
      {mode && (
        <section>
          <SectionHeading
            eyebrow="Step 2"
            title="Upload reads"
            description="Capabilities are detected from the file headers to decide which steps are valid."
          />
          {loadedName && (
            <p className="mt-3 text-sm text-muted-foreground">
              Loaded pipeline: <span className="font-medium text-foreground">{loadedName}</span>
              {neededUploads.length > 0 && (
                <span className="text-amber-600">
                  {" "}— you will need to supply{" "}
                  {neededUploads.map((u) => `${u.step_name}.${u.param}`).join(", ")} again.
                </span>
              )}
            </p>
          )}
          <div className={cn("mt-5 grid gap-4", mode === "paired" && "sm:grid-cols-2")}>
            <FastqUpload
              title={mode === "paired" ? "Read 1 FASTQ" : "FASTQ file"}
              helper={
                mode === "paired"
                  ? "Read 1 file for this sample."
                  : "The single-read file processed by the selected components."
              }
              file={files.r1}
              onUpload={(f) => handleUpload("r1", f)}
              onPickExisting={() => setPickerLane("r1")}
            />
            {mode === "paired" && (
              <FastqUpload
                title="Read 2 FASTQ"
                helper="Read 2 file for this sample."
                file={files.r2}
                onUpload={(f) => handleUpload("r2", f)}
                onPickExisting={() => setPickerLane("r2")}
              />
            )}
          </div>
          {initializing && (
            <p className="mt-3 inline-flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Detecting capabilities…
            </p>
          )}
          {loadNotice && (
            <p className="mt-3 inline-flex items-center gap-2 text-sm text-emerald-600">
              <CheckCircle2 className="h-4 w-4" /> {loadNotice}
            </p>
          )}
          {initError && <p className="mt-3 text-sm text-destructive">{initError}</p>}
        </section>
      )}

      {/* Step 3 — build (pipeline left, components right) */}
      {mode && (
        <section>
          <SectionHeading
            eyebrow="Step 3"
            title="Build your pipeline"
            description="Click a highlighted component to configure and add it. Only steps that are valid right now are enabled, and every addition is validated by the backend."
          />

          <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_1.15fr]">
            {/* Pipeline preview (left) */}
            <div className="flex flex-col gap-5">
              <div
                className="rounded-2xl border border-border bg-card p-5 lg:sticky lg:top-6"
                style={{ boxShadow: "var(--shadow-card)" }}
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                    Pipeline preview
                  </h3>
                  <span className="text-xs text-muted-foreground">
                    {steps.length} step{steps.length === 1 ? "" : "s"}
                    {planner && <> · {planner.stream_mode === "dual" ? "R1 + R2" : "single"}</>}
                  </span>
                </div>

                {steps.length === 0 ? (
                  <p className="mt-4 rounded-lg border border-dashed border-border/70 px-3 py-8 text-center text-sm text-muted-foreground">
                    Your pipeline is empty. Add a component from the right.
                  </p>
                ) : (
                  <PipelinePreview
                    steps={steps}
                    paired={mode === "paired"}
                    onRemoveLast={removeLastStep}
                    neededUploads={neededUploads}
                    uploadBusyKey={stepUploadBusy}
                    onUploadStepFile={handleStepFileUpload}
                  />
                )}
                {initError && <p className="mt-3 text-sm text-destructive">{initError}</p>}
                {stepUploadError && (
                  <p className="mt-3 text-sm text-destructive">{stepUploadError}</p>
                )}

                <div className="mt-5 flex flex-wrap items-center gap-3">
                  <Button
                    variant="outline"
                    onClick={handleValidatePipeline}
                    disabled={steps.length === 0 || validating}
                    className="gap-2"
                  >
                    {validating ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ShieldCheck className="h-4 w-4" />
                    )}
                    Validate pipeline
                  </Button>
                  <Button
                    onClick={handleRun}
                    disabled={steps.length === 0 || !validated || launch.isLaunching}
                    title={!validated ? "Validate the pipeline before running" : undefined}
                    className="gap-2"
                  >
                    {launch.isLaunching ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4" />
                    )}
                    Run pipeline
                  </Button>
                  <Button variant="ghost" onClick={handleStartOver} className="gap-1.5">
                    <RotateCcw className="h-3.5 w-3.5" />
                    Start over
                  </Button>
                </div>
                {validated && !validationError && (
                  <p className="mt-3 inline-flex items-center gap-2 text-sm text-emerald-600">
                    <CheckCircle2 className="h-4 w-4" /> Pipeline validated — ready to run.
                  </p>
                )}
                {!validated && steps.length > 0 && !validationError && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    Validate the pipeline to enable Run.
                  </p>
                )}
                {validationError && (
                  <p className="mt-3 inline-flex items-center gap-2 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4" /> {validationError}
                  </p>
                )}
                {launch.error && (
                  <p className="mt-3 inline-flex items-center gap-2 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4" /> {launch.error}
                  </p>
                )}
              </div>
            </div>

            {/* Components palette (right) */}
            <div
              className="rounded-2xl border border-border bg-card p-5"
              style={{ boxShadow: "var(--shadow-card)" }}
            >
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Components
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {planner?.terminated_by
                  ? "Nothing can follow a step that splits its output."
                  : planner
                    ? "Highlighted components are valid next. Click + to configure."
                    : "Upload your reads to unlock the valid components."}
              </p>

              {/* Without this every component simply appears locked, with no
                  hint that the pipeline is complete rather than broken. */}
              {planner?.terminated_by && (
                <p className="mt-3 inline-flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] leading-relaxed text-amber-700">
                  <Scissors className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    {planner.terminated_by} splits the reads into several files,
                    so the pipeline ends there. Run it — every part will be
                    downloadable — then start a new run from whichever part you
                    need.
                  </span>
                </p>
              )}

              <div className="mt-4 flex flex-col gap-5">
                {grouped.map(({ category, steps: catSteps }) => (
                  <div key={category.key}>
                    <div className="mb-2 flex items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ background: category.color }}
                      />
                      <h4
                        className="text-[11px] font-semibold uppercase tracking-wide"
                        style={{ color: category.text }}
                      >
                        {category.label}
                      </h4>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {catSteps.map((meta) => {
                        const valid = validMap.get(meta.step);
                        const enabled = !!valid && !!planner;
                        return (
                          <StepCube
                            key={meta.step}
                            label={stepShortLabel(meta.step)}
                            family={category.key}
                            color={category.color}
                            tint={category.tint}
                            border={category.border}
                            text={category.text}
                            description={meta.description}
                            enabled={enabled}
                            onClick={() => setDraftStep(meta)}
                          />
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Validated workflow — full width so it scrolls with the page
              instead of being pinned by the sticky pipeline preview. */}
          {showDiagram && steps.length > 0 && (
            <div className="mt-5">
              <GeneratedWorkflowCard
                title={mode === "paired" ? "Custom · paired-end" : "Custom · single-read"}
                filename="custom-workflow.png"
              >
                {(showArgs) => (
                  <PipelineDiagram
                    steps={steps}
                    paired={mode === "paired"}
                    showArgs={showArgs}
                  />
                )}
              </GeneratedWorkflowCard>
            </div>
          )}
        </section>
      )}

      <PipelineLibrary
        steps={stepsPayload}
        chains={chains}
        onLoad={handleLoadPipeline}
      />

      <SessionHistory entries={historyQuery.data ?? []} />

      <PreviousUploadPicker
        open={pickerLane !== null}
        onClose={() => setPickerLane(null)}
        excludeIds={fileIds}
        onPick={(file) => {
          if (pickerLane) handleReuse(pickerLane, file);
        }}
      />

      {draftStep && planner && (
        <DraftDialog
          // Keyed by step so switching straight from one component's form to
          // another re-runs initDraft instead of reusing the previous step's
          // draft values (which would submit params the new step never had).
          key={draftStep.step}
          meta={draftStep}
          valid={validMap.get(draftStep.step)}
          streamMode={planner.stream_mode}
          laneFields={planner.lane_fields}
          laneFieldsConfident={planner.lane_fields_confident}
          onUploadFile={(f) => uploadMutation.mutateAsync(f)}
          onCancel={() => setDraftStep(null)}
          onCommit={commitStep}
        />
      )}

      <JobLaunchGate
        open={launch.gateOpen}
        estimate={launch.estimate}
        onOpenChange={launch.setGateOpen}
        onVerified={launch.startNow}
      />
    </div>
  );
}

// ─────────────────────────── building blocks ───────────────────────────

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

function ReadModeCard({
  active,
  onClick,
  title,
  description,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  description: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group flex h-full flex-col rounded-2xl border bg-card p-5 text-left transition-all duration-200 hover:-translate-y-0.5",
        active ? "border-primary ring-2 ring-primary/30" : "border-border hover:border-primary/40",
      )}
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        <div
          className={cn(
            "h-4 w-4 rounded-full border-2 transition-colors",
            active ? "border-primary bg-primary" : "border-border bg-background",
          )}
        />
      </div>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</p>
    </button>
  );
}

function FastqUpload({
  title,
  helper,
  file,
  onUpload,
  onPickExisting,
}: {
  title: string;
  helper: string;
  file: FileEntry;
  onUpload: (f: File) => void;
  /** Open the picker of files this session already uploaded. */
  onPickExisting?: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const state: UploadState = file?.state ?? "default";
  return (
    <div
      className={cn(
        "rounded-2xl border bg-card p-5 transition-colors",
        state === "uploaded" ? "border-primary/50 ring-1 ring-primary/20" : "border-border",
      )}
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
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
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-semibold text-foreground">{title}</h4>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Required
              </span>
              {state === "uploaded" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                  <CheckCircle2 className="h-3 w-3" /> Loaded
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{helper}</p>
            {file?.name && (
              <p className="mt-1 truncate text-xs font-medium text-foreground">{file.name}</p>
            )}
          </div>
        </div>
        <div>
          <input
            ref={inputRef}
            type="file"
            accept=".fastq,.fq,.fasta,.fa,.gz"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
            }}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant={state === "uploaded" ? "outline" : "default"}
              size="sm"
              onClick={() => inputRef.current?.click()}
              className="gap-1.5"
            >
              <FileUp className="h-3.5 w-3.5" />
              {state === "uploaded" ? "Replace file" : "Choose file"}
            </Button>
            {/* Sequencing files are large and uploads are slow; a second
                pipeline on the same reads should not mean a second transfer. */}
            {onPickExisting && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onPickExisting}
                className="gap-1.5"
                title="Reuse a file you already uploaded in this session"
              >
                <History className="h-3.5 w-3.5" />
                Use previous
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ArrowDown() {
  return (
    <div className="flex justify-center py-1">
      <div className="h-3 w-px bg-border" />
    </div>
  );
}

/** A clickable component "cube" with a + badge (or a lock when unavailable). */
function StepCube({
  label,
  family,
  color,
  tint,
  border,
  text,
  description,
  enabled,
  onClick,
}: {
  label: string;
  family: string;
  color: string;
  tint: string;
  border: string;
  text: string;
  description?: string;
  enabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={!enabled}
      onClick={onClick}
      title={enabled ? description : "Not available at this point"}
      className={cn(
        "flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-all",
        enabled ? "hover:-translate-y-0.5 hover:shadow-sm" : "cursor-not-allowed opacity-45",
      )}
      style={{
        borderColor: enabled ? border : "var(--border)",
        background: enabled ? tint : "transparent",
      }}
    >
      <span className="min-w-0">
        <span
          className="block truncate text-xs font-semibold leading-tight"
          style={{ color: enabled ? text : undefined }}
        >
          {label}
        </span>
        <span className="block truncate text-[9px] text-muted-foreground">{family}</span>
      </span>
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md"
        style={
          enabled
            ? { background: color, color: "white" }
            : { background: "transparent", color: "var(--muted-foreground)" }
        }
      >
        {enabled ? <Plus className="h-3.5 w-3.5" /> : <Lock className="h-3 w-3" />}
      </span>
    </button>
  );
}

// ─────────────────── Parameter popup (modal) ───────────────────

function DraftDialog({
  meta,
  valid,
  streamMode,
  laneFields,
  laneFieldsConfident,
  onUploadFile,
  onCancel,
  onCommit,
}: {
  meta: StepMeta;
  valid: ValidNextStep | undefined;
  streamMode: string;
  laneFields: Record<string, string[]>;
  laneFieldsConfident: Record<string, boolean>;
  onUploadFile: (file: File) => Promise<{ file_id: string }>;
  onCancel: () => void;
  onCommit: (step: UiStep) => Promise<void>;
}) {
  const params = userParams(meta);
  const lanes = laneOptions(valid, streamMode);
  const [lane, setLane] = useState<string>(lanes[0] ?? "paired");
  const [values, setValues] = useState<Record<string, ParamValue>>(() => initDraft(meta));
  const [fileLabels, setFileLabels] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const cat = categoryForStep(meta.step);
  const set = (name: string, v: ParamValue) => setValues((prev) => ({ ...prev, [name]: v }));

  // "always" warns on open; "conditional" starts as a maybe and sharpens into
  // the concrete consequence once the deciding parameter has a value.
  const splitMode = (meta.splits_output ?? null) as SplitMode;
  const splitNotice =
    splitWarning(meta.step, values as Record<string, unknown>) ?? splitHint(splitMode);

  const handleFile = async (name: string, file: File) => {
    setFileLabels((p) => ({ ...p, [name]: `${file.name} …` }));
    try {
      const res = await onUploadFile(file);
      set(name, res.file_id);
      setFileLabels((p) => ({ ...p, [name]: file.name }));
    } catch {
      setFileLabels((p) => ({ ...p, [name]: "upload failed" }));
    }
  };

  const submit = async () => {
    setError(null);
    const out: Record<string, unknown> = {};
    for (const p of params) {
      const k = fieldKind(meta, p);
      const v = values[p.name];
      if (k === "boolean") {
        if (v) out[p.name] = true;
        else if (p.required) out[p.name] = false;
      } else if (k === "number") {
        if (v !== "" && v != null) out[p.name] = Number(v);
        else if (p.required) return setError(`"${humanizeParam(p.name)}" is required`);
      } else if (k === "array") {
        const arr = String(v)
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        if (arr.length) out[p.name] = arr;
        else if (p.required) return setError(`"${humanizeParam(p.name)}" is required`);
      } else if (k === "file") {
        if (v) out[p.name] = v;
        else return setError(`Upload a file for "${humanizeParam(p.name)}"`);
      } else {
        if (v !== "" && v != null) out[p.name] = String(v);
        else if (p.required) return setError(`"${humanizeParam(p.name)}" is required`);
      }
    }
    setSubmitting(true);
    try {
      await onCommit({ uid: nextUid(), name: meta.step, lanes: lane, params: out });
    } catch (e) {
      setError(readApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ background: cat.color }} />
            <div>
              <h3 className="text-lg font-semibold" style={{ color: cat.text }}>
                {meta.step}
              </h3>
              {meta.description && (
                <p className="mt-0.5 text-sm text-muted-foreground">{meta.description}</p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {meta.requires_executable && meta.requires_executable.length > 0 && (
          <p className="mt-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            Runs an external tool on the server:{" "}
            <span className="font-mono">{meta.requires_executable.join(" / ")}</span>
            . The step fails with a clear message if it is not installed there.
          </p>
        )}

        {meta.output_type === "tab" && (
          <p className="mt-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            Outputs a table (TSV), not sequences — this ends the pipeline, so it
            has to be the last step. The sequence ID is always the first column.
          </p>
        )}

        {/* A fan-out ends the pipeline: the lane becomes N files, not one
            stream. Said here, while the parameters are still being chosen,
            rather than after the next step is mysteriously refused. */}
        {splitNotice && (
          <p className="mt-3 inline-flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] leading-relaxed text-amber-700">
            <Scissors className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{splitNotice}</span>
          </p>
        )}

        {lanes.length > 1 && (
          <div className="mt-4">
            <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Apply to lane
            </label>
            <div className="mt-1.5 flex gap-2">
              {lanes.map((l) => (
                <button
                  key={l}
                  type="button"
                  onClick={() => setLane(l)}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                    lane === l
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/40",
                  )}
                >
                  {l === "both" ? "Both (R1 + R2)" : l}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4">
          <ParamFields
            meta={meta}
            params={params}
            values={values}
            fileLabels={fileLabels}
            selectedLane={lane}
            laneFields={laneFields}
            laneFieldsConfident={laneFieldsConfident}
            onSet={set}
            onFile={handleFile}
          />
        </div>

        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={submitting} className="gap-2">
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add &amp; validate
          </Button>
        </div>
      </div>
    </div>
  );
}

function ParamFields({
  meta,
  params,
  values,
  fileLabels,
  selectedLane,
  laneFields,
  laneFieldsConfident,
  onSet,
  onFile,
}: {
  meta: StepMeta;
  params: StepMetaParam[];
  values: Record<string, ParamValue>;
  fileLabels: Record<string, string>;
  selectedLane: string;
  laneFields: Record<string, string[]>;
  laneFieldsConfident: Record<string, boolean>;
  onSet: (name: string, v: ParamValue) => void;
  onFile: (name: string, file: File) => void;
}) {
  if (params.length === 0) {
    return <p className="text-sm text-muted-foreground">No parameters — add it as is.</p>;
  }
  return (
    <div className="grid gap-3.5">
      {params.map((p) => {
        const k = fieldKind(meta, p);
        const v = values[p.name];
        // A realistic value for this exact parameter rather than a syntax
        // reminder: "CPRIMER" says more than "comma,separated,values".
        const guide = paramGuide(meta.step, p.name, k, p.default);
        const choices = k === "boolean" || k === "file" ? undefined : paramChoices(meta.step, p.name);
        // `field_kind` (from the backend's contracts.py field_effects) and
        // `k`/`fieldKind()` (widget shape: text vs array vs ...) are
        // deliberately orthogonal axes -- a field-name param still needs to
        // know if it's one field or a list, but which real fields exist at
        // this stage comes from the backend, not a hand-maintained list.
        const fieldOpts = p.field_kind
          ? fieldOptionsFor(p.name, laneFields, laneFieldsConfident, selectedLane)
          : null;

        return (
          <div key={p.name} className="grid gap-1.5">
            <div className="flex items-center justify-between gap-3">
              <label className="text-xs font-medium text-foreground">
                {humanizeParam(p.name)}
                {p.required && <span className="ml-0.5 text-destructive">*</span>}
              </label>
              <span className="font-mono text-[10px] text-muted-foreground">{p.name}</span>
            </div>

            {k === "boolean" ? (
              <div className="flex items-center gap-3">
                <Switch checked={Boolean(v)} onCheckedChange={(c) => onSet(p.name, c)} />
                <span className="text-xs text-muted-foreground">{v ? "Enabled" : "Disabled"}</span>
              </div>
            ) : k === "file" ? (
              <FileParamInput label={fileLabels[p.name]} onPick={(f) => onFile(p.name, f)} />
            ) : fieldOpts && p.field_kind === "list" ? (
              <MultiSelectField
                value={String(v ?? "")}
                onChange={(next) => onSet(p.name, next)}
                options={fieldOpts.options}
              />
            ) : fieldOpts && p.field_kind === "single" ? (
              <FieldNameSelect
                value={String(v ?? "")}
                onChange={(next) => onSet(p.name, next)}
                options={fieldOpts.options}
                confident={fieldOpts.confident}
              />
            ) : choices ? (
              // A closed set of accepted values -- offered as a list so an
              // invalid mode cannot be typed and rejected at run time.
              <select
                value={String(v ?? "")}
                onChange={(e) => onSet(p.name, e.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm text-foreground shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                {!p.required && <option value="">Default</option>}
                {choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                type={k === "number" ? "number" : "text"}
                value={String(v ?? "")}
                placeholder={guide.example || undefined}
                onChange={(e) => onSet(p.name, e.target.value)}
              />
            )}

            {guide.hint && (
              <p className="text-[11px] leading-snug text-muted-foreground">
                {guide.hint}
                {k === "array" && !fieldOpts && " Separate several with commas."}
              </p>
            )}
            {!guide.hint && k === "array" && !fieldOpts && (
              <p className="text-[11px] text-muted-foreground">
                Separate several values with commas, e.g. {guide.example || "BARCODE, PRIMER"}.
              </p>
            )}
            {fieldOpts && !fieldOpts.confident && (
              <p className="text-[11px] text-muted-foreground">
                Field list not confirmed yet at this stage — pick one if it's listed, or
                type the field name.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

const CUSTOM_FIELD_OPTION = "__custom__";

/**
 * Single field-name picker: a dropdown of the pipeline's known fields at this
 * stage, plus a "Custom value…" escape hatch that swaps in a plain text box
 * -- for a field this very step is about to create, or when the registry
 * isn't confident yet (an unconverted vendor header format).
 */
function FieldNameSelect({
  value,
  onChange,
  options,
  confident,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  confident: boolean;
}) {
  const [isCustom, setIsCustom] = useState(
    () => !confident || (value !== "" && !options.includes(value)),
  );

  if (isCustom) {
    return (
      <div className="flex items-center gap-2">
        <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder="e.g. BARCODE" />
        {options.length > 0 && (
          <button
            type="button"
            className="shrink-0 text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
            onClick={() => setIsCustom(false)}
          >
            Choose from list
          </button>
        )}
      </div>
    );
  }

  return (
    <select
      value={value}
      onChange={(e) => {
        if (e.target.value === CUSTOM_FIELD_OPTION) {
          setIsCustom(true);
          return;
        }
        onChange(e.target.value);
      }}
      className="h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm text-foreground shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <option value="">Select a field…</option>
      {options.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
      <option value={CUSTOM_FIELD_OPTION}>Custom value…</option>
    </select>
  );
}

function FileParamInput({ label, onPick }: { label?: string; onPick: (file: File) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-2">
      <input
        ref={ref}
        type="file"
        accept=".fasta,.fa,.txt,.fastq,.fq,.tab,.tsv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
        }}
      />
      <Button size="sm" variant="outline" onClick={() => ref.current?.click()} className="gap-1.5">
        <FileUp className="h-3.5 w-3.5" /> Upload
      </Button>
      {label && <span className="truncate text-xs text-muted-foreground">{label}</span>}
    </div>
  );
}

// ─────────────────── Generated workflow diagram ───────────────────

/**
 * The diagram card, with a switch between a clean workflow figure and the same
 * figure annotated with every step's parameters.
 *
 * Both views are worth having and neither replaces the other: the plain one is
 * what goes in a paper or a slide, the annotated one is the record of exactly
 * what was run. The PNG export captures whichever is on screen, and names the
 * file accordingly, so a user can save one, flip the switch, and save the other.
 *
 * `children` is a function of the current mode rather than a plain node so the
 * diagram is rebuilt when the switch moves.
 */
function GeneratedWorkflowCard({
  title,
  filename,
  children,
}: {
  title: string;
  /** Base name for the PNG; "-with-arguments" is appended in that mode. */
  filename: string;
  children: (showArgs: boolean) => React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);
  const [showArgs, setShowArgs] = useState(false);

  const handleDownload = async () => {
    if (!ref.current) return;
    setDownloading(true);
    try {
      const dataUrl = await toPng(ref.current, {
        pixelRatio: 2.5,
        backgroundColor: "#ffffff",
        cacheBust: true,
      });
      const base = filename.replace(/\.png$/i, "");
      const a = document.createElement("a");
      a.download = `${base}${showArgs ? "-with-arguments" : ""}.png`;
      a.href = dataUrl;
      a.click();
    } catch (e) {
      console.error("PNG export failed", e);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div
      className="rounded-2xl border border-border bg-card p-6"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          <Workflow className="h-4 w-4" /> Generated workflow
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <DiagramModeToggle showArgs={showArgs} onChange={setShowArgs} />
          <Button
            size="sm"
            variant="outline"
            onClick={handleDownload}
            disabled={downloading}
            className="gap-2"
            title={
              showArgs
                ? "Save this diagram, arguments included, as a PNG"
                : "Save this diagram as a PNG"
            }
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            Download PNG
          </Button>
        </div>
      </div>
      <div className="flex overflow-x-auto rounded-xl border border-border/60 bg-[oklch(0.99_0.005_220)] p-6">
        <div ref={ref} className="mx-auto block bg-white p-8" style={{ width: "100%" }}>
          <div className="mb-5 text-center">
            <div className="mt-0.5 text-base font-semibold text-foreground">{title}</div>
            {showArgs && (
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Parameters as configured
              </div>
            )}
          </div>
          {children(showArgs)}
        </div>
      </div>
    </div>
  );
}

/** Two-way switch between the plain diagram and the annotated one. */
function DiagramModeToggle({
  showArgs,
  onChange,
}: {
  showArgs: boolean;
  onChange: (v: boolean) => void;
}) {
  const options: { value: boolean; label: string; title: string }[] = [
    {
      value: false,
      label: "No arguments",
      title: "Step names only -- the version to put in a figure",
    },
    {
      value: true,
      label: "Show arguments",
      title: "Every step with the parameters it will run with",
    },
  ];
  return (
    <div
      role="group"
      aria-label="Diagram detail"
      className="inline-flex rounded-lg border border-border p-0.5"
    >
      {options.map((opt) => (
        <button
          key={String(opt.value)}
          type="button"
          onClick={() => onChange(opt.value)}
          title={opt.title}
          aria-pressed={showArgs === opt.value}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            showArgs === opt.value
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function DiagramArrow({ height = 26 }: { height?: number }) {
  return (
    <div className="flex justify-center" aria-hidden>
      <svg width="14" height={height} viewBox={`0 0 14 ${height}`}>
        <line
          x1="7"
          y1="0"
          x2="7"
          y2={height - 7}
          stroke="oklch(0.55 0.04 250)"
          strokeWidth="1.5"
        />
        <polygon
          points={`7,${height} 2,${height - 8} 12,${height - 8}`}
          fill="oklch(0.55 0.04 250)"
        />
      </svg>
    </div>
  );
}

function DiagramIO({ label, sublabel }: { label: string; sublabel?: string }) {
  return (
    <div
      className="mx-auto w-[260px] rounded-xl border-2 px-4 py-3 text-center"
      style={{ borderColor: "oklch(0.55 0.04 250)", background: "oklch(0.97 0.01 250)" }}
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-[oklch(0.4_0.06_250)]">
        {label}
      </div>
      {sublabel && (
        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{sublabel}</div>
      )}
    </div>
  );
}

// ── Lane styling (Read 1 vs Read 2) ──────────────────────────────────────
// Distinct accent per channel so the user can tell at a glance which lane a
// component was added to. Kept separate from the step-family palette.
const LANE_STYLE: Record<
  string,
  { label: string; color: string; tint: string; border: string; text: string }
> = {
  R1: {
    label: "Read 1",
    color: "oklch(0.55 0.14 250)",
    tint: "oklch(0.95 0.05 250)",
    border: "oklch(0.7 0.12 250)",
    text: "oklch(0.36 0.13 250)",
  },
  R2: {
    label: "Read 2",
    color: "oklch(0.64 0.16 40)",
    tint: "oklch(0.95 0.07 50)",
    border: "oklch(0.76 0.14 45)",
    text: "oklch(0.42 0.14 40)",
  },
};

function laneStyle(lane: string) {
  return LANE_STYLE[lane] ?? LANE_STYLE.R1;
}

/** Small pill marking which read channel a step belongs to. */
function LaneChip({ lane }: { lane: string }) {
  const ls = laneStyle(lane);
  return (
    <span
      className="shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold leading-none"
      style={{ background: ls.tint, borderColor: ls.border, color: ls.text }}
    >
      {lane}
    </span>
  );
}

// ── Lane-separated workflow diagram ──────────────────────────────────────
const COL_W = 230;
const COL_GAP = 44;
const DUAL_W = COL_W * 2 + COL_GAP;

type DiagramSeg =
  | { kind: "dual"; r1: UiStep[]; r2: UiStep[] }
  | { kind: "band"; step: UiStep }
  | { kind: "merge"; step: UiStep }
  | { kind: "single"; steps: UiStep[] };

/**
 * Split a flat paired pipeline into rendering segments: per-lane "dual"
 * sections, full-width PairSeq "band"s (lanes stay separate), an AssembleSeq
 * "merge" (two lanes → one), and a "single" tail after the merge.
 */
function segmentSteps(steps: UiStep[]): DiagramSeg[] {
  const segs: DiagramSeg[] = [];
  let dual: { r1: UiStep[]; r2: UiStep[] } = { r1: [], r2: [] };
  const single: UiStep[] = [];
  let merged = false;
  const flushDual = () => {
    if (dual.r1.length || dual.r2.length) {
      segs.push({ kind: "dual", r1: dual.r1, r2: dual.r2 });
      dual = { r1: [], r2: [] };
    }
  };
  for (const s of steps) {
    const family = s.name.split(".")[0];
    if (merged) {
      single.push(s);
      continue;
    }
    if (family === "AssembleSeq") {
      flushDual();
      segs.push({ kind: "merge", step: s });
      merged = true;
      continue;
    }
    if (s.lanes === "paired") {
      flushDual();
      segs.push({ kind: "band", step: s });
      continue;
    }
    if (s.lanes === "R2") dual.r2.push(s);
    else if (s.lanes === "both") {
      dual.r1.push(s);
      dual.r2.push(s);
    } else dual.r1.push(s);
  }
  flushDual();
  if (single.length) segs.push({ kind: "single", steps: single });
  return segs;
}

function StepNode({
  step,
  width,
  lane,
  showArgs,
}: {
  step: UiStep;
  width: number | string;
  lane?: string;
  showArgs?: boolean;
}) {
  const st = stepStyle(step.name);
  const args = showArgs ? paramLines(step.params) : [];
  return (
    <div
      className="mx-auto rounded-xl border-2 px-3 py-2.5 text-center shadow-sm"
      style={{ width, background: st.tint, borderColor: st.border, color: st.text }}
    >
      <div className="flex items-center justify-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: st.color }} />
        <span className="truncate text-sm font-semibold">{step.name}</span>
        {lane && <LaneChip lane={lane} />}
      </div>
      <ArgList args={args} defaulted={showArgs && args.length === 0} />
    </div>
  );
}

/**
 * A step's parameters, one per line, for the annotated diagram.
 *
 * Wrapped rather than truncated: this view exists precisely so the values can
 * be read, and a list of copy fields or a primer file reference is often long.
 */
function paramLines(params: Record<string, unknown>): string[] {
  return Object.entries(params ?? {})
    .filter(([, v]) => v !== "" && v != null)
    .map(([k, v]) => {
      if (Array.isArray(v)) return k + " = " + (v as unknown[]).join(", ");
      if (typeof v === "boolean") return k + " = " + (v ? "yes" : "no");
      return k + " = " + String(v);
    });
}

function ArgList({ args, defaulted }: { args: string[]; defaulted?: boolean }) {
  if (defaulted) {
    return (
      <div className="mt-1.5 border-t border-current/20 pt-1.5 text-[9px] italic opacity-60">
        default parameters
      </div>
    );
  }
  if (args.length === 0) return null;
  return (
    <div className="mt-1.5 border-t border-current/20 pt-1.5 text-left">
      {args.map((line) => (
        <div key={line} className="break-words font-mono text-[9px] leading-snug opacity-85">
          {line}
        </div>
      ))}
    </div>
  );
}

function IOBox({
  label,
  sublabel,
  width,
}: {
  label: string;
  sublabel?: string;
  width: number | string;
}) {
  return (
    <div
      className="mx-auto rounded-xl border-2 px-4 py-3 text-center"
      style={{ width, borderColor: "oklch(0.55 0.04 250)", background: "oklch(0.97 0.01 250)" }}
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-[oklch(0.4_0.06_250)]">
        {label}
      </div>
      {sublabel && (
        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{sublabel}</div>
      )}
    </div>
  );
}

function TwoColRow({ left, right }: { left: React.ReactNode; right: React.ReactNode }) {
  return (
    <div
      className="mx-auto grid items-start"
      style={{ width: DUAL_W, gridTemplateColumns: `${COL_W}px ${COL_GAP}px ${COL_W}px` }}
    >
      <div>{left}</div>
      <div />
      <div>{right}</div>
    </div>
  );
}

function LaneColumn({
  steps,
  lane,
  showArgs,
}: {
  steps: UiStep[];
  lane: "R1" | "R2";
  showArgs?: boolean;
}) {
  const ls = laneStyle(lane);
  return (
    <div className="flex flex-col">
      {steps.length === 0 ? (
        <>
          <DiagramArrow height={20} />
          <div
            className="mx-auto w-full rounded-lg border border-dashed px-3 py-2 text-center text-[10px] italic text-muted-foreground"
            style={{ borderColor: ls.border }}
          >
            passes through
          </div>
        </>
      ) : (
        steps.map((s) => (
          <div key={s.uid}>
            <DiagramArrow height={20} />
            <StepNode step={s} width="100%" lane={lane} showArgs={showArgs} />
          </div>
        ))
      )}
    </div>
  );
}

function PairBand({ step, showArgs }: { step: UiStep; showArgs?: boolean }) {
  const st = stepStyle(step.name);
  const args = showArgs ? paramLines(step.params) : [];
  const w = DUAL_W;
  const cL = COL_W / 2;
  const cR = COL_W + COL_GAP + COL_W / 2;
  return (
    <div className="mx-auto" style={{ width: w }}>
      <svg width={w} height="30" viewBox={`0 0 ${w} 30`} className="block">
        <path
          d={`M ${cL} 0 Q ${cL} 22 ${w / 2} 26`}
          stroke={st.color}
          strokeWidth="1.5"
          fill="none"
        />
        <path
          d={`M ${cR} 0 Q ${cR} 22 ${w / 2} 26`}
          stroke={st.color}
          strokeWidth="1.5"
          fill="none"
        />
        <polygon points={`${w / 2},30 ${w / 2 - 5},22 ${w / 2 + 5},22`} fill={st.color} />
      </svg>
      <div
        className="mx-auto rounded-xl border-2 px-4 py-2.5 text-center shadow-sm"
        style={{ width: COL_W + 40, background: st.tint, borderColor: st.border, color: st.text }}
      >
        <div className="flex items-center justify-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: st.color }} />
          <span className="text-sm font-semibold">{step.name}</span>
        </div>
        <div className="mt-0.5 text-[9px] font-semibold uppercase tracking-wider opacity-75">
          Synchronizes Read 1 ⇄ Read 2
        </div>
        <ArgList args={args} defaulted={showArgs && args.length === 0} />
      </div>
      <svg width={w} height="30" viewBox={`0 0 ${w} 30`} className="block">
        <path
          d={`M ${w / 2} 0 Q ${cL} 12 ${cL} 26`}
          stroke={st.color}
          strokeWidth="1.5"
          fill="none"
        />
        <path
          d={`M ${w / 2} 0 Q ${cR} 12 ${cR} 26`}
          stroke={st.color}
          strokeWidth="1.5"
          fill="none"
        />
        <polygon points={`${cL},30 ${cL - 5},22 ${cL + 5},22`} fill={st.color} />
        <polygon points={`${cR},30 ${cR - 5},22 ${cR + 5},22`} fill={st.color} />
      </svg>
    </div>
  );
}

function MergeBand({ step, showArgs }: { step: UiStep; showArgs?: boolean }) {
  const st = stepStyle(step.name);
  const w = DUAL_W;
  const cL = COL_W / 2;
  const cR = COL_W + COL_GAP + COL_W / 2;
  return (
    <div className="mx-auto" style={{ width: w }}>
      <svg width={w} height="34" viewBox={`0 0 ${w} 34`} className="block">
        <path
          d={`M ${cL} 0 Q ${cL} 26 ${w / 2} 30`}
          stroke={st.color}
          strokeWidth="1.5"
          fill="none"
        />
        <path
          d={`M ${cR} 0 Q ${cR} 26 ${w / 2} 30`}
          stroke={st.color}
          strokeWidth="1.5"
          fill="none"
        />
        <polygon points={`${w / 2},34 ${w / 2 - 5},26 ${w / 2 + 5},26`} fill={st.color} />
      </svg>
      <StepNode step={step} width={COL_W + 40} showArgs={showArgs} />
    </div>
  );
}

function PipelineDiagram({
  steps,
  paired,
  showArgs,
}: {
  steps: UiStep[];
  paired: boolean;
  showArgs?: boolean;
}) {
  // Annotated nodes carry several lines of text; give them the extra width
  // rather than letting each parameter wrap to one word per line.
  const nodeWidth = showArgs ? 320 : 260;

  // A run whose last step fans out produces a set of part files, not one
  // result -- promising a "Final repertoire" would misdescribe the output.
  const last = steps[steps.length - 1];
  const endsInSplit =
    !!last && stepSplitsOutput(last.name, last.params as Record<string, unknown>);
  const outputBox = endsInSplit ? (
    <DiagramIO label="Split output" sublabel="One file per part" />
  ) : (
    <DiagramIO label="Final repertoire" sublabel="Processed reads" />
  );

  if (!paired) {
    return (
      <div className="flex flex-col gap-0">
        <DiagramIO label="Input FASTQ" />
        {steps.map((s) => (
          <div key={s.uid}>
            <DiagramArrow />
            <StepNode step={s} width={nodeWidth} showArgs={showArgs} />
          </div>
        ))}
        <DiagramArrow />
        {outputBox}
      </div>
    );
  }

  const segs = segmentSteps(steps);
  const merged = segs.some((s) => s.kind === "merge");

  return (
    <div className="flex flex-col gap-0">
      <TwoColRow
        left={<IOBox label="Read 1" sublabel="Input FASTQ" width="100%" />}
        right={<IOBox label="Read 2" sublabel="Input FASTQ" width="100%" />}
      />
      {segs.map((seg, i) => {
        if (seg.kind === "dual") {
          return (
            <TwoColRow
              key={i}
              left={<LaneColumn steps={seg.r1} lane="R1" showArgs={showArgs} />}
              right={<LaneColumn steps={seg.r2} lane="R2" showArgs={showArgs} />}
            />
          );
        }
        if (seg.kind === "band")
          return <PairBand key={i} step={seg.step} showArgs={showArgs} />;
        if (seg.kind === "merge")
          return <MergeBand key={i} step={seg.step} showArgs={showArgs} />;
        return (
          <div key={i} className="flex flex-col">
            {seg.steps.map((s) => (
              <div key={s.uid}>
                <DiagramArrow />
                <StepNode step={s} width={nodeWidth} showArgs={showArgs} />
              </div>
            ))}
          </div>
        );
      })}
      {merged ? (
        <>
          <DiagramArrow />
          {outputBox}
        </>
      ) : (
        <>
          <TwoColRow left={<DiagramArrow />} right={<DiagramArrow />} />
          <TwoColRow
            left={
              <IOBox
                label="Read 1 output"
                sublabel={endsInSplit ? "Split into parts" : "Processed"}
                width="100%"
              />
            }
            right={
              <IOBox
                label="Read 2 output"
                sublabel={endsInSplit ? "Split into parts" : "Processed"}
                width="100%"
              />
            }
          />
        </>
      )}
    </div>
  );
}

// ── Interactive pipeline preview (lane-separated, shows params) ───────────
function formatParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params ?? {});
  if (entries.length === 0) return "";
  return entries
    .map(([k, v]) => {
      if (Array.isArray(v)) return `${k}=[${(v as unknown[]).join(",")}]`;
      return `${k}=${String(v)}`;
    })
    .join(", ");
}

function PreviewHeader({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-border bg-muted px-3 py-2 text-center text-[11px] font-semibold uppercase tracking-wide text-foreground">
      {label}
    </div>
  );
}

/**
 * Inline "this step is missing a file" chip with its own upload control.
 *
 * Lets a required upload (primer FASTA, reference file, ...) be supplied
 * straight onto the step that needs it -- a loaded/imported pipeline strips
 * these on save, and validation can surface the same gap -- instead of
 * forcing "Start over" just to re-reach that step in the interactive builder.
 */
function StepFileNeed({
  uid,
  param,
  busy,
  onUpload,
}: {
  uid: string;
  param: string;
  busy: boolean;
  onUpload: (uid: string, param: string, file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="mt-1.5 flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-700">
      <AlertCircle className="h-3 w-3 shrink-0" />
      <span className="truncate font-mono">{param}</span>
      <span className="opacity-80">needed</span>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onUpload(uid, param, f);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          inputRef.current?.click();
        }}
        disabled={busy}
        className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-500/50 bg-white/70 px-1.5 py-0.5 font-semibold transition-colors hover:bg-white disabled:opacity-60"
      >
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
        Upload
      </button>
    </div>
  );
}

function PreviewStepBox({
  step,
  index,
  lane,
  isLast,
  onRemoveLast,
  needs,
  uploadBusyKey,
  onUploadStepFile,
}: {
  step: UiStep;
  index: number;
  lane?: string;
  isLast: boolean;
  onRemoveLast: () => void;
  needs?: RequiredUpload[];
  uploadBusyKey?: string | null;
  onUploadStepFile?: (uid: string, param: string, file: File) => void;
}) {
  const st = stepStyle(step.name);
  const params = formatParams(step.params);
  return (
    <div
      className="relative rounded-xl border-2 px-3 py-2"
      style={{ borderColor: st.border, background: st.tint, color: st.text }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="tabular-nums text-[11px] opacity-60">{index}.</span>
            <span className="truncate text-sm font-semibold">{step.name}</span>
            {lane && <LaneChip lane={lane} />}
          </div>
          {params && (
            <div className="mt-0.5 truncate font-mono text-[10px] opacity-80">{params}</div>
          )}
        </div>
        {isLast && (
          <button
            type="button"
            onClick={onRemoveLast}
            title="Remove last step"
            className="shrink-0 opacity-70 transition-opacity hover:opacity-100"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {needs && needs.length > 0 && onUploadStepFile && (
        <div className="flex flex-col gap-1">
          {needs.map((u) => (
            <StepFileNeed
              key={u.param}
              uid={step.uid}
              param={u.param}
              busy={uploadBusyKey === `${step.uid}:${u.param}`}
              onUpload={onUploadStepFile}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PreviewLaneColumn({
  steps,
  lane,
  indexOf,
  lastUid,
  onRemoveLast,
  emptyHint,
  neededByUid,
  uploadBusyKey,
  onUploadStepFile,
}: {
  steps: UiStep[];
  lane: "R1" | "R2";
  indexOf: (uid: string) => number;
  lastUid?: string;
  onRemoveLast: () => void;
  emptyHint: string;
  neededByUid: Map<string, RequiredUpload[]>;
  uploadBusyKey: string | null;
  onUploadStepFile: (uid: string, param: string, file: File) => void;
}) {
  const ls = laneStyle(lane);
  return (
    <div className="flex flex-col">
      <div
        className="mx-auto mb-1 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold"
        style={{ background: ls.tint, borderColor: ls.border, color: ls.text }}
      >
        {ls.label}
      </div>
      {steps.length === 0 ? (
        <div
          className="rounded-lg border border-dashed px-3 py-3 text-center text-[11px] text-muted-foreground"
          style={{ borderColor: ls.border }}
        >
          {emptyHint}
        </div>
      ) : (
        steps.map((s) => (
          <div key={s.uid}>
            <ArrowDown />
            <PreviewStepBox
              step={s}
              index={indexOf(s.uid)}
              lane={lane}
              isLast={s.uid === lastUid}
              onRemoveLast={onRemoveLast}
              needs={neededByUid.get(s.uid)}
              uploadBusyKey={uploadBusyKey}
              onUploadStepFile={onUploadStepFile}
            />
          </div>
        ))
      )}
    </div>
  );
}

function PreviewBand({
  step,
  index,
  isLast,
  onRemoveLast,
  needs,
  uploadBusyKey,
  onUploadStepFile,
}: {
  step: UiStep;
  index: number;
  isLast: boolean;
  onRemoveLast: () => void;
  needs?: RequiredUpload[];
  uploadBusyKey?: string | null;
  onUploadStepFile?: (uid: string, param: string, file: File) => void;
}) {
  const st = stepStyle(step.name);
  const params = formatParams(step.params);
  return (
    <div
      className="rounded-2xl border-2 border-dashed px-4 py-3"
      style={{ borderColor: st.border, background: st.tint, color: st.text }}
    >
      <div className="mb-2 grid grid-cols-2 text-center text-[10px] font-semibold uppercase tracking-wide opacity-60">
        <span>From Read 1 ↘</span>
        <span>↙ From Read 2</span>
      </div>
      <div className="rounded-xl border bg-white/60 px-3 py-2" style={{ borderColor: st.border }}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="tabular-nums text-[11px] opacity-60">{index}.</span>
              <span className="text-sm font-semibold">{step.name}</span>
              <span className="rounded-full bg-white px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide opacity-80">
                Synchronizes Read 1 ⇄ Read 2
              </span>
            </div>
            {params && (
              <div className="mt-0.5 truncate font-mono text-[10px] opacity-80">{params}</div>
            )}
          </div>
          {isLast && (
            <button
              type="button"
              onClick={onRemoveLast}
              title="Remove last step"
              className="shrink-0 opacity-70 transition-opacity hover:opacity-100"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {needs && needs.length > 0 && onUploadStepFile && (
          <div className="flex flex-col gap-1">
            {needs.map((u) => (
              <StepFileNeed
                key={u.param}
                uid={step.uid}
                param={u.param}
                busy={uploadBusyKey === `${step.uid}:${u.param}`}
                onUpload={onUploadStepFile}
              />
            ))}
          </div>
        )}
      </div>
      <div className="mt-2 grid grid-cols-2 text-center text-[10px] font-semibold uppercase tracking-wide opacity-60">
        <span>↙ To Read 1</span>
        <span>To Read 2 ↘</span>
      </div>
    </div>
  );
}

function PreviewMerge({
  step,
  index,
  isLast,
  onRemoveLast,
  needs,
  uploadBusyKey,
  onUploadStepFile,
}: {
  step: UiStep;
  index: number;
  isLast: boolean;
  onRemoveLast: () => void;
  needs?: RequiredUpload[];
  uploadBusyKey?: string | null;
  onUploadStepFile?: (uid: string, param: string, file: File) => void;
}) {
  const st = stepStyle(step.name);
  const params = formatParams(step.params);
  return (
    <div className="flex flex-col items-stretch gap-2">
      <ArrowDown />
      <div
        className="rounded-xl border-2 px-4 py-2.5"
        style={{ borderColor: st.border, background: st.tint, color: st.text }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="tabular-nums text-[11px] opacity-60">{index}.</span>
              <span className="text-sm font-semibold">{step.name}</span>
              <span className="rounded-full bg-white/60 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide">
                Merges Read 1 + Read 2
              </span>
            </div>
            {params && (
              <div className="mt-0.5 truncate font-mono text-[10px] opacity-80">{params}</div>
            )}
          </div>
          {isLast && (
            <button
              type="button"
              onClick={onRemoveLast}
              title="Remove last step"
              className="shrink-0 opacity-70 transition-opacity hover:opacity-100"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {needs && needs.length > 0 && onUploadStepFile && (
          <div className="flex flex-col gap-1">
            {needs.map((u) => (
              <StepFileNeed
                key={u.param}
                uid={step.uid}
                param={u.param}
                busy={uploadBusyKey === `${step.uid}:${u.param}`}
                onUpload={onUploadStepFile}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PipelinePreview({
  steps,
  paired,
  onRemoveLast,
  neededUploads,
  uploadBusyKey,
  onUploadStepFile,
}: {
  steps: UiStep[];
  paired: boolean;
  onRemoveLast: () => void;
  neededUploads: RequiredUpload[];
  uploadBusyKey: string | null;
  onUploadStepFile: (uid: string, param: string, file: File) => void;
}) {
  const lastUid = steps[steps.length - 1]?.uid;
  const indexMap = new Map(steps.map((s, i) => [s.uid, i + 1]));
  const indexOf = (uid: string) => indexMap.get(uid) ?? 0;

  // requires_uploads/missing_required_uploads name a step by its position in
  // `steps` at the time the backend saw it (step_index) -- the same order
  // this array is always sent in -- so that's what maps each gap back to the
  // exact UiStep whose box should offer the upload control.
  const neededByUid = new Map<string, RequiredUpload[]>();
  neededUploads.forEach((u) => {
    const s = steps[u.step_index];
    if (!s) return;
    const list = neededByUid.get(s.uid) ?? [];
    list.push(u);
    neededByUid.set(s.uid, list);
  });

  if (!paired) {
    return (
      <div className="mt-4 flex flex-col">
        <PreviewHeader label="FASTQ input" />
        {steps.map((s) => (
          <div key={s.uid}>
            <ArrowDown />
            <PreviewStepBox
              step={s}
              index={indexOf(s.uid)}
              isLast={s.uid === lastUid}
              onRemoveLast={onRemoveLast}
              needs={neededByUid.get(s.uid)}
              uploadBusyKey={uploadBusyKey}
              onUploadStepFile={onUploadStepFile}
            />
          </div>
        ))}
        <ArrowDown />
        <PreviewHeader label="Filtered FASTQ" />
      </div>
    );
  }

  const segs = segmentSteps(steps);
  const merged = segs.some((x) => x.kind === "merge");

  return (
    <div className="mt-4 flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        <PreviewHeader label="Read 1 FASTQ" />
        <PreviewHeader label="Read 2 FASTQ" />
      </div>
      {segs.map((seg, i) => {
        if (seg.kind === "dual") {
          return (
            <div key={i} className="grid grid-cols-2 gap-3">
              <PreviewLaneColumn
                steps={seg.r1}
                lane="R1"
                indexOf={indexOf}
                lastUid={lastUid}
                onRemoveLast={onRemoveLast}
                emptyHint="No Read 1 components here"
                neededByUid={neededByUid}
                uploadBusyKey={uploadBusyKey}
                onUploadStepFile={onUploadStepFile}
              />
              <PreviewLaneColumn
                steps={seg.r2}
                lane="R2"
                indexOf={indexOf}
                lastUid={lastUid}
                onRemoveLast={onRemoveLast}
                emptyHint="No Read 2 components here"
                neededByUid={neededByUid}
                uploadBusyKey={uploadBusyKey}
                onUploadStepFile={onUploadStepFile}
              />
            </div>
          );
        }
        if (seg.kind === "band") {
          return (
            <PreviewBand
              key={i}
              step={seg.step}
              index={indexOf(seg.step.uid)}
              isLast={seg.step.uid === lastUid}
              onRemoveLast={onRemoveLast}
              needs={neededByUid.get(seg.step.uid)}
              uploadBusyKey={uploadBusyKey}
              onUploadStepFile={onUploadStepFile}
            />
          );
        }
        if (seg.kind === "merge") {
          return (
            <div key={i} className="flex flex-col gap-2">
              <PreviewMerge
                step={seg.step}
                index={indexOf(seg.step.uid)}
                isLast={seg.step.uid === lastUid}
                onRemoveLast={onRemoveLast}
                needs={neededByUid.get(seg.step.uid)}
                uploadBusyKey={uploadBusyKey}
                onUploadStepFile={onUploadStepFile}
              />
              <PreviewHeader label="Assembled sequence" />
            </div>
          );
        }
        return (
          <div key={i} className="flex flex-col">
            {seg.steps.map((s) => (
              <div key={s.uid}>
                <ArrowDown />
                <PreviewStepBox
                  step={s}
                  index={indexOf(s.uid)}
                  isLast={s.uid === lastUid}
                  onRemoveLast={onRemoveLast}
                  needs={neededByUid.get(s.uid)}
                  uploadBusyKey={uploadBusyKey}
                  onUploadStepFile={onUploadStepFile}
                />
              </div>
            ))}
          </div>
        );
      })}
      {merged ? (
        <PreviewHeader label="Output assembled FASTQ" />
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <PreviewHeader label="Read 1 output" />
          <PreviewHeader label="Read 2 output" />
        </div>
      )}
    </div>
  );
}
