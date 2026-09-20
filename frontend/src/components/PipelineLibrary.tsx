import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  BookMarked,
  Check,
  Download,
  FolderOpen,
  Loader2,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { readApiError, type PipelineStep } from "@/api/jobs";
import {
  buildExportDocument,
  deleteSavedPipeline,
  downloadPipelineDocument,
  importPipeline,
  listSavedPipelines,
  savePipeline,
  type ImportedPipeline,
  type SavedPipeline,
} from "@/api/savedPipelines";

/**
 * Keep, export and reload a pipeline.
 *
 * Assembling a workflow is the slow, considered part of a run -- a dozen steps
 * with parameters chosen against one library prep. Rebuilding it from memory
 * next month is how two runs end up quietly different, so a pipeline can be
 * saved to the session and reloaded in one click, or exported as a file that
 * imports into any session on any machine.
 *
 * Uploads are deliberately not part of a saved pipeline: a `primer_file`
 * parameter holds the id of an upload that retention will delete, and a saved
 * workflow pointing at a missing file would fail at launch with an id nobody
 * can read. The backend strips them and reports what is needed, which is what
 * the "needs files" note on each entry comes from.
 */
export function PipelineLibrary({
  steps,
  chains,
  onLoad,
  disabled,
  sourceJobId,
}: {
  /** The pipeline currently in the builder; empty disables saving. */
  steps: PipelineStep[];
  chains: 1 | 2;
  /** Replace the builder's pipeline with a saved or imported one. */
  onLoad: (loaded: {
    steps: PipelineStep[];
    chains: 1 | 2;
    name: string;
    requiresUploads: ImportedPipeline["requires_uploads"];
  }) => void;
  disabled?: boolean;
  sourceJobId?: string;
}) {
  const queryClient = useQueryClient();
  const saved = useQuery({ queryKey: ["saved-pipelines"], queryFn: listSavedPipelines });

  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const canSave = steps.length > 0 && !disabled;

  const handleSave = async () => {
    if (!canSave) return;
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const record = await savePipeline({
        name: name.trim() || defaultName(steps),
        chains,
        steps,
        source_job_id: sourceJobId,
      });
      setName("");
      setNotice(`Saved "${record.name}" — ${record.step_count} steps.`);
      await queryClient.invalidateQueries({ queryKey: ["saved-pipelines"] });
    } catch (e) {
      setError(readApiError(e));
    } finally {
      setBusy(null);
    }
  };

  // Exported without saving first: the file is the whole point, and forcing a
  // save would leave a stray entry behind for anyone who only wanted it.
  const handleExport = () => {
    if (steps.length === 0) return;
    const label = name.trim() || defaultName(steps);
    downloadPipelineDocument(
      buildExportDocument({ name: label, chains, steps }),
      label,
    );
    setNotice(`Exported "${label}" as a .pipeline.json file.`);
  };

  const handleImportFile = async (file: File) => {
    setBusy("import");
    setError(null);
    setNotice(null);
    try {
      const text = await file.text();
      const imported = await importPipeline(JSON.parse(text));
      onLoad({
        steps: imported.steps,
        chains: imported.chains,
        name: imported.name,
        requiresUploads: imported.requires_uploads,
      });
      setName(imported.name);
      setNotice(`Loaded "${imported.name}" — ${imported.steps.length} steps.`);
    } catch (e) {
      setError(
        e instanceof SyntaxError
          ? "That file is not valid JSON."
          : readApiError(e),
      );
    } finally {
      setBusy(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleLoadSaved = (record: SavedPipeline) => {
    onLoad({
      steps: record.steps,
      chains: record.chains,
      name: record.name,
      requiresUploads: record.requires_uploads,
    });
    setName(record.name);
    setNotice(`Loaded "${record.name}" — ${record.step_count} steps.`);
    setError(null);
  };

  const handleDelete = async (record: SavedPipeline) => {
    setBusy(record.pipeline_id);
    try {
      await deleteSavedPipeline(record.pipeline_id);
      await queryClient.invalidateQueries({ queryKey: ["saved-pipelines"] });
    } catch (e) {
      setError(readApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const records = saved.data ?? [];

  return (
    <div
      className="rounded-2xl border border-border bg-card p-5"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <h3 className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        <BookMarked className="h-4 w-4" /> Pipeline library
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Save this workflow to run it again later, or export it as a file you can
        keep and import anywhere. Uploaded primer and reference files are not
        included — you will be asked for those again.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={steps.length ? defaultName(steps) : "Name this pipeline"}
          className="h-9 w-full sm:w-64"
          disabled={disabled}
        />
        <Button
          size="sm"
          onClick={handleSave}
          disabled={!canSave || busy === "save"}
          className="gap-1.5"
          title={canSave ? undefined : "Add at least one step first"}
        >
          {busy === "save" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          Save
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={handleExport}
          disabled={steps.length === 0 || disabled}
          className="gap-1.5"
        >
          <Download className="h-3.5 w-3.5" /> Export file
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleImportFile(f);
          }}
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => fileRef.current?.click()}
          disabled={busy === "import" || disabled}
          className="gap-1.5"
        >
          {busy === "import" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Upload className="h-3.5 w-3.5" />
          )}
          Import file
        </Button>
      </div>

      {notice && (
        <p className="mt-3 inline-flex items-center gap-2 text-sm text-emerald-600">
          <Check className="h-4 w-4" /> {notice}
        </p>
      )}
      {error && (
        <p className="mt-3 inline-flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4" /> {error}
        </p>
      )}

      {records.length > 0 && (
        <div className="mt-5">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Saved in this session
          </h4>
          <ul className="mt-2 flex flex-col gap-2">
            {records.map((record) => {
              const needs = record.requires_uploads?.filter((u) => u.required) ?? [];
              return (
                <li
                  key={record.pipeline_id}
                  className="flex flex-wrap items-center gap-3 rounded-xl border border-border px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium text-foreground">
                        {record.name}
                      </span>
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {record.step_count} steps
                      </span>
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {record.chains === 2 ? "paired-end" : "single-read"}
                      </span>
                    </div>
                    {needs.length > 0 && (
                      <p className="mt-1 text-[11px] text-amber-600">
                        Needs files again:{" "}
                        {needs.map((u) => `${u.step_name}.${u.param}`).join(", ")}
                      </p>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1.5"
                    onClick={() => handleLoadSaved(record)}
                    disabled={disabled}
                  >
                    <FolderOpen className="h-3.5 w-3.5" /> Load
                  </Button>
                  <button
                    type="button"
                    title="Delete this saved pipeline"
                    onClick={() => handleDelete(record)}
                    disabled={busy === record.pipeline_id}
                    className={cn(
                      "text-muted-foreground transition-colors hover:text-destructive",
                      busy === record.pipeline_id && "opacity-50",
                    )}
                  >
                    {busy === record.pipeline_id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/** "MaskPrimers to CollapseSeq (6 steps)" — a name that beats "Untitled". */
function defaultName(steps: PipelineStep[]): string {
  if (steps.length === 0) return "Untitled pipeline";
  const first = steps[0].name.split(".")[0];
  const last = steps[steps.length - 1].name.split(".")[0];
  const span = first === last ? first : `${first} to ${last}`;
  return `${span} (${steps.length} step${steps.length === 1 ? "" : "s"})`;
}
