/**
 * Saved pipelines: a workflow kept so it can be run again.
 *
 * Two routes out of the builder, both the same document underneath -- stored
 * against the session and listed in the UI, or exported as a JSON file the
 * user keeps and imports later (into any session, on any machine).
 *
 * Uploaded files never travel with a pipeline: a `primer_file` parameter holds
 * the id of an upload that is deleted when retention runs out, so the backend
 * strips those and reports them in `requires_uploads` instead. Loading a saved
 * pipeline therefore asks for the primer FASTA again, by name and by step.
 */

import { publicApi, API } from "./client";
import { getSessionId, getSessionToken } from "./session";
import type { PipelineStep } from "./jobs";

/** An upload a saved pipeline needs supplied again before it can run. */
export interface RequiredUpload {
  step_index: number;
  step_name: string;
  param: string;
  required: boolean;
}

export interface SavedPipeline {
  pipeline_id: string;
  name: string;
  description: string;
  chains: 1 | 2;
  steps: PipelineStep[];
  requires_uploads: RequiredUpload[];
  source_job_id?: string | null;
  step_count: number;
  created_at: number;
  updated_at: number;
}

export interface SavePipelineBody {
  name: string;
  description?: string;
  chains: 1 | 2;
  steps: PipelineStep[];
  source_job_id?: string;
  /** Set to overwrite an existing save rather than adding another. */
  pipeline_id?: string;
}

export async function savePipeline(body: SavePipelineBody) {
  const sessionId = await getSessionId();
  return publicApi<SavedPipeline>(`/api/sessions/${sessionId}/pipelines`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listSavedPipelines(): Promise<SavedPipeline[]> {
  const sessionId = await getSessionId();
  const res = await publicApi<{ pipelines: SavedPipeline[] }>(
    `/api/sessions/${sessionId}/pipelines`,
  );
  return res.pipelines ?? [];
}

export async function deleteSavedPipeline(pipelineId: string) {
  const sessionId = await getSessionId();
  return publicApi<{ deleted: boolean }>(
    `/api/sessions/${sessionId}/pipelines/${pipelineId}`,
    { method: "DELETE" },
  );
}

/**
 * Read an exported pipeline file back into a runnable step list.
 *
 * The document is checked against this server's component catalog, so a file
 * naming a step that no longer exists fails here with a sentence about that
 * step rather than deep inside a run.
 */
export interface ImportedPipeline {
  name: string;
  description: string;
  chains: 1 | 2;
  steps: PipelineStep[];
  requires_uploads: RequiredUpload[];
  saved: SavedPipeline | null;
}

export async function importPipeline(document: unknown, save = false) {
  const sessionId = await getSessionId();
  return publicApi<ImportedPipeline>(
    `/api/sessions/${sessionId}/pipelines/import?save=${save ? "true" : "false"}`,
    { method: "POST", body: JSON.stringify({ document }) },
  );
}

/**
 * Download URL for a saved pipeline's JSON file.
 *
 * Used as a plain `<a href>`, which cannot set headers, so the session token
 * travels as a query parameter -- the same arrangement the file downloads use.
 */
export async function exportPipelineUrl(pipelineId: string): Promise<string> {
  const sessionId = await getSessionId();
  const token = getSessionToken();
  const suffix = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${API}/api/sessions/${sessionId}/pipelines/${pipelineId}/export${suffix}`;
}

/**
 * Build the same document the export endpoint returns, without a round trip.
 *
 * Lets the builder offer "export" for a pipeline that has not been saved to
 * the session -- the file is the whole point, and requiring a save first would
 * leave a stray entry behind for anyone who only wanted the download.
 */
export function buildExportDocument(input: {
  name: string;
  description?: string;
  chains: 1 | 2;
  steps: PipelineStep[];
}): Record<string, unknown> {
  return {
    format: "airr-preprocessor.pipeline",
    version: 1,
    name: input.name,
    description: input.description ?? "",
    chains: input.chains,
    steps: input.steps.map((s) => ({
      id: s.id,
      name: s.name,
      lanes: s.lanes,
      params: s.params,
    })),
    exported_at: Date.now() / 1000,
  };
}

/** Trigger a browser download of a pipeline document as a .json file. */
export function downloadPipelineDocument(
  pipelineDoc: Record<string, unknown>,
  name: string,
) {
  const safe = (name || "pipeline").replace(/[^A-Za-z0-9._-]+/g, "_");
  const blob = new Blob([JSON.stringify(pipelineDoc, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${safe}.pipeline.json`;
  a.click();
  URL.revokeObjectURL(url);
}
