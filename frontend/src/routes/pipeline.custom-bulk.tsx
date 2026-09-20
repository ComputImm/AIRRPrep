import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { toPng } from "html-to-image";
import {
  ArrowLeft,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  FileUp,
  Loader2,
  Pencil,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
  Workflow,
  X,
} from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { CustomWorkflowBuilder } from "@/components/CustomWorkflowBuilder";

export const Route = createFileRoute("/pipeline/custom-bulk")({
  head: () => ({
    meta: [
      { title: "Custom bulk AIRR-seq workflow" },
      {
        name: "description",
        content:
          "Build a user-defined preprocessing workflow with FilterSeq components.",
      },
    ],
  }),
  component: CustomBulkPage,
});

// ─────────────────────────── Component catalog ───────────────────────────

type ParamType =
  | "number"
  | "text"
  | "boolean"
  | "select"
  | "multiselect"
  | "file"
  | "scientific";

type ParamDef = {
  key: string;
  label: string;
  helper: string;
  type: ParamType;
  default: string | number | boolean | string[];
  flag: string;
  options?: string[];
  required?: boolean;
};

type ComponentKey =
  | "length"
  | "quality"
  | "missing"
  | "repeats"
  | "trimqual"
  | "maskqual";

type ComponentDef = {
  key: ComponentKey;
  name: string;
  cli: string;
  description: string;
  color: string;
  tint: string;
  border: string;
  text: string;
  params: ParamDef[];
};

const COMPONENTS: ComponentDef[] = [
  {
    key: "length",
    name: "FilterSeq.length",
    cli: "FilterSeq length",
    description: "Removes reads shorter than the minimum required sequence length.",
    color: "oklch(0.6 0.18 245)",
    tint: "oklch(0.96 0.04 245)",
    border: "oklch(0.85 0.08 245)",
    text: "oklch(0.4 0.16 245)",
    params: [
      {
        key: "min_length",
        label: "Minimum sequence length",
        helper: "Minimum sequence length required; shorter reads are removed.",
        type: "number",
        default: 250,
        flag: "--min_length",
      },
      {
        key: "inner",
        label: "Apply to internal region",
        helper: "Applies length checking to the internal region for stricter filtering.",
        type: "boolean",
        default: true,
        flag: "--inner",
      },
      {
        key: "missing_chars",
        label: "Missing characters",
        helper: "Characters treated as unknown bases or gaps.",
        type: "text",
        default: "#",
        flag: "--missing_chars",
      },
    ],
  },
  {
    key: "quality",
    name: "FilterSeq.quality",
    cli: "FilterSeq quality",
    description: "Filters reads based on minimum sequence quality.",
    color: "oklch(0.65 0.13 195)",
    tint: "oklch(0.96 0.04 195)",
    border: "oklch(0.85 0.08 195)",
    text: "oklch(0.4 0.12 195)",
    params: [
      {
        key: "min_qual",
        label: "Minimum quality score",
        helper:
          "Minimum allowed quality score; reads below this threshold are filtered out.",
        type: "number",
        default: 0,
        flag: "--min_qual",
      },
      {
        key: "inner",
        label: "Evaluate internal region",
        helper:
          "Quality is evaluated over the full or internal region depending on this setting.",
        type: "boolean",
        default: true,
        flag: "--inner",
      },
      {
        key: "missing_chars",
        label: "Missing characters",
        helper: "Bases treated as invalid or unknown for quality calculation.",
        type: "text",
        default: "#",
        flag: "--missing_chars",
      },
    ],
  },
  {
    key: "missing",
    name: "FilterSeq.missing",
    cli: "FilterSeq missing",
    description: "Removes reads with too many ambiguous or missing bases.",
    color: "oklch(0.6 0.18 300)",
    tint: "oklch(0.96 0.04 300)",
    border: "oklch(0.85 0.08 300)",
    text: "oklch(0.4 0.16 300)",
    params: [
      {
        key: "max_missing",
        label: "Maximum missing bases",
        helper: "Maximum allowed number of ambiguous bases, such as N.",
        type: "number",
        default: 10,
        flag: "--max_missing",
      },
      {
        key: "inner",
        label: "Count internal region",
        helper: "Counts missing bases across the full or internal region.",
        type: "boolean",
        default: true,
        flag: "--inner",
      },
      {
        key: "missing_chars",
        label: "Missing characters",
        helper: "Defines which characters are considered missing.",
        type: "text",
        default: "#",
        flag: "--missing_chars",
      },
    ],
  },
  {
    key: "repeats",
    name: "FilterSeq.repeats",
    cli: "FilterSeq repeats",
    description: "Filters repetitive or low-complexity reads.",
    color: "oklch(0.7 0.17 50)",
    tint: "oklch(0.96 0.04 50)",
    border: "oklch(0.85 0.1 50)",
    text: "oklch(0.45 0.15 50)",
    params: [
      {
        key: "max_repeat",
        label: "Maximum repeat level",
        helper: "Maximum allowed level of repetitive or low-complexity sequence.",
        type: "number",
        default: 15,
        flag: "--max_repeat",
      },
      {
        key: "include_missing",
        label: "Include missing bases",
        helper:
          "Whether ambiguous bases, such as N, are included in repeat calculation.",
        type: "boolean",
        default: false,
        flag: "--include_missing",
      },
      {
        key: "inner",
        label: "Check internal region",
        helper: "Checks repetitive sequence patterns in the full or internal region.",
        type: "boolean",
        default: true,
        flag: "--inner",
      },
      {
        key: "missing_chars",
        label: "Missing characters",
        helper: "Defines ambiguous bases used in the repeat calculation.",
        type: "text",
        default: "#",
        flag: "--missing_chars",
      },
    ],
  },
  {
    key: "trimqual",
    name: "FilterSeq.trimqual",
    cli: "FilterSeq trimqual",
    description: "Trims low-quality bases using a sliding-window quality threshold.",
    color: "oklch(0.65 0.15 150)",
    tint: "oklch(0.96 0.04 150)",
    border: "oklch(0.85 0.08 150)",
    text: "oklch(0.4 0.13 150)",
    params: [
      {
        key: "min_qual",
        label: "Minimum trimming quality",
        helper: "Quality threshold for trimming; bases below this threshold are trimmed.",
        type: "number",
        default: 0,
        flag: "--min_qual",
      },
      {
        key: "window",
        label: "Sliding window size",
        helper: "Size of the sliding window used to compute average quality.",
        type: "number",
        default: 10,
        flag: "--window",
      },
      {
        key: "reverse",
        label: "Trim from reverse end",
        helper: "If enabled, trimming starts from the 3′ end instead of the 5′ end.",
        type: "boolean",
        default: false,
        flag: "--reverse",
      },
    ],
  },
  {
    key: "maskqual",
    name: "FilterSeq.maskqual",
    cli: "FilterSeq maskqual",
    description: "Masks low-quality bases instead of removing them.",
    color: "oklch(0.55 0.08 230)",
    tint: "oklch(0.96 0.03 230)",
    border: "oklch(0.85 0.05 230)",
    text: "oklch(0.4 0.08 230)",
    params: [
      {
        key: "min_qual",
        label: "Minimum masking quality",
        helper:
          "Bases with quality below this threshold are masked and replaced with N instead of being removed.",
        type: "number",
        default: 0,
        flag: "--min_qual",
      },
    ],
  },
];

const COMPONENT_MAP: Record<ComponentKey, ComponentDef> = COMPONENTS.reduce(
  (acc, c) => ({ ...acc, [c.key]: c }),
  {} as Record<ComponentKey, ComponentDef>,
);

// ────────────────────────────── State types ──────────────────────────────

type ReadMode = null | "single" | "paired";
type ParamValue = string | number | boolean | string[];
type PipelineStep = {
  id: string;
  key: ComponentKey;
  values: Record<string, ParamValue>;
  /**
   * For paired-end read branches: index of the PairSeq checkpoint this
   * component was added AFTER. 0 = before any PairSeq, 1 = after PairSeq #1,
   * 2 = after PairSeq #2, etc. Undefined for non-paired contexts.
   */
  checkpoint?: number;
};
type UploadState = "default" | "uploading" | "uploaded" | "error";
type FileEntry = { name: string; state: UploadState } | null;

// ──────────────────────────────── Helpers ────────────────────────────────

type AnyDef = {
  key: string;
  name: string;
  cli: string;
  description: string;
  color: string;
  tint: string;
  border: string;
  text: string;
  params: ParamDef[];
};

const defaultValues = (def: AnyDef): Record<string, ParamValue> => {
  const v: Record<string, ParamValue> = {};
  def.params.forEach((p) => (v[p.key] = p.default));
  return v;
};

const formatSummary = (def: AnyDef, values: Record<string, ParamValue>) =>
  def.params
    .map((p) => {
      const v = values[p.key];
      if (p.type === "boolean") return `${p.key}=${v ? "true" : "false"}`;
      if (p.type === "multiselect") {
        const arr = Array.isArray(v) ? v : [];
        return `${p.key}=[${arr.join(",")}]`;
      }
      return `${p.key}=${v}`;
    })
    .join(", ");

const buildCommand = (def: AnyDef, values: Record<string, ParamValue>) => {
  const parts: string[] = [def.cli];
  for (const p of def.params) {
    const v = values[p.key];
    if (p.type === "boolean") {
      if (v) parts.push(p.flag);
    } else if (p.type === "number" || p.type === "scientific") {
      parts.push(`${p.flag} ${v}`);
    } else if (p.type === "select") {
      parts.push(`${p.flag} ${v}`);
    } else if (p.type === "multiselect") {
      const arr = Array.isArray(v) ? v : [];
      if (arr.length > 0) parts.push(`${p.flag} ${arr.join(",")}`);
    } else if (p.type === "file") {
      parts.push(`${p.flag} ${v || "reference.fasta"}`);
    } else {
      parts.push(`${p.flag} "${v}"`);
    }
  }
  return parts.join(" ");
};

const validateValues = (def: AnyDef, values: Record<string, ParamValue>) => {
  for (const p of def.params) {
    const v = values[p.key];
    if ((p.type === "number" || p.type === "scientific") && (v === "" || Number.isNaN(Number(v)))) {
      return `${p.label} must be a valid number.`;
    }
    if (p.type === "text" && typeof v === "string" && v.length === 0) {
      return `${p.label} cannot be empty.`;
    }
    if (p.type === "file" && p.required && (!v || (typeof v === "string" && v.length === 0))) {
      return `${p.label} is required.`;
    }
  }
  return null;
};

// ───────────────────────────────── Page ──────────────────────────────────

function CustomBulkPage() {
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
            Custom bulk AIRR-seq workflow
          </h1>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-muted-foreground">
            Build a user-defined preprocessing workflow: pick your read
            configuration, then chain any pRESTO step. Only steps that are valid
            at each point light up, and every choice is validated against the
            backend before it is added.
          </p>
        </header>

        <section className="mt-10">
          <CustomWorkflowBuilder />
        </section>
      </main>
    </div>
  );
}

// ──────────────────────────── Single-read UI ─────────────────────────────

function SingleReadBuilder() {
  const [pipeline, setPipeline] = useState<PipelineStep[]>([]);
  const [expandedKey, setExpandedKey] = useState<ComponentKey | null>(null);
  const [draftValues, setDraftValues] = useState<Record<string, ParamValue>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<Record<string, ParamValue>>({});

  const [file, setFile] = useState<FileEntry>(null);
  const [validating, setValidating] = useState(false);
  const [validated, setValidated] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const toggleExpand = (key: ComponentKey) => {
    if (expandedKey === key) {
      setExpandedKey(null);
      return;
    }
    setExpandedKey(key);
    setDraftValues(defaultValues(COMPONENT_MAP[key]));
  };

  const updateDraft = (k: string, v: ParamValue) =>
    setDraftValues((prev) => ({ ...prev, [k]: v }));

  const addStepFromDraft = (key: ComponentKey) => {
    const def = COMPONENT_MAP[key];
    const err = validateValues(def, draftValues);
    if (err) return;
    const step: PipelineStep = {
      id: `${key}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      key,
      values: { ...draftValues },
    };
    setPipeline((p) => [...p, step]);
    setExpandedKey(null);
    setValidated(false);
  };

  const removeStep = (id: string) => {
    setPipeline((p) => p.filter((s) => s.id !== id));
    if (editingId === id) setEditingId(null);
    setValidated(false);
  };

  const moveStep = (id: string, dir: -1 | 1) => {
    setPipeline((p) => {
      const idx = p.findIndex((s) => s.id === id);
      if (idx < 0) return p;
      const j = idx + dir;
      if (j < 0 || j >= p.length) return p;
      const next = [...p];
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  };

  const beginEdit = (step: PipelineStep) => {
    setEditingId(step.id);
    setEditValues({ ...step.values });
  };

  const updateEdit = (k: string, v: ParamValue) =>
    setEditValues((prev) => ({ ...prev, [k]: v }));

  const saveEdit = (id: string) => {
    const step = pipeline.find((s) => s.id === id);
    if (!step) return;
    const def = COMPONENT_MAP[step.key];
    const err = validateValues(def, editValues);
    if (err) return;
    setPipeline((p) =>
      p.map((s) => (s.id === id ? { ...s, values: { ...editValues } } : s)),
    );
    setEditingId(null);
    setValidated(false);
  };

  const handleUpload = (f: File) => {
    setFile({ name: f.name, state: "uploading" });
    setValidated(false);
    setTimeout(() => setFile({ name: f.name, state: "uploaded" }), 700);
  };

  const handleValidate = () => {
    setValidating(true);
    setValidationError(null);
    setTimeout(() => {
      setValidating(false);
      if (file?.state !== "uploaded") {
        setValidationError("Please upload a FASTQ file.");
        return;
      }
      if (pipeline.length === 0) {
        setValidationError("Add at least one preprocessing component.");
        return;
      }
      for (const step of pipeline) {
        const def = COMPONENT_MAP[step.key];
        const err = validateValues(def, step.values);
        if (err) {
          setValidationError(`${def.name}: ${err}`);
          return;
        }
      }
      setValidated(true);
    }, 700);
  };

  const compactPath = useMemo(() => {
    if (pipeline.length === 0) return "FASTQ → Output";
    const middle = pipeline
      .map((s) => {
        const def = COMPONENT_MAP[s.key];
        const first = def.params[0];
        const v = s.values[first.key];
        return `${def.name}(${first.key}=${v})`;
      })
      .join(" → ");
    return `FASTQ → ${middle} → Output`;
  }, [pipeline]);

  return (
    <>
      <section className="mt-12">
        <SectionHeading
          eyebrow="Step 2"
          title="Configure single-read preprocessing workflow"
          description="Upload the FASTQ file, configure components, then add them to the pipeline."
        />

        <div className="mt-5">
          <FastqUpload file={file} onUpload={handleUpload} />
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_1.15fr]">
          {/* Left: choosable components with inline params */}
          <div
            className="rounded-2xl border border-border bg-card p-5"
            style={{ boxShadow: "var(--shadow-card)" }}
          >
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Choosable components
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Configure parameters inside a component, then add it to the pipeline.
            </p>

            <div className="mt-4 grid gap-3">
              {COMPONENTS.map((c) => (
                <ComponentCard
                  key={c.key}
                  def={c}
                  expanded={expandedKey === c.key}
                  values={expandedKey === c.key ? draftValues : null}
                  onToggle={() => toggleExpand(c.key)}
                  onUpdate={updateDraft}
                  onAdd={() => addStepFromDraft(c.key)}
                />
              ))}
            </div>
          </div>

          {/* Right: pipeline preview */}
          <div className="flex flex-col gap-5">
            <div
              className="rounded-2xl border border-border bg-card p-5"
              style={{ boxShadow: "var(--shadow-card)" }}
            >
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Pipeline preview
                </h3>
                <span className="text-xs text-muted-foreground">
                  {pipeline.length} step{pipeline.length === 1 ? "" : "s"}
                </span>
              </div>

              {pipeline.length > 0 && (
                <pre className="mt-3 overflow-x-auto rounded-lg bg-muted px-3 py-2 font-mono text-[11px] text-foreground">
                  {compactPath}
                </pre>
              )}

              <div className="mt-4">
                <PipelineFlow
                  steps={pipeline}
                  editingId={editingId}
                  editValues={editValues}
                  onEdit={beginEdit}
                  onCancelEdit={() => setEditingId(null)}
                  onUpdateEdit={updateEdit}
                  onSaveEdit={saveEdit}
                  onRemove={removeStep}
                  onMove={moveStep}
                />
              </div>
            </div>

            <CommandPreview pipeline={pipeline} />
          </div>
        </div>

        {/* Workflow preview */}
        <div className="mt-6">
          <Button
            variant="outline"
            onClick={() => setPreviewOpen((p) => !p)}
            className="gap-2"
            disabled={pipeline.length === 0}
          >
            <Workflow className="h-4 w-4" />
            {previewOpen ? "Hide workflow preview" : "Generate workflow preview"}
          </Button>

          {previewOpen && pipeline.length > 0 && (
            <>
              <GeneratedWorkflowCard
                filename="custom-bulk-single-read-workflow.png"
                title="Generated workflow · Single-read"
              >
                {(showArgs) => (
                  <SingleGeneratedDiagram pipeline={pipeline} showArgs={showArgs} />
                )}
              </GeneratedWorkflowCard>
              <RetentionFunnelSingle pipeline={pipeline} />
            </>
          )}
        </div>


        {/* Actions */}
        <section className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap gap-3">
            <Button onClick={handleValidate} disabled={validating} className="gap-2">
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
                  ? "Configuration valid"
                  : "Validate configuration"}
            </Button>
            <Button variant="outline" disabled={!validated} className="gap-2">
              Continue
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
          {validationError && (
            <div className="inline-flex items-center gap-2 rounded-full bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive">
              <AlertCircle className="h-3.5 w-3.5" />
              {validationError}
            </div>
          )}
          {validated && !validationError && (
            <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Ready to run
            </div>
          )}
        </section>
      </section>
    </>
  );
}

// ────────────────────────── Building blocks ──────────────────────────────

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
  file,
  onUpload,
}: {
  file: FileEntry;
  onUpload: (f: File) => void;
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
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-semibold text-foreground">FASTQ file</h4>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Required
              </span>
              {state === "uploaded" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                  <CheckCircle2 className="h-3 w-3" /> Loaded
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Upload the single-read FASTQ file that will be processed by the selected components.
            </p>
            {file?.name && (
              <p className="mt-1 truncate text-xs font-medium text-foreground">
                {file.name}
              </p>
            )}
          </div>
        </div>
        <div>
          <input
            ref={inputRef}
            type="file"
            accept=".fastq,.fq,.gz"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
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
        </div>
      </div>
    </div>
  );
}

// ──────────────────── Expandable component card ──────────────────────────

function ComponentCard({
  def,
  expanded,
  values,
  onToggle,
  onUpdate,
  onAdd,
}: {
  def: AnyDef;
  expanded: boolean;
  values: Record<string, ParamValue> | null;
  onToggle: () => void;
  onUpdate: (key: string, value: ParamValue) => void;
  onAdd: () => void;
}) {
  const err = expanded && values ? validateValues(def, values) : null;

  return (
    <div
      className={cn(
        "rounded-xl border bg-background transition-colors",
        expanded ? "ring-1" : "hover:border-primary/40",
      )}
      style={{
        borderColor: expanded ? def.border : undefined,
        ...(expanded
          ? ({ "--tw-ring-color": def.border } as React.CSSProperties)
          : {}),
      }}
    >
      <div className="flex items-start justify-between gap-3 p-3.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: def.color }}
            />
            <h4 className="truncate text-sm font-semibold text-foreground">
              {def.name}
            </h4>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {def.description}
          </p>
        </div>
        <Button
          size="sm"
          variant={expanded ? "ghost" : "outline"}
          className="gap-1.5 shrink-0"
          onClick={onToggle}
        >
          {expanded ? (
            <>
              <X className="h-3.5 w-3.5" />
              Close
            </>
          ) : (
            <>
              <ChevronDown className="h-3.5 w-3.5" />
              Configure
            </>
          )}
        </Button>
      </div>

      {expanded && values && (
        <div
          className="border-t px-3.5 pb-3.5 pt-3"
          style={{ borderColor: def.border, background: def.tint }}
        >
          <ParameterForm def={def} values={values} onUpdate={onUpdate} />
          <div className="mt-4 flex items-center justify-between gap-3">
            {err ? (
              <span className="text-[11px] font-medium text-destructive">
                {err}
              </span>
            ) : (
              <span className="text-[11px] text-muted-foreground">
                Values stored when added to pipeline.
              </span>
            )}
            <Button
              size="sm"
              className="gap-1.5"
              onClick={onAdd}
              disabled={Boolean(err)}
            >
              <Plus className="h-3.5 w-3.5" />
              Add to pipeline
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ParameterForm({
  def,
  values,
  onUpdate,
}: {
  def: AnyDef;
  values: Record<string, ParamValue>;
  onUpdate: (key: string, value: ParamValue) => void;
}) {
  return (
    <div className="grid gap-3.5">
      {def.params.map((p) => {
        const v = values[p.key];
        return (
          <div key={p.key} className="grid gap-1.5">
            <div className="flex items-center justify-between gap-3">
              <label className="text-xs font-medium text-foreground">
                {p.label}
              </label>
              <span className="font-mono text-[10px] text-muted-foreground">
                {p.flag}
              </span>
            </div>
            {p.type === "boolean" ? (
              <div className="flex items-center gap-3">
                <Switch
                  checked={Boolean(v)}
                  onCheckedChange={(c) => onUpdate(p.key, c)}
                />
                <span className="text-xs text-muted-foreground">
                  {v ? "Enabled" : "Disabled"}
                </span>
              </div>
            ) : p.type === "number" ? (
              <Input
                type="number"
                value={String(v)}
                onChange={(e) =>
                  onUpdate(
                    p.key,
                    e.target.value === "" ? "" : Number(e.target.value),
                  )
                }
              />
            ) : p.type === "scientific" ? (
              <Input
                type="text"
                value={String(v)}
                placeholder="e.g. 1e-5"
                onChange={(e) => onUpdate(p.key, e.target.value)}
              />
            ) : p.type === "select" ? (
              <select
                value={String(v)}
                onChange={(e) => onUpdate(p.key, e.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {(p.options ?? []).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : p.type === "multiselect" ? (
              <MultiSelect
                options={p.options ?? []}
                value={Array.isArray(v) ? v : []}
                onChange={(arr) => onUpdate(p.key, arr)}
              />
            ) : p.type === "file" ? (
              <FileParamInput
                value={typeof v === "string" ? v : ""}
                onChange={(name) => onUpdate(p.key, name)}
              />
            ) : (
              <Input
                type="text"
                value={String(v)}
                onChange={(e) => onUpdate(p.key, e.target.value)}
              />
            )}
            <p className="text-[11px] text-muted-foreground">{p.helper}</p>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────── Pipeline preview ────────────────────────────

function PipelineFlow({
  steps,
  editingId,
  editValues,
  onEdit,
  onCancelEdit,
  onUpdateEdit,
  onSaveEdit,
  onRemove,
  onMove,
}: {
  steps: PipelineStep[];
  editingId: string | null;
  editValues: Record<string, ParamValue>;
  onEdit: (step: PipelineStep) => void;
  onCancelEdit: () => void;
  onUpdateEdit: (key: string, value: ParamValue) => void;
  onSaveEdit: (id: string) => void;
  onRemove: (id: string) => void;
  onMove: (id: string, dir: -1 | 1) => void;
}) {
  if (steps.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-8 text-center">
        <p className="text-sm text-muted-foreground">
          No components yet. Configure a component on the left and add it to start building your pipeline.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-stretch gap-2">
      <FlowBlock label="FASTQ input" tone="io" />
      {steps.map((step, idx) => {
        const def = COMPONENT_MAP[step.key];
        const isEditing = step.id === editingId;
        const summary = formatSummary(def, step.values);
        const editErr = isEditing ? validateValues(def, editValues) : null;
        return (
          <div key={step.id} className="flex flex-col items-stretch gap-2">
            <ArrowDown />
            <div
              className="rounded-xl border"
              style={{
                background: def.tint,
                borderColor: def.border,
                color: def.text,
              }}
            >
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-bold text-white"
                    style={{ background: def.color }}
                  >
                    {idx + 1}
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{def.name}</div>
                    <div className="truncate font-mono text-[11px] opacity-80">
                      {summary}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <IconBtn
                    label="Edit"
                    onClick={() =>
                      isEditing ? onCancelEdit() : onEdit(step)
                    }
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </IconBtn>
                  <IconBtn
                    label="Move up"
                    disabled={idx === 0}
                    onClick={() => onMove(step.id, -1)}
                  >
                    <ChevronUp className="h-3.5 w-3.5" />
                  </IconBtn>
                  <IconBtn
                    label="Move down"
                    disabled={idx === steps.length - 1}
                    onClick={() => onMove(step.id, 1)}
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </IconBtn>
                  <IconBtn label="Remove" onClick={() => onRemove(step.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </IconBtn>
                </div>
              </div>

              {isEditing && (
                <div
                  className="border-t bg-background/60 px-4 pb-4 pt-3"
                  style={{ borderColor: def.border }}
                >
                  <ParameterForm
                    def={def}
                    values={editValues}
                    onUpdate={onUpdateEdit}
                  />
                  <div className="mt-4 flex items-center justify-between gap-3">
                    {editErr ? (
                      <span className="text-[11px] font-medium text-destructive">
                        {editErr}
                      </span>
                    ) : (
                      <span />
                    )}
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost" onClick={onCancelEdit}>
                        Cancel
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => onSaveEdit(step.id)}
                        disabled={Boolean(editErr)}
                      >
                        Save changes
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
      <ArrowDown />
      <FlowBlock label="Filtered FASTQ" tone="io" />
    </div>
  );
}

function IconBtn({
  children,
  onClick,
  disabled,
  label,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-md border border-transparent bg-white/60 transition-colors hover:bg-white",
        disabled && "pointer-events-none opacity-40",
      )}
    >
      {children}
    </button>
  );
}

// ───────────────────────────── Command preview ───────────────────────────

function CommandPreview({ pipeline }: { pipeline: PipelineStep[] }) {
  return (
    <div
      className="rounded-2xl border border-border bg-card p-5"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Command preview
      </h3>
      {pipeline.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Add configured components to see the generated commands.
        </p>
      ) : (
        <pre className="mt-3 overflow-x-auto rounded-lg bg-muted px-3 py-2.5 font-mono text-xs leading-relaxed text-foreground">
          {pipeline
            .map((s) => buildCommand(COMPONENT_MAP[s.key], s.values))
            .join("\n\n")}
        </pre>
      )}
    </div>
  );
}

// ─────────────────────────────── Flow block ──────────────────────────────

function FlowBlock({
  label,
  sublabel,
  color,
  tint,
  border,
  text,
  tone,
}: {
  label: string;
  sublabel?: string;
  color?: string;
  tint?: string;
  border?: string;
  text?: string;
  tone?: "io";
}) {
  if (tone === "io") {
    return (
      <div className="mx-auto w-full max-w-xs rounded-xl border border-border bg-muted px-4 py-2.5 text-center text-sm font-semibold text-foreground">
        {label}
      </div>
    );
  }
  return (
    <div
      className="mx-auto w-full max-w-sm rounded-xl border px-4 py-2.5 text-center text-sm font-semibold"
      style={{ background: tint, borderColor: border, color: text }}
    >
      <div>
        <span
          className="mr-2 inline-block h-2 w-2 rounded-full align-middle"
          style={{ background: color }}
        />
        {label}
      </div>
      {sublabel && (
        <div className="mt-1 truncate font-mono text-[10px] opacity-80">
          {sublabel}
        </div>
      )}
    </div>
  );
}

function ArrowDown() {
  return (
    <div className="mx-auto flex h-5 w-px items-center justify-center bg-border" />
  );
}

// ─────────────────────── MultiSelect / FileParam ─────────────────────────

function MultiSelect({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const toggle = (o: string) => {
    if (value.includes(o)) onChange(value.filter((x) => x !== o));
    else onChange([...value, o]);
  };
  return (
    <div className="flex flex-wrap gap-1.5 rounded-md border border-input bg-background p-2">
      {options.map((o) => {
        const active = value.includes(o);
        return (
          <button
            key={o}
            type="button"
            onClick={() => toggle(o)}
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:border-primary/40",
            )}
          >
            {o}
          </button>
        );
      })}
      {value.length === 0 && (
        <span className="px-1 py-0.5 text-[11px] text-muted-foreground">
          None selected
        </span>
      )}
    </div>
  );
}

function FileParamInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (name: string) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-2 rounded-md border border-input bg-background px-2 py-1.5">
      <input
        ref={ref}
        type="file"
        accept=".fasta,.fa,.fna"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onChange(f.name);
        }}
      />
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={() => ref.current?.click()}
      >
        <FileUp className="h-3.5 w-3.5" />
        {value ? "Replace" : "Upload FASTA"}
      </Button>
      <span className="truncate text-xs text-muted-foreground">
        {value || "No file selected"}
      </span>
    </div>
  );
}

// ──────────────────────── Paired-end catalog ─────────────────────────────

const FIELD_OPTIONS = [
  "BARCODE",
  "UMI",
  "MID",
  "PRIMER",
  "SAMPLE",
  "CELL",
  "CLUSTER",
  "GROUP",
  "CONSCOUNT",
  "DUPCOUNT",
  "COUNT",
  "READCOUNT",
  "SEQCOUNT",
  "QUALITY",
  "CONSENSUS",
];

const PAIRSEQ_DEF: AnyDef = {
  key: "pairseq",
  name: "PairSeq",
  cli: "PairSeq",
  description:
    "Pairs or synchronizes Read 1 and Read 2 using sequence identifiers or annotation fields while keeping the workflow as two separate branches.",
  color: "oklch(0.6 0.15 220)",
  tint: "oklch(0.96 0.03 220)",
  border: "oklch(0.85 0.07 220)",
  text: "oklch(0.4 0.14 220)",
  params: [
    {
      key: "coord_type",
      label: "Coordinate extraction method",
      helper:
        "Method used to identify matching sequence pairs between Read 1 and Read 2.",
      type: "select",
      default: "id",
      options: ["id", "illumina", "presto", "IMGT"],
      flag: "--coord_type",
    },
    {
      key: "fields_1",
      label: "Fields copied from Read 1 to Read 2",
      helper: "Annotation fields copied from Read 1 to Read 2.",
      type: "multiselect",
      default: [],
      options: FIELD_OPTIONS,
      flag: "--fields_1",
    },
    {
      key: "fields_2",
      label: "Fields copied from Read 2 to Read 1",
      helper: "Annotation fields copied from Read 2 to Read 1.",
      type: "multiselect",
      default: [],
      options: FIELD_OPTIONS,
      flag: "--fields_2",
    },
    {
      key: "action",
      label: "Merge action",
      helper:
        "Defines how values are merged when the destination field already exists.",
      type: "select",
      default: "None",
      options: ["None", "first", "last", "set", "cat"],
      flag: "--action",
    },
    {
      key: "failed",
      label: "Write unpaired sequences to fail files",
      helper:
        "If enabled, unpaired sequences are written to separate fail output files.",
      type: "boolean",
      default: false,
      flag: "--failed",
    },
  ],
};

const ASM_COLOR = {
  color: "oklch(0.6 0.16 160)",
  tint: "oklch(0.96 0.04 160)",
  border: "oklch(0.85 0.08 160)",
  text: "oklch(0.4 0.14 160)",
};

const RC_PARAM: ParamDef = {
  key: "rc",
  label: "Reverse-complement setting",
  helper: "Specifies which read should be reverse-complemented before assembly.",
  type: "select",
  default: "tail",
  options: ["tail", "head", "both"],
  flag: "--rc",
};

const HEAD_FIELDS: ParamDef = {
  key: "head_fields",
  label: "Fields copied from Read 1",
  helper: "Annotation fields copied from Read 1 into the assembled sequence.",
  type: "multiselect",
  default: [],
  options: FIELD_OPTIONS,
  flag: "--head_fields",
};

const TAIL_FIELDS: ParamDef = {
  key: "tail_fields",
  label: "Fields copied from Read 2",
  helper: "Annotation fields copied from Read 2 into the assembled sequence.",
  type: "multiselect",
  default: [],
  options: FIELD_OPTIONS,
  flag: "--tail_fields",
};

const ASSEMBLE_ALIGN: AnyDef = {
  key: "assemble-align",
  name: "AssembleSeq.align",
  cli: "AssembleSeq align",
  description:
    "Performs de novo assembly by identifying an overlap between paired-end reads.",
  ...ASM_COLOR,
  params: [
    { key: "alpha", label: "Overlap significance threshold", helper: "Statistical significance threshold used to evaluate overlap quality. Smaller values are more stringent.", type: "scientific", default: "1e-5", flag: "--alpha" },
    { key: "max_error", label: "Maximum overlap error rate", helper: "Maximum allowed error rate within the overlap region. Example: 0.1 means 10% mismatch allowed.", type: "number", default: 0.3, flag: "--max_error" },
    { key: "min_len", label: "Minimum overlap length", helper: "Minimum overlap length required between paired reads.", type: "number", default: 8, flag: "--min_len" },
    { key: "max_len", label: "Maximum overlap length", helper: "Maximum overlap length considered during assembly.", type: "number", default: 1000, flag: "--max_len" },
    { key: "scan_reverse", label: "Scan reverse orientation", helper: "If enabled, reverse-orientation overlaps are also evaluated.", type: "boolean", default: false, flag: "--scan_reverse" },
    RC_PARAM,
    HEAD_FIELDS,
    TAIL_FIELDS,
  ],
};

const ASSEMBLE_JOIN: AnyDef = {
  key: "assemble-join",
  name: "AssembleSeq.join",
  cli: "AssembleSeq join",
  description: "Joins paired reads directly without searching for an overlap.",
  ...ASM_COLOR,
  params: [
    { key: "gap", label: "Gap length", helper: "Number of N bases inserted between Read 1 and Read 2.", type: "number", default: 0, flag: "--gap" },
    RC_PARAM,
    HEAD_FIELDS,
    TAIL_FIELDS,
  ],
};

const ASSEMBLE_REFERENCE: AnyDef = {
  key: "assemble-reference",
  name: "AssembleSeq.reference",
  cli: "AssembleSeq reference",
  description: "Performs reference-guided assembly using a reference FASTA sequence.",
  ...ASM_COLOR,
  params: [
    { key: "ref_file", label: "Reference FASTA file", helper: "Reference FASTA file used during assembly.", type: "file", default: "", flag: "--ref_file", required: true },
    { key: "min_ident", label: "Minimum sequence identity", helper: "Minimum sequence identity required for alignment to the reference.", type: "number", default: 0.5, flag: "--min_ident" },
    { key: "evalue", label: "Maximum E-value", helper: "Maximum acceptable E-value during reference alignment. Smaller values are more stringent.", type: "scientific", default: "1e-5", flag: "--evalue" },
    { key: "max_hits", label: "Maximum reference hits", helper: "Maximum number of reference matches evaluated per sequence.", type: "number", default: 100, flag: "--max_hits" },
    { key: "fill", label: "Fill gaps using reference", helper: "If enabled, gaps between paired reads are filled using the reference sequence.", type: "boolean", default: false, flag: "--fill" },
    { key: "aligner", label: "Alignment tool", helper: "Alignment tool used for reference mapping.", type: "select", default: "blastn", options: ["usearch", "blastn"], flag: "--aligner" },
    RC_PARAM,
    HEAD_FIELDS,
    TAIL_FIELDS,
  ],
};

const ASSEMBLE_SEQUENTIAL: AnyDef = {
  key: "assemble-sequential",
  name: "AssembleSeq.sequential",
  cli: "AssembleSeq sequential",
  description:
    "Attempts overlap assembly first. If overlap assembly fails, reference-guided assembly is performed.",
  ...ASM_COLOR,
  params: [
    { key: "alpha", label: "Overlap significance threshold", helper: "Statistical significance threshold.", type: "scientific", default: "1e-5", flag: "--alpha" },
    { key: "max_error", label: "Maximum overlap error rate", helper: "Maximum allowed error rate within the overlap region.", type: "number", default: 0.3, flag: "--max_error" },
    { key: "min_len", label: "Minimum overlap length", helper: "Minimum overlap length required.", type: "number", default: 8, flag: "--min_len" },
    { key: "max_len", label: "Maximum overlap length", helper: "Maximum overlap length considered.", type: "number", default: 1000, flag: "--max_len" },
    { key: "scan_reverse", label: "Scan reverse orientation", helper: "Evaluate reverse-orientation overlaps.", type: "boolean", default: false, flag: "--scan_reverse" },
    { key: "min_ident", label: "Minimum sequence identity", helper: "Minimum identity for reference alignment.", type: "number", default: 0.5, flag: "--min_ident" },
    { key: "evalue", label: "Maximum E-value", helper: "Maximum acceptable E-value.", type: "scientific", default: "1e-5", flag: "--evalue" },
    { key: "max_hits", label: "Maximum reference hits", helper: "Maximum number of reference matches.", type: "number", default: 100, flag: "--max_hits" },
    { key: "fill", label: "Fill gaps using reference", helper: "Fill gaps with reference sequence.", type: "boolean", default: false, flag: "--fill" },
    { key: "aligner", label: "Alignment tool", helper: "Alignment tool used for reference mapping.", type: "select", default: "usearch", options: ["usearch", "blastn"], flag: "--aligner" },
    { key: "ref_file", label: "Reference FASTA file", helper: "Reference FASTA file used during fallback assembly.", type: "file", default: "", flag: "--ref_file", required: true },
    RC_PARAM,
    HEAD_FIELDS,
    TAIL_FIELDS,
  ],
};

const ASSEMBLE_MODES: Record<string, AnyDef> = {
  align: ASSEMBLE_ALIGN,
  join: ASSEMBLE_JOIN,
  reference: ASSEMBLE_REFERENCE,
  sequential: ASSEMBLE_SEQUENTIAL,
};

const PAIRED_MAP: Record<string, AnyDef> = {
  pairseq: PAIRSEQ_DEF,
  "assemble-align": ASSEMBLE_ALIGN,
  "assemble-join": ASSEMBLE_JOIN,
  "assemble-reference": ASSEMBLE_REFERENCE,
  "assemble-sequential": ASSEMBLE_SEQUENTIAL,
};

// ─────────────────────── Paired-end builder UI ───────────────────────────

type AssembleMode = "align" | "join" | "reference" | "sequential";
type PairedStep = {
  id: string;
  key: string;
  values: Record<string, ParamValue>;
};

type Tab = "read1" | "read2" | "paired" | "assembled";

function PairedEndBuilder() {
  const [file1, setFile1] = useState<FileEntry>(null);
  const [file2, setFile2] = useState<FileEntry>(null);
  const [tab, setTab] = useState<Tab>("read1");

  const [read1, setRead1] = useState<PipelineStep[]>([]);
  const [read2, setRead2] = useState<PipelineStep[]>([]);
  const [pairedSteps, setPairedSteps] = useState<PairedStep[]>([]);
  const [assembled, setAssembled] = useState<PipelineStep[]>([]);

  // Expanded card state per tab (component catalog)
  const [expandedFilter, setExpandedFilter] = useState<{
    tab: Tab;
    key: ComponentKey;
  } | null>(null);
  const [filterDraft, setFilterDraft] = useState<Record<string, ParamValue>>({});

  // Expanded card state for paired components
  const [expandedPaired, setExpandedPaired] = useState<string | null>(null);
  const [pairedDraft, setPairedDraft] = useState<Record<string, ParamValue>>({});
  const [assembleMode, setAssembleMode] = useState<AssembleMode>("align");

  const [validating, setValidating] = useState(false);
  const [validated, setValidated] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const hasAssemble = pairedSteps.some((s) => s.key.startsWith("assemble-"));
  const assembleStep = pairedSteps.find((s) => s.key.startsWith("assemble-"));

  const invalidate = () => setValidated(false);

  const handleUpload = (which: 1 | 2, f: File) => {
    const setter = which === 1 ? setFile1 : setFile2;
    setter({ name: f.name, state: "uploading" });
    invalidate();
    setTimeout(() => setter({ name: f.name, state: "uploaded" }), 700);
  };

  // ── FilterSeq actions per branch ──
  const toggleFilter = (forTab: Tab, key: ComponentKey) => {
    if (expandedFilter && expandedFilter.tab === forTab && expandedFilter.key === key) {
      setExpandedFilter(null);
      return;
    }
    setExpandedFilter({ tab: forTab, key });
    setFilterDraft(defaultValues(COMPONENT_MAP[key]));
  };

  const pairSeqCount = pairedSteps.filter((s) => s.key === "pairseq").length;
  const hasPairSeq = pairSeqCount > 0;

  const addFilter = (forTab: Tab, key: ComponentKey) => {
    const def = COMPONENT_MAP[key];
    if (validateValues(def, filterDraft)) return;
    const isReadBranch = forTab === "read1" || forTab === "read2";
    const checkpoint: number | undefined = isReadBranch ? pairSeqCount : undefined;
    const step: PipelineStep = {
      id: `${key}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      key,
      values: { ...filterDraft },
      checkpoint,
    };
    if (forTab === "read1") setRead1((p) => [...p, step]);
    else if (forTab === "read2") setRead2((p) => [...p, step]);
    else if (forTab === "assembled") setAssembled((p) => [...p, step]);
    setExpandedFilter(null);
    invalidate();
  };

  const removeStep = (forTab: Tab, id: string) => {
    const setter =
      forTab === "read1" ? setRead1 : forTab === "read2" ? setRead2 : setAssembled;
    setter((p) => p.filter((s) => s.id !== id));
    invalidate();
  };

  const moveStep = (forTab: Tab, id: string, dir: -1 | 1) => {
    const setter =
      forTab === "read1" ? setRead1 : forTab === "read2" ? setRead2 : setAssembled;
    setter((p) => {
      const idx = p.findIndex((s) => s.id === id);
      if (idx < 0) return p;
      const j = idx + dir;
      if (j < 0 || j >= p.length) return p;
      // Restrict swap to within the same checkpoint segment.
      if ((p[idx].checkpoint ?? 0) !== (p[j].checkpoint ?? 0)) return p;
      const next = [...p];
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  };

  // ── Paired actions ──
  const togglePaired = (key: string) => {
    if (expandedPaired === key) {
      setExpandedPaired(null);
      return;
    }
    setExpandedPaired(key);
    if (key === "pairseq") setPairedDraft(defaultValues(PAIRSEQ_DEF));
    else setPairedDraft(defaultValues(ASSEMBLE_MODES[assembleMode]));
  };

  const switchAssembleMode = (m: AssembleMode) => {
    setAssembleMode(m);
    setPairedDraft(defaultValues(ASSEMBLE_MODES[m]));
  };

  const addPaired = (key: "pairseq" | "assemble") => {
    if (key === "pairseq") {
      if (validateValues(PAIRSEQ_DEF, pairedDraft)) return;
      setPairedSteps((p) => [
        ...p,
        {
          id: `pairseq-${Date.now()}`,
          key: "pairseq",
          values: { ...pairedDraft },
        },
      ]);
    } else {
      const def = ASSEMBLE_MODES[assembleMode];
      if (validateValues(def, pairedDraft)) return;
      if (hasAssemble) return;
      setPairedSteps((p) => [
        ...p,
        {
          id: `assemble-${Date.now()}`,
          key: `assemble-${assembleMode}`,
          values: { ...pairedDraft },
        },
      ]);
    }
    setExpandedPaired(null);
    invalidate();
  };

  const removePaired = (id: string) => {
    const removed = pairedSteps.find((s) => s.id === id);
    const nextPaired = pairedSteps.filter((s) => s.id !== id);
    setPairedSteps(nextPaired);
    if (removed?.key.startsWith("assemble-")) {
      setAssembled([]);
    }
    // If the removed step was a PairSeq, shift any read1/read2 components that
    // were added AFTER it down by one checkpoint (the checkpoint they were
    // anchored to no longer exists).
    if (removed?.key === "pairseq") {
      const pairseqIds = pairedSteps
        .filter((s) => s.key === "pairseq")
        .map((s) => s.id);
      const removedIndex = pairseqIds.indexOf(removed.id); // 0-based
      const shift = (s: PipelineStep): PipelineStep => {
        const c = s.checkpoint ?? 0;
        if (c > removedIndex) return { ...s, checkpoint: c - 1 };
        return s;
      };
      setRead1((p) => p.map(shift));
      setRead2((p) => p.map(shift));
    }
    invalidate();
  };

  const handleValidate = () => {
    setValidating(true);
    setValidationError(null);
    setTimeout(() => {
      setValidating(false);
      if (file1?.state !== "uploaded") {
        setValidationError("Please upload the Read 1 FASTQ file.");
        return;
      }
      if (file2?.state !== "uploaded") {
        setValidationError("Please upload the Read 2 FASTQ file.");
        return;
      }
      const total =
        read1.length + read2.length + pairedSteps.length + assembled.length;
      if (total === 0) {
        setValidationError("Add at least one component to the workflow.");
        return;
      }
      const check = (def: AnyDef, vals: Record<string, ParamValue>) =>
        validateValues(def, vals);
      for (const s of read1) {
        const e = check(COMPONENT_MAP[s.key], s.values);
        if (e) {
          setValidationError(`Read 1 · ${COMPONENT_MAP[s.key].name}: ${e}`);
          return;
        }
      }
      for (const s of read2) {
        const e = check(COMPONENT_MAP[s.key], s.values);
        if (e) {
          setValidationError(`Read 2 · ${COMPONENT_MAP[s.key].name}: ${e}`);
          return;
        }
      }
      for (const s of pairedSteps) {
        const def = PAIRED_MAP[s.key];
        const e = check(def, s.values);
        if (e) {
          setValidationError(`${def.name}: ${e}`);
          return;
        }
      }
      for (const s of assembled) {
        const e = check(COMPONENT_MAP[s.key], s.values);
        if (e) {
          setValidationError(`Assembled · ${COMPONENT_MAP[s.key].name}: ${e}`);
          return;
        }
      }
      setValidated(true);
    }, 700);
  };

  return (
    <section className="mt-12">
      <SectionHeading
        eyebrow="Step 2"
        title="Configure paired-end preprocessing workflow"
        description="Upload Read 1 and Read 2 FASTQ files, configure components for each read, then define whether the reads should be paired, synchronized, or assembled."
      />

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <PairedFastqUpload
          which={1}
          file={file1}
          onUpload={(f) => handleUpload(1, f)}
        />
        <PairedFastqUpload
          which={2}
          file={file2}
          onUpload={(f) => handleUpload(2, f)}
        />
      </div>

      <div className="mt-6 flex flex-wrap gap-1 rounded-xl border border-border bg-card p-1 text-sm">
        <TabBtn active={tab === "read1"} onClick={() => setTab("read1")}>
          Read 1 components
        </TabBtn>
        <TabBtn active={tab === "read2"} onClick={() => setTab("read2")}>
          Read 2 components
        </TabBtn>
        <TabBtn active={tab === "paired"} onClick={() => setTab("paired")}>
          Paired-end components
        </TabBtn>
        {hasAssemble && (
          <TabBtn active={tab === "assembled"} onClick={() => setTab("assembled")}>
            Assembled sequence components
          </TabBtn>
        )}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_1.15fr]">
        {/* Left: catalog */}
        <div
          className="rounded-2xl border border-border bg-card p-5"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          {tab === "read1" && (
            <FilterCatalog
              title="Read 1 components"
              hint="Configure parameters, then add to the Read 1 pipeline."
              addLabel="Add to Read 1 pipeline"
              disabled={hasAssemble}
              disabledHint="Locked after AssembleSeq. Add new components to the assembled sequence branch."
              expandedKey={
                expandedFilter?.tab === "read1" ? expandedFilter.key : null
              }
              draft={filterDraft}
              onToggle={(k) => toggleFilter("read1", k)}
              onUpdate={(k, v) =>
                setFilterDraft((p) => ({ ...p, [k]: v }))
              }
              onAdd={(k) => addFilter("read1", k)}
            />
          )}
          {tab === "read2" && (
            <FilterCatalog
              title="Read 2 components"
              hint="Configure parameters, then add to the Read 2 pipeline."
              addLabel="Add to Read 2 pipeline"
              disabled={hasAssemble}
              disabledHint="Locked after AssembleSeq. Add new components to the assembled sequence branch."
              expandedKey={
                expandedFilter?.tab === "read2" ? expandedFilter.key : null
              }
              draft={filterDraft}
              onToggle={(k) => toggleFilter("read2", k)}
              onUpdate={(k, v) =>
                setFilterDraft((p) => ({ ...p, [k]: v }))
              }
              onAdd={(k) => addFilter("read2", k)}
            />
          )}
          {tab === "paired" && (
            <PairedCatalog
              expanded={expandedPaired}
              draft={pairedDraft}
              assembleMode={assembleMode}
              hasAssemble={hasAssemble}
              onToggle={togglePaired}
              onUpdate={(k, v) =>
                setPairedDraft((p) => ({ ...p, [k]: v }))
              }
              onSwitchMode={switchAssembleMode}
              onAdd={addPaired}
            />
          )}
          {tab === "assembled" && hasAssemble && (
            <FilterCatalog
              title="Assembled sequence components"
              hint="Add components to the assembled output branch."
              addLabel="Add to assembled sequence pipeline"
              expandedKey={
                expandedFilter?.tab === "assembled" ? expandedFilter.key : null
              }
              draft={filterDraft}
              onToggle={(k) => toggleFilter("assembled", k)}
              onUpdate={(k, v) =>
                setFilterDraft((p) => ({ ...p, [k]: v }))
              }
              onAdd={(k) => addFilter("assembled", k)}
            />
          )}
        </div>

        {/* Right: previews */}
        <div className="flex flex-col gap-5">
          <div
            className="rounded-2xl border border-border bg-card p-5"
            style={{ boxShadow: "var(--shadow-card)" }}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Pipeline preview
              </h3>
              <span className="text-xs text-muted-foreground">
                {read1.length + read2.length + pairedSteps.length + assembled.length}{" "}
                step
                {read1.length + read2.length + pairedSteps.length + assembled.length === 1
                  ? ""
                  : "s"}
              </span>
            </div>
            <div className="mt-4">
              <PairedBranchPreview
                read1={read1}
                read2={read2}
                pairedSteps={pairedSteps}
                assembled={assembled}
                onRemoveRead={(t, id) => removeStep(t, id)}
                onMoveRead={(t, id, d) => moveStep(t, id, d)}
                onRemovePaired={removePaired}
                onRemoveAssembled={(id) => removeStep("assembled", id)}
                onMoveAssembled={(id, d) => moveStep("assembled", id, d)}
              />
            </div>
          </div>

          <PairedCommandPreview
            read1={read1}
            read2={read2}
            pairedSteps={pairedSteps}
            assembled={assembled}
          />
        </div>
      </div>

      {/* Workflow preview */}
      <div className="mt-6">
        <Button
          variant="outline"
          onClick={() => setPreviewOpen((p) => !p)}
          className="gap-2"
          disabled={
            read1.length + read2.length + pairedSteps.length + assembled.length ===
            0
          }
        >
          <Workflow className="h-4 w-4" />
          {previewOpen ? "Hide workflow preview" : "Generate workflow preview"}
        </Button>

        {previewOpen && (
          <>
            <GeneratedWorkflowCard
              filename="custom-bulk-paired-end-workflow.png"
              title="Generated workflow · Paired-end"
            >
              {(showArgs) => (
                <PairedGeneratedDiagram
                  read1={read1}
                  read2={read2}
                  pairedSteps={pairedSteps}
                  assembled={assembled}
                  assembleStep={assembleStep ?? null}
                  showArgs={showArgs}
                />
              )}
            </GeneratedWorkflowCard>
            <RetentionFunnelPaired
              read1={read1}
              read2={read2}
              pairedSteps={pairedSteps}
              assembled={assembled}
            />
          </>
        )}
      </div>


      {/* Actions */}
      <section className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-3">
          <Button onClick={handleValidate} disabled={validating} className="gap-2">
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
                ? "Configuration valid"
                : "Validate configuration"}
          </Button>
          <Button variant="outline" disabled={!validated} className="gap-2">
            Continue
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
        {validationError && (
          <div className="inline-flex items-center gap-2 rounded-full bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive">
            <AlertCircle className="h-3.5 w-3.5" />
            {validationError}
          </div>
        )}
        {validated && !validationError && (
          <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Ready to run
          </div>
        )}
      </section>
    </section>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function PairedFastqUpload({
  which,
  file,
  onUpload,
}: {
  which: 1 | 2;
  file: FileEntry;
  onUpload: (f: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const state: UploadState = file?.state ?? "default";
  return (
    <div
      className={cn(
        "rounded-2xl border bg-card p-5 transition-colors",
        state === "uploaded"
          ? "border-primary/50 ring-1 ring-primary/20"
          : "border-border",
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
              <h4 className="text-sm font-semibold text-foreground">
                Read {which} FASTQ
              </h4>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Required
              </span>
              {state === "uploaded" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                  <CheckCircle2 className="h-3 w-3" /> Loaded
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Upload the FASTQ file for Read {which}.
            </p>
            {file?.name && (
              <p className="mt-1 truncate text-xs font-medium text-foreground">
                {file.name}
              </p>
            )}
          </div>
        </div>
        <div>
          <input
            ref={inputRef}
            type="file"
            accept=".fastq,.fq,.gz"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
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
        </div>
      </div>
    </div>
  );
}

function FilterCatalog({
  title,
  hint,
  addLabel,
  disabled,
  disabledHint,
  expandedKey,
  draft,
  onToggle,
  onUpdate,
  onAdd,
}: {
  title: string;
  hint: string;
  addLabel: string;
  disabled?: boolean;
  disabledHint?: string;
  expandedKey: ComponentKey | null;
  draft: Record<string, ParamValue>;
  onToggle: (k: ComponentKey) => void;
  onUpdate: (k: string, v: ParamValue) => void;
  onAdd: (k: ComponentKey) => void;
}) {
  return (
    <>
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      {disabled && (
        <p className="mt-2 rounded-md bg-amber-100/60 px-2.5 py-1.5 text-[11px] font-medium text-amber-900">
          {disabledHint}
        </p>
      )}
      <div className={cn("mt-4 grid gap-3", disabled && "pointer-events-none opacity-50")}>
        {COMPONENTS.map((c) => (
          <BranchedComponentCard
            key={c.key}
            def={c}
            expanded={expandedKey === c.key}
            values={expandedKey === c.key ? draft : null}
            addLabel={addLabel}
            onToggle={() => onToggle(c.key)}
            onUpdate={onUpdate}
            onAdd={() => onAdd(c.key)}
          />
        ))}
      </div>
    </>
  );
}

function BranchedComponentCard({
  def,
  expanded,
  values,
  addLabel,
  onToggle,
  onUpdate,
  onAdd,
}: {
  def: AnyDef;
  expanded: boolean;
  values: Record<string, ParamValue> | null;
  addLabel: string;
  onToggle: () => void;
  onUpdate: (key: string, value: ParamValue) => void;
  onAdd: () => void;
}) {
  const err = expanded && values ? validateValues(def, values) : null;
  return (
    <div
      className={cn(
        "rounded-xl border bg-background transition-colors",
        expanded ? "ring-1" : "hover:border-primary/40",
      )}
      style={{
        borderColor: expanded ? def.border : undefined,
        ...(expanded ? ({ "--tw-ring-color": def.border } as React.CSSProperties) : {}),
      }}
    >
      <div className="flex items-start justify-between gap-3 p-3.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: def.color }}
            />
            <h4 className="truncate text-sm font-semibold text-foreground">
              {def.name}
            </h4>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {def.description}
          </p>
        </div>
        <Button
          size="sm"
          variant={expanded ? "ghost" : "outline"}
          className="gap-1.5 shrink-0"
          onClick={onToggle}
        >
          {expanded ? (
            <>
              <X className="h-3.5 w-3.5" />
              Close
            </>
          ) : (
            <>
              <ChevronDown className="h-3.5 w-3.5" />
              Configure
            </>
          )}
        </Button>
      </div>
      {expanded && values && (
        <div
          className="border-t px-3.5 pb-3.5 pt-3"
          style={{ borderColor: def.border, background: def.tint }}
        >
          <ParameterForm def={def} values={values} onUpdate={onUpdate} />
          <div className="mt-4 flex items-center justify-between gap-3">
            {err ? (
              <span className="text-[11px] font-medium text-destructive">{err}</span>
            ) : (
              <span className="text-[11px] text-muted-foreground">
                Values stored when added.
              </span>
            )}
            <Button
              size="sm"
              className="gap-1.5"
              onClick={onAdd}
              disabled={Boolean(err)}
            >
              <Plus className="h-3.5 w-3.5" />
              {addLabel}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function PairedCatalog({
  expanded,
  draft,
  assembleMode,
  hasAssemble,
  onToggle,
  onUpdate,
  onSwitchMode,
  onAdd,
}: {
  expanded: string | null;
  draft: Record<string, ParamValue>;
  assembleMode: AssembleMode;
  hasAssemble: boolean;
  onToggle: (k: string) => void;
  onUpdate: (k: string, v: ParamValue) => void;
  onSwitchMode: (m: AssembleMode) => void;
  onAdd: (k: "pairseq" | "assemble") => void;
}) {
  const pairseqDef = PAIRSEQ_DEF;
  const assembleDef = ASSEMBLE_MODES[assembleMode];
  const pairseqExpanded = expanded === "pairseq";
  const assembleExpanded = expanded === "assemble";
  const pairseqErr = pairseqExpanded ? validateValues(pairseqDef, draft) : null;
  const assembleErr = assembleExpanded ? validateValues(assembleDef, draft) : null;

  return (
    <>
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Paired-end components
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Use PairSeq to synchronize the two branches, or AssembleSeq to merge them
        into a single sequence.
      </p>

      <div className="mt-4 grid gap-3">
        {/* PairSeq card */}
        <div
          className={cn(
            "rounded-xl border bg-background transition-colors",
            pairseqExpanded ? "ring-1" : "hover:border-primary/40",
          )}
          style={{
            borderColor: pairseqExpanded ? pairseqDef.border : undefined,
            ...(pairseqExpanded
              ? ({ "--tw-ring-color": pairseqDef.border } as React.CSSProperties)
              : {}),
          }}
        >
          <div className="flex items-start justify-between gap-3 p-3.5">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: pairseqDef.color }}
                />
                <h4 className="text-sm font-semibold text-foreground">PairSeq</h4>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {pairseqDef.description}
              </p>
            </div>
            <Button
              size="sm"
              variant={pairseqExpanded ? "ghost" : "outline"}
              className="gap-1.5 shrink-0"
              onClick={() => onToggle("pairseq")}
            >
              {pairseqExpanded ? (
                <>
                  <X className="h-3.5 w-3.5" />
                  Close
                </>
              ) : (
                <>
                  <ChevronDown className="h-3.5 w-3.5" />
                  Configure
                </>
              )}
            </Button>
          </div>
          {pairseqExpanded && (
            <div
              className="border-t px-3.5 pb-3.5 pt-3"
              style={{ borderColor: pairseqDef.border, background: pairseqDef.tint }}
            >
              <ParameterForm def={pairseqDef} values={draft} onUpdate={onUpdate} />
              <div className="mt-4 flex items-center justify-between gap-3">
                {pairseqErr ? (
                  <span className="text-[11px] font-medium text-destructive">
                    {pairseqErr}
                  </span>
                ) : (
                  <span className="text-[11px] text-muted-foreground">
                    Keeps Read 1 and Read 2 as separate branches.
                  </span>
                )}
                <Button
                  size="sm"
                  className="gap-1.5"
                  onClick={() => onAdd("pairseq")}
                  disabled={Boolean(pairseqErr)}
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add PairSeq to workflow
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* AssembleSeq card */}
        <div
          className={cn(
            "rounded-xl border bg-background transition-colors",
            assembleExpanded ? "ring-1" : "hover:border-primary/40",
            hasAssemble && "opacity-60",
          )}
          style={{
            borderColor: assembleExpanded ? assembleDef.border : undefined,
            ...(assembleExpanded
              ? ({ "--tw-ring-color": assembleDef.border } as React.CSSProperties)
              : {}),
          }}
        >
          <div className="flex items-start justify-between gap-3 p-3.5">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: assembleDef.color }}
                />
                <h4 className="text-sm font-semibold text-foreground">AssembleSeq</h4>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Assembles Read 1 and Read 2 into a single output sequence. After
                this step, the workflow becomes one assembled-sequence branch.
              </p>
            </div>
            <Button
              size="sm"
              variant={assembleExpanded ? "ghost" : "outline"}
              className="gap-1.5 shrink-0"
              onClick={() => onToggle("assemble")}
              disabled={hasAssemble}
            >
              {assembleExpanded ? (
                <>
                  <X className="h-3.5 w-3.5" />
                  Close
                </>
              ) : (
                <>
                  <ChevronDown className="h-3.5 w-3.5" />
                  Configure
                </>
              )}
            </Button>
          </div>
          {assembleExpanded && (
            <div
              className="border-t px-3.5 pb-3.5 pt-3"
              style={{ borderColor: assembleDef.border, background: assembleDef.tint }}
            >
              <div className="mb-3">
                <label className="text-xs font-medium text-foreground">
                  Assembly mode
                </label>
                <div className="mt-1.5 flex flex-wrap gap-1 rounded-lg border border-border bg-background p-1">
                  {(["align", "join", "reference", "sequential"] as AssembleMode[]).map(
                    (m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => onSwitchMode(m)}
                        className={cn(
                          "rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors",
                          assembleMode === m
                            ? "bg-primary text-primary-foreground"
                            : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        )}
                      >
                        {m}
                      </button>
                    ),
                  )}
                </div>
                <p className="mt-1.5 text-[11px] text-muted-foreground">
                  {assembleDef.description}
                </p>
              </div>
              <ParameterForm def={assembleDef} values={draft} onUpdate={onUpdate} />
              <div className="mt-4 flex items-center justify-between gap-3">
                {assembleErr ? (
                  <span className="text-[11px] font-medium text-destructive">
                    {assembleErr}
                  </span>
                ) : (
                  <span className="text-[11px] text-muted-foreground">
                    Merges both branches into one assembled sequence.
                  </span>
                )}
                <Button
                  size="sm"
                  className="gap-1.5"
                  onClick={() => onAdd("assemble")}
                  disabled={Boolean(assembleErr) || hasAssemble}
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add {assembleDef.name} to workflow
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function PairedBranchPreview({
  read1,
  read2,
  pairedSteps,
  assembled,
  onRemoveRead,
  onMoveRead,
  onRemovePaired,
  onRemoveAssembled,
  onMoveAssembled,
}: {
  read1: PipelineStep[];
  read2: PipelineStep[];
  pairedSteps: PairedStep[];
  assembled: PipelineStep[];
  onRemoveRead: (t: Tab, id: string) => void;
  onMoveRead: (t: Tab, id: string, d: -1 | 1) => void;
  onRemovePaired: (id: string) => void;
  onRemoveAssembled: (id: string) => void;
  onMoveAssembled: (id: string, d: -1 | 1) => void;
}) {
  const hasAnything =
    read1.length + read2.length + pairedSteps.length + assembled.length > 0;
  if (!hasAnything) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-8 text-center">
        <p className="text-sm text-muted-foreground">
          No components yet. Add filters to Read 1 or Read 2, or pair/assemble the
          branches.
        </p>
      </div>
    );
  }
  const assembleIdx = pairedSteps.findIndex((s) => s.key.startsWith("assemble-"));
  const beforeAssemble =
    assembleIdx < 0 ? pairedSteps : pairedSteps.slice(0, assembleIdx);
  const assembleStep = assembleIdx >= 0 ? pairedSteps[assembleIdx] : null;
  const pairSeqSteps = beforeAssemble.filter((s) => s.key === "pairseq");
  const N = pairSeqSteps.length;
  const r1Seg = (k: number) => read1.filter((s) => (s.checkpoint ?? 0) === k);
  const r2Seg = (k: number) => read2.filter((s) => (s.checkpoint ?? 0) === k);
  // Cumulative count for stable 1-based numbering across segments.
  const r1Offsets: number[] = [];
  const r2Offsets: number[] = [];
  {
    let a = 0;
    let b = 0;
    for (let k = 0; k <= N; k++) {
      r1Offsets.push(a);
      r2Offsets.push(b);
      a += r1Seg(k).length;
      b += r2Seg(k).length;
    }
  }

  const segments: React.ReactNode[] = [];
  for (let k = 0; k <= N; k++) {
    const isFirst = k === 0;
    const isAfter = k > 0;
    segments.push(
      <div key={`seg-${k}`} className="grid grid-cols-2 gap-3">
        <BranchColumn
          title={isFirst ? "Read 1" : `Read 1 (after PairSeq ${k})`}
          steps={r1Seg(k)}
          startIndex={r1Offsets[k]}
          onRemove={(id) => onRemoveRead("read1", id)}
          onMove={(id, d) => onMoveRead("read1", id, d)}
          emptyHint={
            isAfter ? `No Read 1 components after PairSeq ${k}` : undefined
          }
          headerTone={isAfter ? "post" : "default"}
        />
        <BranchColumn
          title={isFirst ? "Read 2" : `Read 2 (after PairSeq ${k})`}
          steps={r2Seg(k)}
          startIndex={r2Offsets[k]}
          onRemove={(id) => onRemoveRead("read2", id)}
          onMove={(id, d) => onMoveRead("read2", id, d)}
          emptyHint={
            isAfter ? `No Read 2 components after PairSeq ${k}` : undefined
          }
          headerTone={isAfter ? "post" : "default"}
        />
      </div>,
    );
    if (k < N) {
      const ps = pairSeqSteps[k];
      segments.push(
        <PairSeqMergeSplit
          key={ps.id}
          step={ps}
          index={k + 1}
          total={N}
          onRemove={() => onRemovePaired(ps.id)}
        />,
      );
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {segments}
      {/* Render any non-PairSeq pre-assemble bridges (defensive; currently only PairSeq supported here) */}
      {beforeAssemble
        .filter((s) => s.key !== "pairseq")
        .map((s) => (
          <PairedBridge key={s.id} step={s} onRemove={() => onRemovePaired(s.id)} />
        ))}
      {assembleStep && (
        <>
          <AssembleNode
            step={assembleStep}
            onRemove={() => onRemovePaired(assembleStep.id)}
          />
          <div className="flex flex-col items-stretch gap-2">
            <FlowBlock label="Assembled sequence" tone="io" />
            {assembled.map((step, idx) => {
              const def = COMPONENT_MAP[step.key];
              return (
                <div key={step.id} className="flex flex-col items-stretch gap-2">
                  <ArrowDown />
                  <div
                    className="rounded-xl border"
                    style={{
                      background: def.tint,
                      borderColor: def.border,
                      color: def.text,
                    }}
                  >
                    <div className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <span
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-bold text-white"
                          style={{ background: def.color }}
                        >
                          {idx + 1}
                        </span>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold">
                            {def.name}
                          </div>
                          <div className="truncate font-mono text-[11px] opacity-80">
                            {formatSummary(def, step.values)}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <IconBtn
                          label="Move up"
                          disabled={idx === 0}
                          onClick={() => onMoveAssembled(step.id, -1)}
                        >
                          <ChevronUp className="h-3.5 w-3.5" />
                        </IconBtn>
                        <IconBtn
                          label="Move down"
                          disabled={idx === assembled.length - 1}
                          onClick={() => onMoveAssembled(step.id, 1)}
                        >
                          <ChevronDown className="h-3.5 w-3.5" />
                        </IconBtn>
                        <IconBtn
                          label="Remove"
                          onClick={() => onRemoveAssembled(step.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </IconBtn>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
            <ArrowDown />
            <FlowBlock label="Output assembled FASTQ" tone="io" />
          </div>
        </>
      )}
    </div>
  );
}

function BranchColumn({
  title,
  steps,
  onRemove,
  onMove,
  startIndex = 0,
  emptyHint,
  headerTone = "default",
}: {
  title: string;
  steps: PipelineStep[];
  onRemove: (id: string) => void;
  onMove: (id: string, d: -1 | 1) => void;
  startIndex?: number;
  emptyHint?: string;
  headerTone?: "default" | "post";
}) {
  const headerLabel = startIndex > 0 || headerTone === "post" ? title : `${title} FASTQ`;
  return (
    <div className="flex flex-col items-stretch gap-2">
      <div
        className={cn(
          "rounded-xl border border-border px-3 py-2 text-center text-xs font-semibold uppercase tracking-wide text-foreground",
          headerTone === "post" ? "bg-background/70" : "bg-muted",
        )}
      >
        {headerLabel}
      </div>
      {steps.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-background/60 px-3 py-4 text-center text-[11px] text-muted-foreground">
          {emptyHint ?? `No ${title} components`}
        </div>
      ) : (
        steps.map((step, idx) => {
          const def = COMPONENT_MAP[step.key];
          return (
            <div key={step.id} className="flex flex-col items-stretch gap-1.5">
              <ArrowDown />
              <div
                className="rounded-lg border px-3 py-2"
                style={{
                  background: def.tint,
                  borderColor: def.border,
                  color: def.text,
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-xs font-semibold">
                      <span className="mr-1 opacity-60">{startIndex + idx + 1}.</span>
                      {def.name}
                    </div>
                    <div className="truncate font-mono text-[10px] opacity-80">
                      {formatSummary(def, step.values)}
                    </div>
                  </div>
                  <div className="flex items-center gap-0.5">
                    <IconBtn
                      label="Move up"
                      disabled={idx === 0}
                      onClick={() => onMove(step.id, -1)}
                    >
                      <ChevronUp className="h-3 w-3" />
                    </IconBtn>
                    <IconBtn
                      label="Move down"
                      disabled={idx === steps.length - 1}
                      onClick={() => onMove(step.id, 1)}
                    >
                      <ChevronDown className="h-3 w-3" />
                    </IconBtn>
                    <IconBtn label="Remove" onClick={() => onRemove(step.id)}>
                      <Trash2 className="h-3 w-3" />
                    </IconBtn>
                  </div>
                </div>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

function PairSeqMergeSplit({
  step,
  index,
  total,
  onRemove,
}: {
  step: PairedStep;
  index: number;
  total: number;
  onRemove: () => void;
}) {
  const def = PAIRED_MAP["pairseq"];
  return (
    <div className="relative rounded-2xl border-2 border-dashed px-4 py-4"
      style={{ borderColor: def.border, background: def.tint, color: def.text }}
    >
      {/* Converging lines (two inputs) */}
      <div className="grid grid-cols-2 gap-3 pb-3">
        <div className="flex justify-center">
          <div className="flex flex-col items-center">
            <span className="text-[10px] font-semibold uppercase tracking-wide opacity-70">From Read 1</span>
            <svg width="60" height="22" viewBox="0 0 60 22" className="mt-0.5">
              <path d="M10 0 L30 18" stroke={def.color} strokeWidth="1.5" fill="none" />
              <polygon points="30,22 26,14 34,14" fill={def.color} />
            </svg>
          </div>
        </div>
        <div className="flex justify-center">
          <div className="flex flex-col items-center">
            <span className="text-[10px] font-semibold uppercase tracking-wide opacity-70">From Read 2</span>
            <svg width="60" height="22" viewBox="0 0 60 22" className="mt-0.5">
              <path d="M50 0 L30 18" stroke={def.color} strokeWidth="1.5" fill="none" />
              <polygon points="30,22 26,14 34,14" fill={def.color} />
            </svg>
          </div>
        </div>
      </div>
      {/* PairSeq card */}
      <div
        className="rounded-xl border bg-white/70 px-4 py-3"
        style={{ borderColor: def.border }}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: def.color }}
              />
              <span className="text-sm font-semibold">{def.name}</span>
              {total > 1 && (
                <span className="rounded-full bg-white px-1.5 py-0.5 text-[10px] font-semibold opacity-70">
                  #{index}
                </span>
              )}
              <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide opacity-80">
                Synchronizes Read 1 ⇄ Read 2
              </span>
            </div>
            <div className="mt-1 truncate font-mono text-[11px] opacity-80">
              {formatSummary(def, step.values)}
            </div>
          </div>
          <IconBtn label="Remove" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </IconBtn>
        </div>
      </div>
      {/* Diverging lines (two outputs) */}
      <div className="grid grid-cols-2 gap-3 pt-3">
        <div className="flex justify-center">
          <div className="flex flex-col items-center">
            <svg width="60" height="22" viewBox="0 0 60 22">
              <path d="M30 0 L10 18" stroke={def.color} strokeWidth="1.5" fill="none" />
              <polygon points="10,22 6,14 14,14" fill={def.color} />
            </svg>
            <span className="text-[10px] font-semibold uppercase tracking-wide opacity-70">To Read 1</span>
          </div>
        </div>
        <div className="flex justify-center">
          <div className="flex flex-col items-center">
            <svg width="60" height="22" viewBox="0 0 60 22">
              <path d="M30 0 L50 18" stroke={def.color} strokeWidth="1.5" fill="none" />
              <polygon points="50,22 46,14 54,14" fill={def.color} />
            </svg>
            <span className="text-[10px] font-semibold uppercase tracking-wide opacity-70">To Read 2</span>
          </div>
        </div>
      </div>
      <p className="mt-2 text-center text-[10px] text-muted-foreground">
        PairSeq synchronizes the two reads but keeps them as separate branches.
      </p>
    </div>
  );
}

function PairedBridge({
  step,
  onRemove,
}: {
  step: PairedStep;
  onRemove: () => void;
}) {
  const def = PAIRED_MAP[step.key];
  return (
    <div className="flex flex-col items-center gap-2">
      <ArrowDown />
      <div
        className="w-full rounded-xl border-2 border-dashed px-4 py-3"
        style={{ borderColor: def.border, background: def.tint, color: def.text }}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: def.color }}
              />
              <span className="text-sm font-semibold">{def.name}</span>
              <span className="rounded-full bg-white/60 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
                Bridges Read 1 ⇄ Read 2
              </span>
            </div>
            <div className="mt-1 truncate font-mono text-[11px] opacity-80">
              {formatSummary(def, step.values)}
            </div>
          </div>
          <IconBtn label="Remove" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </IconBtn>
        </div>
      </div>
      <p className="text-[10px] text-muted-foreground">
        Branches remain separate after PairSeq.
      </p>
    </div>
  );
}

function AssembleNode({
  step,
  onRemove,
}: {
  step: PairedStep;
  onRemove: () => void;
}) {
  const def = PAIRED_MAP[step.key];
  return (
    <div className="flex flex-col items-center gap-2">
      <ArrowDown />
      <div
        className="w-full rounded-xl border-2 px-4 py-3"
        style={{ borderColor: def.border, background: def.tint, color: def.text }}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: def.color }}
              />
              <span className="text-sm font-semibold">{def.name}</span>
              <span className="rounded-full bg-white/60 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
                Merges Read 1 + Read 2
              </span>
            </div>
            <div className="mt-1 truncate font-mono text-[11px] opacity-80">
              {formatSummary(def, step.values)}
            </div>
          </div>
          <IconBtn label="Remove" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </IconBtn>
        </div>
      </div>
    </div>
  );
}

function PairedCommandPreview({
  read1,
  read2,
  pairedSteps,
  assembled,
}: {
  read1: PipelineStep[];
  read2: PipelineStep[];
  pairedSteps: PairedStep[];
  assembled: PipelineStep[];
}) {
  const lines: string[] = [];
  const assembleIdx = pairedSteps.findIndex((s) => s.key.startsWith("assemble-"));
  const beforeAssemble =
    assembleIdx < 0 ? pairedSteps : pairedSteps.slice(0, assembleIdx);
  const assembleStep = assembleIdx >= 0 ? pairedSteps[assembleIdx] : null;
  const pairSeqSteps = beforeAssemble.filter((s) => s.key === "pairseq");
  const N = pairSeqSteps.length;

  const pushBranch = (label: string, items: PipelineStep[]) => {
    if (!items.length) return;
    lines.push(`# ${label}`);
    items.forEach((s) => lines.push(buildCommand(COMPONENT_MAP[s.key], s.values)));
    lines.push("");
  };

  for (let k = 0; k <= N; k++) {
    const suffix = k === 0 ? "" : ` (after PairSeq ${k})`;
    pushBranch(`Read 1 branch${suffix}`, read1.filter((s) => (s.checkpoint ?? 0) === k));
    pushBranch(`Read 2 branch${suffix}`, read2.filter((s) => (s.checkpoint ?? 0) === k));
    if (k < N) {
      const ps = pairSeqSteps[k];
      const def = PAIRED_MAP[ps.key];
      lines.push(`# ${def.name}${N > 1 ? ` #${k + 1}` : ""}`);
      lines.push(buildCommand(def, ps.values));
      lines.push("");
    }
  }
  // Defensive: any non-PairSeq bridges between branches.
  beforeAssemble
    .filter((s) => s.key !== "pairseq")
    .forEach((s) => {
      const def = PAIRED_MAP[s.key];
      lines.push(`# ${def.name}`);
      lines.push(buildCommand(def, s.values));
      lines.push("");
    });
  if (assembleStep) {
    const def = PAIRED_MAP[assembleStep.key];
    lines.push(`# ${def.name}`);
    lines.push(buildCommand(def, assembleStep.values));
    lines.push("");
  }
  if (assembled.length) {
    lines.push("# Assembled branch");
    assembled.forEach((s) =>
      lines.push(buildCommand(COMPONENT_MAP[s.key], s.values)),
    );
  }
  const text = lines.join("\n").trim();
  return (
    <div
      className="rounded-2xl border border-border bg-card p-5"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Command preview
      </h3>
      {!text ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Add configured components to see the generated commands.
        </p>
      ) : (
        <pre className="mt-3 overflow-x-auto rounded-lg bg-muted px-3 py-2.5 font-mono text-xs leading-relaxed text-foreground whitespace-pre-wrap">
          {text}
        </pre>
      )}
    </div>
  );
}

function PairedWorkflowDiagram({
  read1,
  read2,
  pairedSteps,
  assembled,
  assembleStep,
}: {
  read1: PipelineStep[];
  read2: PipelineStep[];
  pairedSteps: PairedStep[];
  assembled: PipelineStep[];
  assembleStep: PairedStep | null;
}) {
  const beforeAssemble = assembleStep
    ? pairedSteps.slice(0, pairedSteps.indexOf(assembleStep))
    : pairedSteps;
  const pairSeqSteps = beforeAssemble.filter((s) => s.key === "pairseq");
  const N = pairSeqSteps.length;
  const r1Seg = (k: number) => read1.filter((s) => (s.checkpoint ?? 0) === k);
  const r2Seg = (k: number) => read2.filter((s) => (s.checkpoint ?? 0) === k);

  const renderColumn = (
    label: string,
    items: PipelineStep[],
    showHeader: boolean,
    placeholderLabel?: string,
  ) => (
    <div className="flex flex-col items-stretch gap-2">
      {showHeader && <FlowBlock label={label} tone="io" />}
      {items.length === 0 && placeholderLabel ? (
        <>
          {showHeader && <ArrowDown />}
          <FlowBlock label={placeholderLabel} tone="io" />
        </>
      ) : (
        items.map((s, i) => {
          const def = COMPONENT_MAP[s.key];
          return (
            <div key={s.id} className="flex flex-col items-stretch gap-2">
              {showHeader || i > 0 ? <ArrowDown /> : null}
              <FlowBlock
                label={def.name}
                sublabel={formatSummary(def, s.values)}
                color={def.color}
                tint={def.tint}
                border={def.border}
                text={def.text}
              />
            </div>
          );
        })
      )}
    </div>
  );

  const sections: React.ReactNode[] = [];
  for (let k = 0; k <= N; k++) {
    const isFirst = k === 0;
    const r1Label = isFirst ? "Read 1 FASTQ" : `Read 1 (after PairSeq ${k})`;
    const r2Label = isFirst ? "Read 2 FASTQ" : `Read 2 (after PairSeq ${k})`;
    const r1Items = r1Seg(k);
    const r2Items = r2Seg(k);
    const lastSeg = k === N;
    const placeholder1 =
      !isFirst && lastSeg && !assembleStep && r1Items.length === 0
        ? "Read 1 continues"
        : undefined;
    const placeholder2 =
      !isFirst && lastSeg && !assembleStep && r2Items.length === 0
        ? "Read 2 continues"
        : undefined;
    sections.push(
      <div key={`seg-${k}`} className="grid grid-cols-2 gap-4">
        {renderColumn(r1Label, r1Items, true, placeholder1)}
        {renderColumn(r2Label, r2Items, true, placeholder2)}
      </div>,
    );
    if (k < N) {
      const ps = pairSeqSteps[k];
      sections.push(
        <PairSeqMergeSplit
          key={ps.id}
          step={ps}
          index={k + 1}
          total={N}
          onRemove={() => {}}
        />,
      );
    }
  }

  return (
    <div className="flex flex-col items-stretch gap-3">
      {sections}
      {/* Non-PairSeq bridges (defensive) */}
      {beforeAssemble
        .filter((s) => s.key !== "pairseq")
        .map((s) => {
          const def = PAIRED_MAP[s.key];
          return (
            <div key={s.id} className="flex flex-col items-center gap-2">
              <ArrowDown />
              <div
                className="w-full rounded-xl border-2 border-dashed px-4 py-2.5 text-center text-sm font-semibold"
                style={{ background: def.tint, borderColor: def.border, color: def.text }}
              >
                {def.name} · bridges Read 1 ⇄ Read 2
              </div>
            </div>
          );
        })}
      {assembleStep && (
        <>
          <ArrowDown />
          <FlowBlock
            label={PAIRED_MAP[assembleStep.key].name}
            sublabel={formatSummary(
              PAIRED_MAP[assembleStep.key],
              assembleStep.values,
            )}
            color={PAIRED_MAP[assembleStep.key].color}
            tint={PAIRED_MAP[assembleStep.key].tint}
            border={PAIRED_MAP[assembleStep.key].border}
            text={PAIRED_MAP[assembleStep.key].text}
          />
          <ArrowDown />
          <FlowBlock label="Assembled sequence" tone="io" />
          {assembled.map((s) => {
            const def = COMPONENT_MAP[s.key];
            return (
              <div key={s.id} className="flex flex-col items-center gap-2">
                <ArrowDown />
                <FlowBlock
                  label={def.name}
                  sublabel={formatSummary(def, s.values)}
                  color={def.color}
                  tint={def.tint}
                  border={def.border}
                  text={def.text}
                />
              </div>
            );
          })}
          <ArrowDown />
          <FlowBlock label="Output assembled FASTQ" tone="io" />
        </>
      )}
    </div>
  );
}

// ───────────────────── Generated Workflow (presentation) ─────────────────────

/**
 * The workflow figure, with a switch between the clean diagram and the same
 * diagram annotated with every step's arguments.
 *
 * Both are worth having and neither replaces the other: the plain one is what
 * goes in a paper or a slide, the annotated one is the record of exactly what
 * was configured. The PNG export captures whichever is on screen and names the
 * file accordingly, so both can be saved.
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

  const modes: { value: boolean; label: string; title: string }[] = [
    {
      value: false,
      label: "No arguments",
      title: "Step names only -- the version to put in a figure",
    },
    {
      value: true,
      label: "Show arguments",
      title: "Every step with the parameters it is configured with",
    },
  ];

  return (
    <div
      className="mt-4 rounded-2xl border border-border bg-card p-6"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Generated workflow
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <div
            role="group"
            aria-label="Diagram detail"
            className="inline-flex rounded-lg border border-border p-0.5"
          >
            {modes.map((m) => (
              <button
                key={String(m.value)}
                type="button"
                onClick={() => setShowArgs(m.value)}
                title={m.title}
                aria-pressed={showArgs === m.value}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  showArgs === m.value
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={handleDownload}
            disabled={downloading}
            className="gap-2"
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

      <div className="overflow-x-auto rounded-xl border border-border/60 bg-[oklch(0.99_0.005_220)] p-6">
        <div ref={ref} className="mx-auto inline-block bg-white p-8">
          <div className="mb-5 text-center">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[oklch(0.55_0.13_230)]">
              pRESTO workflow
            </div>
            <div className="mt-0.5 text-base font-semibold text-foreground">
              {title}
            </div>
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

function DiagramArrow({ height = 28 }: { height?: number }) {
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
      style={{
        borderColor: "oklch(0.55 0.04 250)",
        background: "oklch(0.97 0.01 250)",
      }}
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-[oklch(0.4 0.06 250)]">
        {label}
      </div>
      {sublabel && (
        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
          {sublabel}
        </div>
      )}
    </div>
  );
}

/**
 * One step's arguments, one per line, for the annotated diagram.
 *
 * Wrapped rather than truncated: the annotated view exists precisely so the
 * values can be read, and a multiselect of copy fields is often long.
 */
function argLines(def: AnyDef, values: Record<string, ParamValue>): string[] {
  return def.params.map((param) => {
    const v = values[param.key];
    if (param.type === "boolean") return `${param.key} = ${v ? "yes" : "no"}`;
    if (param.type === "multiselect") {
      const arr = Array.isArray(v) ? v : [];
      return `${param.key} = ${arr.length ? arr.join(", ") : "none"}`;
    }
    return `${param.key} = ${v === "" || v == null ? "default" : String(v)}`;
  });
}

function DiagramStep({
  name,
  summary,
  args,
  color,
  tint,
  border,
  text,
  width = 260,
}: {
  name: string;
  summary?: string;
  /** Argument lines shown under the name in "Show arguments" mode. */
  args?: string[];
  color: string;
  tint: string;
  border: string;
  text: string;
  width?: number;
}) {
  return (
    <div
      className="mx-auto rounded-xl border-2 px-4 py-3 text-center shadow-sm"
      style={{
        width,
        background: tint,
        borderColor: border,
        color: text,
      }}
    >
      <div className="flex items-center justify-center gap-2">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: color }}
        />
        <span className="text-sm font-semibold">{name}</span>
      </div>
      {summary && (
        <div className="mt-1 truncate font-mono text-[10px] opacity-80">
          {summary}
        </div>
      )}
      {args && args.length > 0 && (
        <div className="mt-1.5 border-t border-current/20 pt-1.5 text-left">
          {args.map((line) => (
            <div
              key={line}
              className="break-words font-mono text-[9px] leading-snug opacity-85"
            >
              {line}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SingleGeneratedDiagram({
  pipeline,
  showArgs,
}: {
  pipeline: PipelineStep[];
  showArgs?: boolean;
}) {
  // Annotated nodes carry several lines; give them room rather than letting
  // each argument wrap to one word per line.
  const nodeWidth = showArgs ? 320 : 260;
  return (
    <div className="flex flex-col gap-0">
      <DiagramIO label="Input FASTQ" />
      {pipeline.map((step) => {
        const def = COMPONENT_MAP[step.key];
        return (
          <div key={step.id}>
            <DiagramArrow />
            <DiagramStep
              name={def.name}
              args={showArgs ? argLines(def, step.values) : undefined}
              width={nodeWidth}
              color={def.color}
              tint={def.tint}
              border={def.border}
              text={def.text}
            />
          </div>
        );
      })}
      <DiagramArrow />
      <DiagramIO label="Final repertoire" sublabel="Processed FASTQ" />
    </div>
  );
}

// ── Paired-end presentation diagram ─────────────────────────────────────────

const BRANCH_WIDTH = 230;
const BRANCH_GAP = 56;
const TOTAL_WIDTH = BRANCH_WIDTH * 2 + BRANCH_GAP;

function GenBranchColumn({
  steps,
  emptyLabel,
  showArgs,
}: {
  steps: PipelineStep[];
  emptyLabel?: string;
  showArgs?: boolean;
}) {
  return (
    <div
      className="flex flex-col gap-0"
      style={{ width: BRANCH_WIDTH }}
    >
      {steps.length === 0 && emptyLabel ? (
        <div
          className="mx-auto w-full rounded-lg border border-dashed border-border px-3 py-2 text-center text-[10px] font-medium italic text-muted-foreground"
        >
          {emptyLabel}
        </div>
      ) : (
        steps.map((s, i) => {
          const def = COMPONENT_MAP[s.key];
          return (
            <div key={s.id}>
              {i > 0 && <DiagramArrow height={22} />}
              <DiagramStep
                name={def.name}
                args={showArgs ? argLines(def, s.values) : undefined}
                color={def.color}
                tint={def.tint}
                border={def.border}
                text={def.text}
                width={BRANCH_WIDTH}
              />
            </div>
          );
        })
      )}
    </div>
  );
}

function PairSeqBand({
  step,
  index,
  total,
  showArgs,
}: {
  step: PairedStep;
  index: number;
  total: number;
  showArgs?: boolean;
}) {
  const def = PAIRED_MAP["pairseq"];
  const w = TOTAL_WIDTH;
  // SVG: top — two arrows converge to center; bottom — two arrows diverge.
  return (
    <div className="mx-auto" style={{ width: w }}>
      {/* Converge */}
      <svg width={w} height="34" viewBox={`0 0 ${w} 34`} className="block">
        <path
          d={`M ${BRANCH_WIDTH / 2} 0 Q ${BRANCH_WIDTH / 2} 24 ${w / 2} 28`}
          stroke={def.color}
          strokeWidth="1.5"
          fill="none"
        />
        <path
          d={`M ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2} 0 Q ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2} 24 ${w / 2} 28`}
          stroke={def.color}
          strokeWidth="1.5"
          fill="none"
        />
        <polygon
          points={`${w / 2},34 ${w / 2 - 5},26 ${w / 2 + 5},26`}
          fill={def.color}
        />
      </svg>
      {/* PairSeq card */}
      <div
        className="mx-auto rounded-xl border-2 px-4 py-2.5 text-center shadow-sm"
        style={{
          width: BRANCH_WIDTH + 40,
          background: def.tint,
          borderColor: def.border,
          color: def.text,
        }}
      >
        <div className="flex items-center justify-center gap-2">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: def.color }}
          />
          <span className="text-sm font-semibold">{def.name}</span>
          {total > 1 && (
            <span className="rounded-full bg-white/70 px-1.5 py-0.5 text-[9px] font-semibold">
              #{index}
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[9px] font-semibold uppercase tracking-wider opacity-75">
          Synchronizes Read 1 ⇄ Read 2
        </div>
      </div>
      {/* Diverge */}
      <svg width={w} height="34" viewBox={`0 0 ${w} 34`} className="block">
        <path
          d={`M ${w / 2} 0 Q ${BRANCH_WIDTH / 2} 14 ${BRANCH_WIDTH / 2} 28`}
          stroke={def.color}
          strokeWidth="1.5"
          fill="none"
        />
        <path
          d={`M ${w / 2} 0 Q ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2} 14 ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2} 28`}
          stroke={def.color}
          strokeWidth="1.5"
          fill="none"
        />
        <polygon
          points={`${BRANCH_WIDTH / 2},34 ${BRANCH_WIDTH / 2 - 5},26 ${BRANCH_WIDTH / 2 + 5},26`}
          fill={def.color}
        />
        <polygon
          points={`${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2},34 ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2 - 5},26 ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2 + 5},26`}
          fill={def.color}
        />
      </svg>
    </div>
  );
}

function AssembleMerge({
  step,
  showArgs,
}: {
  step: PairedStep;
  showArgs?: boolean;
}) {
  const def = PAIRED_MAP[step.key];
  const w = TOTAL_WIDTH;
  return (
    <div className="mx-auto" style={{ width: w }}>
      <svg width={w} height="40" viewBox={`0 0 ${w} 40`} className="block">
        <path
          d={`M ${BRANCH_WIDTH / 2} 0 Q ${BRANCH_WIDTH / 2} 28 ${w / 2} 34`}
          stroke={def.color}
          strokeWidth="1.5"
          fill="none"
        />
        <path
          d={`M ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2} 0 Q ${BRANCH_WIDTH + BRANCH_GAP + BRANCH_WIDTH / 2} 28 ${w / 2} 34`}
          stroke={def.color}
          strokeWidth="1.5"
          fill="none"
        />
        <polygon
          points={`${w / 2},40 ${w / 2 - 5},32 ${w / 2 + 5},32`}
          fill={def.color}
        />
      </svg>
      <DiagramStep
        name={def.name}
        args={showArgs ? argLines(def, step.values) : undefined}
        color={def.color}
        tint={def.tint}
        border={def.border}
        text={def.text}
        width={BRANCH_WIDTH + 40}
      />
    </div>
  );
}

function PairedGeneratedDiagram({
  read1,
  read2,
  pairedSteps,
  assembled,
  assembleStep,
  showArgs,
}: {
  read1: PipelineStep[];
  read2: PipelineStep[];
  pairedSteps: PairedStep[];
  assembled: PipelineStep[];
  assembleStep: PairedStep | null;
  showArgs?: boolean;
}) {
  const beforeAssemble = assembleStep
    ? pairedSteps.slice(0, pairedSteps.indexOf(assembleStep))
    : pairedSteps;
  const pairSeqSteps = beforeAssemble.filter((s) => s.key === "pairseq");
  const N = pairSeqSteps.length;
  const r1Seg = (k: number) => read1.filter((s) => (s.checkpoint ?? 0) === k);
  const r2Seg = (k: number) => read2.filter((s) => (s.checkpoint ?? 0) === k);

  const sections: React.ReactNode[] = [];

  for (let k = 0; k <= N; k++) {
    const isFirst = k === 0;
    const r1Items = r1Seg(k);
    const r2Items = r2Seg(k);
    const r1Label = isFirst ? "Read 1 FASTQ" : `Read 1 (cont.)`;
    const r2Label = isFirst ? "Read 2 FASTQ" : `Read 2 (cont.)`;

    sections.push(
      <div
        key={`hdr-${k}`}
        className="mx-auto grid"
        style={{
          width: TOTAL_WIDTH,
          gridTemplateColumns: `${BRANCH_WIDTH}px ${BRANCH_GAP}px ${BRANCH_WIDTH}px`,
        }}
      >
        <DiagramIO label={r1Label} sublabel={isFirst ? "FASTQ" : undefined} />
        <div />
        <DiagramIO label={r2Label} sublabel={isFirst ? "FASTQ" : undefined} />
      </div>,
    );

    if (r1Items.length > 0 || r2Items.length > 0) {
      sections.push(
        <div
          key={`arrows-${k}`}
          className="mx-auto grid"
          style={{
            width: TOTAL_WIDTH,
            gridTemplateColumns: `${BRANCH_WIDTH}px ${BRANCH_GAP}px ${BRANCH_WIDTH}px`,
          }}
        >
          <DiagramArrow height={22} />
          <div />
          <DiagramArrow height={22} />
        </div>,
      );
      sections.push(
        <div
          key={`cols-${k}`}
          className="mx-auto grid"
          style={{
            width: TOTAL_WIDTH,
            gridTemplateColumns: `${BRANCH_WIDTH}px ${BRANCH_GAP}px ${BRANCH_WIDTH}px`,
          }}
        >
          <GenBranchColumn steps={r1Items} emptyLabel="(no steps)" showArgs={showArgs} />
          <div />
          <GenBranchColumn steps={r2Items} emptyLabel="(no steps)" showArgs={showArgs} />
        </div>,
      );
    }

    if (k < N) {
      const ps = pairSeqSteps[k];
      sections.push(
        <PairSeqBand
          key={ps.id}
          step={ps}
          index={k + 1}
          total={N}
          showArgs={showArgs}
        />,
      );
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {sections}

      {assembleStep ? (
        <>
          <AssembleMerge step={assembleStep} showArgs={showArgs} />
          {assembled.length > 0 && (
            <div className="mx-auto" style={{ width: BRANCH_WIDTH + 40 }}>
              {assembled.map((s) => {
                const def = COMPONENT_MAP[s.key];
                return (
                  <div key={s.id}>
                    <DiagramArrow height={22} />
                    <DiagramStep
                      name={def.name}
                      args={showArgs ? argLines(def, s.values) : undefined}
                      color={def.color}
                      tint={def.tint}
                      border={def.border}
                      text={def.text}
                      width={BRANCH_WIDTH + 40}
                    />
                  </div>
                );
              })}
            </div>
          )}
          <div className="mx-auto" style={{ width: BRANCH_WIDTH + 40 }}>
            <DiagramArrow />
            <DiagramIO
              label="Final repertoire"
              sublabel="Assembled FASTQ"
            />
          </div>
        </>
      ) : (
        <>
          <div
            className="mx-auto grid"
            style={{
              width: TOTAL_WIDTH,
              gridTemplateColumns: `${BRANCH_WIDTH}px ${BRANCH_GAP}px ${BRANCH_WIDTH}px`,
            }}
          >
            <DiagramArrow />
            <div />
            <DiagramArrow />
          </div>
          <div
            className="mx-auto grid"
            style={{
              width: TOTAL_WIDTH,
              gridTemplateColumns: `${BRANCH_WIDTH}px ${BRANCH_GAP}px ${BRANCH_WIDTH}px`,
            }}
          >
            <DiagramIO label="Read 1 output" sublabel="Processed FASTQ" />
            <div />
            <DiagramIO label="Read 2 output" sublabel="Processed FASTQ" />
          </div>
        </>
      )}
    </div>
  );
}

// ───────────────────── Read-retention funnel (preview) ─────────────────────

// Estimated per-step retention rates used when no real run data is available.
// Clearly labeled as a preview in the UI. Values are intentionally conservative.
const RETENTION_RATE: Record<string, number> = {
  length: 0.92,
  quality: 0.94,
  missing: 0.97,
  repeats: 0.98,
  trimqual: 0.96,
  maskqual: 1.0,
  pairseq: 0.95,
  "assemble-align": 0.85,
  "assemble-join": 0.88,
  "assemble-reference": 0.82,
  "assemble-sequential": 0.86,
};

const INITIAL_READS = 1_000_000;

const fmtInt = (n: number) => Math.round(n).toLocaleString();
const fmtPct = (n: number) => `${(n * 100).toFixed(1)}%`;

type DefLite = {
  key: string;
  name: string;
  color: string;
  tint: string;
  border: string;
  text: string;
};

const getDefLite = (key: string): DefLite => {
  if (key in COMPONENT_MAP) return COMPONENT_MAP[key as ComponentKey];
  if (key === "pairseq") return PAIRSEQ_DEF as unknown as DefLite;
  if (key in PAIRED_MAP)
    return PAIRED_MAP[key as keyof typeof PAIRED_MAP] as unknown as DefLite;
  return {
    key,
    name: key,
    color: "oklch(0.6 0.05 240)",
    tint: "oklch(0.96 0.02 240)",
    border: "oklch(0.85 0.04 240)",
    text: "oklch(0.4 0.05 240)",
  };
};

type FunnelRow = {
  id: string;
  label: string;
  def: DefLite;
  input: number;
  output: number;
  removed: number;
  stepRetention: number;
  cumulativeRetention: number;
};

const buildFunnel = (
  steps: { id: string; key: string }[],
  initial: number,
): FunnelRow[] => {
  let current = initial;
  return steps.map((s) => {
    const def = getDefLite(s.key);
    const rate = RETENTION_RATE[s.key] ?? 1;
    const input = current;
    const output = input * rate;
    const removed = input - output;
    current = output;
    return {
      id: s.id,
      label: def.name,
      def,
      input,
      output,
      removed,
      stepRetention: rate,
      cumulativeRetention: output / initial,
    };
  });
};

function ExportCard({
  title,
  subtitle,
  filename,
  children,
}: {
  title: string;
  subtitle?: string;
  filename: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);
  const handleDownload = async () => {
    if (!ref.current) return;
    setDownloading(true);
    try {
      const dataUrl = await toPng(ref.current, {
        pixelRatio: 2.5,
        backgroundColor: "#ffffff",
        cacheBust: true,
      });
      const a = document.createElement("a");
      a.download = filename;
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
      className="mt-4 rounded-2xl border border-border bg-card p-6"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {title}
          </h3>
          {subtitle && (
            <p className="mt-1 text-xs text-muted-foreground/80">{subtitle}</p>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={handleDownload}
          disabled={downloading}
          className="gap-2"
        >
          {downloading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          Download PNG
        </Button>
      </div>
      <div ref={ref} className="rounded-xl bg-white p-6">
        {children}
      </div>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="flex-1 min-w-[140px] rounded-lg border border-border/70 bg-muted/30 px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className="mt-1 text-lg font-semibold tabular-nums"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
    </div>
  );
}

function FunnelBar({
  row,
  initial,
  maxWidthPct,
}: {
  row: FunnelRow;
  initial: number;
  maxWidthPct?: number;
}) {
  const cap = maxWidthPct ?? 100;
  const widthPct = Math.max(8, (row.output / initial) * cap);
  return (
    <div className="flex flex-col items-center">
      <div className="relative w-full" style={{ height: 56 }}>
        <div
          className="absolute left-1/2 top-0 -translate-x-1/2 rounded-lg shadow-sm transition-all"
          style={{
            width: `${widthPct}%`,
            height: "100%",
            background: `linear-gradient(180deg, ${row.def.tint} 0%, ${row.def.color} 100%)`,
            border: `1px solid ${row.def.border}`,
          }}
        >
          <div className="flex h-full items-center justify-between px-3 text-[11px] font-medium text-white drop-shadow-sm">
            <span className="truncate">{row.label}</span>
            <span className="tabular-nums">{fmtPct(row.cumulativeRetention)}</span>
          </div>
        </div>
      </div>
      <div className="mt-1.5 grid w-full grid-cols-3 gap-2 px-1 text-[10px] text-muted-foreground">
        <div>
          <div className="font-semibold text-foreground/80 tabular-nums">
            {fmtInt(row.output)}
          </div>
          <div>remaining</div>
        </div>
        <div className="text-center">
          <div className="font-semibold text-rose-600/80 tabular-nums">
            −{fmtInt(row.removed)}
          </div>
          <div>removed</div>
        </div>
        <div className="text-right">
          <div className="font-semibold text-foreground/80 tabular-nums">
            {fmtPct(row.stepRetention)}
          </div>
          <div>step</div>
        </div>
      </div>
    </div>
  );
}

function InputBar({
  label,
  count,
  color = "oklch(0.55 0.04 240)",
}: {
  label: string;
  count: number;
  color?: string;
}) {
  return (
    <div className="flex flex-col items-center">
      <div
        className="flex h-12 w-full items-center justify-between rounded-lg border px-3 text-[11px] font-semibold text-white shadow-sm"
        style={{
          background: `linear-gradient(180deg, ${color} 0%, oklch(0.4 0.05 240) 100%)`,
          borderColor: color,
        }}
      >
        <span>{label}</span>
        <span className="tabular-nums">100.0%</span>
      </div>
      <div className="mt-1.5 text-[10px] text-muted-foreground">
        <span className="font-semibold tabular-nums text-foreground/80">
          {fmtInt(count)}
        </span>{" "}
        reads
      </div>
    </div>
  );
}

function OutputBar({
  label,
  count,
  initial,
}: {
  label: string;
  count: number;
  initial: number;
}) {
  const pct = count / initial;
  const widthPct = Math.max(8, pct * 100);
  return (
    <div className="flex flex-col items-center">
      <div
        className="flex h-12 min-w-0 items-center justify-between rounded-lg border border-emerald-600/60 bg-gradient-to-b from-emerald-100 to-emerald-500 px-3 text-[11px] font-semibold text-white shadow-sm"
        style={{ width: `${widthPct}%` }}
      >
        <span>{label}</span>
        <span className="tabular-nums">{fmtPct(pct)}</span>
      </div>
      <div className="mt-1.5 text-[10px] text-muted-foreground">
        <span className="font-semibold tabular-nums text-foreground/80">
          {fmtInt(count)}
        </span>{" "}
        reads retained
      </div>
    </div>
  );
}

function FunnelArrow() {
  return (
    <div className="flex justify-center py-1">
      <div className="h-3 w-px bg-border" />
    </div>
  );
}

// ── Single-read funnel ──
function RetentionFunnelSingle({ pipeline }: { pipeline: PipelineStep[] }) {
  const rows = useMemo(
    () => buildFunnel(pipeline, INITIAL_READS),
    [pipeline],
  );
  const finalCount = rows.length ? rows[rows.length - 1].output : INITIAL_READS;
  const removed = INITIAL_READS - finalCount;
  const overall = finalCount / INITIAL_READS;

  return (
    <ExportCard
      title="Read retention funnel"
      subtitle="Estimated read counts across filtering steps (preview)."
      filename="custom-bulk-single-retention.png"
    >
      <div className="flex flex-wrap gap-2">
        <SummaryStat label="Initial reads" value={fmtInt(INITIAL_READS)} />
        <SummaryStat
          label="Final reads"
          value={fmtInt(finalCount)}
          accent="oklch(0.55 0.15 155)"
        />
        <SummaryStat
          label="Total removed"
          value={fmtInt(removed)}
          accent="oklch(0.6 0.18 25)"
        />
        <SummaryStat
          label="Overall retention"
          value={fmtPct(overall)}
          accent="oklch(0.5 0.18 245)"
        />
      </div>

      <div className="mx-auto mt-6 max-w-xl space-y-1">
        <InputBar label="Initial reads" count={INITIAL_READS} />
        {rows.map((r) => (
          <div key={r.id}>
            <FunnelArrow />
            <FunnelBar row={r} initial={INITIAL_READS} />
          </div>
        ))}
        <FunnelArrow />
        <OutputBar
          label="Final output"
          count={finalCount}
          initial={INITIAL_READS}
        />
      </div>
    </ExportCard>
  );
}

// ── Paired-end funnel ──
function PairSeqBanner({ index }: { index: number }) {
  const def = getDefLite("pairseq");
  return (
    <div className="my-3">
      <div
        className="rounded-lg border px-3 py-2 text-center text-[11px] font-semibold"
        style={{
          background: def.tint,
          borderColor: def.border,
          color: def.text,
        }}
      >
        PairSeq #{index} · synchronization checkpoint (counts unchanged)
      </div>
    </div>
  );
}

function FunnelBranchColumn({
  title,
  initialLabel,
  rows,
  initial,
}: {
  title: string;
  initialLabel: string;
  rows: FunnelRow[];
  initial: number;
}) {
  return (
    <div className="flex-1 min-w-0">
      <div className="mb-2 text-center text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </div>
      <div className="space-y-1">
        <InputBar label={initialLabel} count={initial} />
        {rows.length === 0 ? (
          <div className="py-3 text-center text-[10px] italic text-muted-foreground">
            no filters
          </div>
        ) : (
          rows.map((r) => (
            <div key={r.id}>
              <FunnelArrow />
              <FunnelBar row={r} initial={initial} />
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function RetentionFunnelPaired({
  read1,
  read2,
  pairedSteps,
  assembled,
}: {
  read1: PipelineStep[];
  read2: PipelineStep[];
  pairedSteps: PairedStep[];
  assembled: PipelineStep[];
}) {
  const initialR1 = INITIAL_READS;
  const initialR2 = INITIAL_READS;

  const pairSeqCount = pairedSteps.filter((s) => s.key === "pairseq").length;
  const assembleStep = pairedSteps.find((s) => s.key.startsWith("assemble-"));

  // segment branches by checkpoint
  type Segment = { r1: FunnelRow[]; r2: FunnelRow[]; endR1: number; endR2: number };
  const segments: Segment[] = [];
  let curR1 = initialR1;
  let curR2 = initialR2;
  for (let k = 0; k <= pairSeqCount; k++) {
    const r1Steps = read1.filter((s) => (s.checkpoint ?? 0) === k);
    const r2Steps = read2.filter((s) => (s.checkpoint ?? 0) === k);
    const r1Rows = buildFunnel(r1Steps, curR1);
    const r2Rows = buildFunnel(r2Steps, curR2);
    const endR1 = r1Rows.length ? r1Rows[r1Rows.length - 1].output : curR1;
    const endR2 = r2Rows.length ? r2Rows[r2Rows.length - 1].output : curR2;
    segments.push({ r1: r1Rows, r2: r2Rows, endR1, endR2 });
    curR1 = endR1;
    curR2 = endR2;
    if (k < pairSeqCount) {
      // pairseq: drop unmatched
      const rate = RETENTION_RATE.pairseq;
      curR1 = curR1 * rate;
      curR2 = curR2 * rate;
    }
  }

  // assembly merges branches into single
  const preAssemblyMin = Math.min(curR1, curR2);
  let assembledCount = preAssemblyMin;
  let assembledRows: FunnelRow[] = [];
  if (assembleStep) {
    const aRate = RETENTION_RATE[assembleStep.key] ?? 0.85;
    assembledCount = preAssemblyMin * aRate;
    assembledRows = buildFunnel(assembled, assembledCount);
  }
  const finalCount = assembleStep
    ? assembledRows.length
      ? assembledRows[assembledRows.length - 1].output
      : assembledCount
    : Math.min(curR1, curR2);

  const totalInitial = initialR1 + initialR2;
  const overall = assembleStep
    ? finalCount / Math.min(initialR1, initialR2)
    : (curR1 + curR2) / totalInitial;

  const assembleDef = assembleStep ? getDefLite(assembleStep.key) : null;

  return (
    <ExportCard
      title="Read retention funnel"
      subtitle="Estimated read counts across paired-end branches (preview)."
      filename="custom-bulk-paired-retention.png"
    >
      <div className="flex flex-wrap gap-2">
        <SummaryStat label="Read 1 initial" value={fmtInt(initialR1)} />
        <SummaryStat label="Read 2 initial" value={fmtInt(initialR2)} />
        {assembleStep && (
          <SummaryStat
            label="Assembled"
            value={fmtInt(assembledCount)}
            accent="oklch(0.55 0.15 155)"
          />
        )}
        <SummaryStat
          label="Final reads"
          value={fmtInt(finalCount)}
          accent="oklch(0.55 0.15 155)"
        />
        <SummaryStat
          label="Overall retention"
          value={fmtPct(overall)}
          accent="oklch(0.5 0.18 245)"
        />
      </div>

      <div className="mt-6 space-y-2">
        {segments.map((seg, k) => (
          <div key={k}>
            {k > 0 && <PairSeqBanner index={k} />}
            <div className="flex items-stretch gap-6">
              <FunnelBranchColumn
                title={k === 0 ? "Read 1 branch" : `Read 1 (after PairSeq #${k})`}
                initialLabel={k === 0 ? "Read 1 initial" : "Carried forward"}
                rows={seg.r1}
                initial={k === 0 ? initialR1 : segments[k - 1].endR1 * RETENTION_RATE.pairseq}
              />
              <div className="w-px self-stretch bg-border" />
              <FunnelBranchColumn
                title={k === 0 ? "Read 2 branch" : `Read 2 (after PairSeq #${k})`}
                initialLabel={k === 0 ? "Read 2 initial" : "Carried forward"}
                rows={seg.r2}
                initial={k === 0 ? initialR2 : segments[k - 1].endR2 * RETENTION_RATE.pairseq}
              />
            </div>
          </div>
        ))}

        {assembleStep && assembleDef && (
          <div className="mt-4">
            <div
              className="mx-auto max-w-md rounded-lg border px-4 py-3 text-center text-xs font-semibold shadow-sm"
              style={{
                background: `linear-gradient(180deg, ${assembleDef.tint} 0%, ${assembleDef.color} 100%)`,
                borderColor: assembleDef.border,
                color: "white",
              }}
            >
              {assembleDef.name} · merge
              <div className="mt-0.5 text-[10px] font-normal opacity-90">
                {fmtInt(preAssemblyMin)} pairs →{" "}
                {fmtInt(assembledCount)} assembled (
                {fmtPct(RETENTION_RATE[assembleStep.key] ?? 0.85)})
              </div>
            </div>

            <div className="mx-auto mt-4 max-w-xl space-y-1">
              <InputBar
                label="Assembled reads"
                count={assembledCount}
                color="oklch(0.6 0.13 155)"
              />
              {assembledRows.map((r) => (
                <div key={r.id}>
                  <FunnelArrow />
                  <FunnelBar row={r} initial={assembledCount} />
                </div>
              ))}
              <FunnelArrow />
              <OutputBar
                label="Final output"
                count={finalCount}
                initial={assembledCount}
              />
            </div>
          </div>
        )}
      </div>
    </ExportCard>
  );
}
