import { API, publicApi } from "./client";
import { getSessionToken } from "./session";

export type SingleCellFormatId =
  | "cellranger_vdj_all"
  | "cellranger_vdj_filtered"
  | "cellranger_airr_tsv"
  | "trust4"
  | "fastq_10x"
  | "bam_10x"
  | "generic_fasta";

export interface MatchedFile {
  role: string;
  file_id: string;
  filename: string;
}

export interface MissingFile {
  role: string;
  description: string;
  required: boolean;
}

/** Response shape of POST /api/singlecell/detect. */
export interface DetectionResult {
  format_id: SingleCellFormatId | null;
  label: string | null;
  matched_files: MatchedFile[];
  missing_files: MissingFile[];
  ready: boolean;
  ambiguous_format_ids: string[];
  requires_trust4: boolean;
  trust4_available: boolean;
}

export interface ValidateResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  record_count_estimate: number | null;
}

/** The two formats whose adapter has to run a TRUST4 assembly first. */
export const TRUST4_ASSEMBLY_FORMATS: SingleCellFormatId[] = [
  "fastq_10x",
  "bam_10x",
];

export type Trust4Species = "human" | "mouse";
export type Trust4Chemistry = "10x_v2" | "10x_v3" | "custom";

/** Mirrors app/singlecell/models.py::Trust4Options. */
export interface Trust4Options {
  species: Trust4Species;
  chemistry: Trust4Chemistry;
  /** Only read by the backend when chemistry === "custom". */
  barcode_start: number;
  barcode_end: number;
  umi_start: number;
  umi_end: number;
  /**
   * BAM input only. Convert the BAM to FASTQ with samtools rather than
   * handing it to TRUST4's bam-extractor. Required for any BAM that is not
   * aligned to a reference genome.
   */
  bam_extract_with_samtools: boolean;
}

export const DEFAULT_TRUST4_OPTIONS: Trust4Options = {
  species: "human",
  chemistry: "10x_v2",
  barcode_start: 0,
  barcode_end: 15,
  umi_start: 16,
  umi_end: 25,
  bam_extract_with_samtools: false,
};

export interface Trust4SpeciesInfo {
  id: string;
  label: string;
  available: boolean;
  problems: string[];
}

export interface Trust4ChemistryInfo {
  id: Trust4Chemistry;
  label: string;
  barcode_range: [number, number] | null;
  umi_range: [number, number] | null;
}

/** Response shape of GET /api/singlecell/trust4/status. */
export interface Trust4Status {
  available: boolean;
  binary: string;
  problems: string[];
  species: Trust4SpeciesInfo[];
  chemistries: Trust4ChemistryInfo[];
  default_species: string;
  threads: number;
  barcode_whitelist_configured: boolean;
}

export interface StartSingleCellJobResponse {
  session_id: string;
  job_id: string;
  format_id: string;
  /** Set only when the session has a verified email; see /api/jobs/estimate. */
  tracking_code?: string | null;
}

export function detectSingleCell(sessionId: string, fileIds: string[]) {
  return publicApi<DetectionResult>("/api/singlecell/detect", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, file_ids: fileIds }),
  });
}

/**
 * What the server can do with raw-read input right now: whether TRUST4 is
 * installed, which species references it has, and the barcode/UMI layouts it
 * offers. Independent of any session or uploaded file.
 */
export function getTrust4Status() {
  return publicApi<Trust4Status>("/api/singlecell/trust4/status");
}

/**
 * Extra arguments both /validate and /jobs/start accept once a format has
 * been chosen. `roleFileIds` maps a format role (contig_fasta, r1_fastq, …)
 * to the file uploaded into that slot; sending it stops the backend from
 * re-deriving roles from filenames, which is what lets the per-workflow
 * pages accept an arbitrarily named file in a named slot.
 */
export interface SingleCellRunOptions {
  trust4Options?: Trust4Options;
  roleFileIds?: Record<string, string>;
  /**
   * Carry Cell Ranger's `productive` call through to the output. Off by
   * default — it is annotation-derived, so the spec keeps it empty unless the
   * user explicitly asks for it.
   */
  allowProductive?: boolean;
  /**
   * Generic FASTA only: regex with one capture group, applied to the FASTA
   * header to recover the cell barcode when no mapping file is uploaded.
   */
  barcodeHeaderRegex?: string;
  /**
   * Page this run was launched from, and a human name for it. Stored with the
   * tracking code so returning via /track lands the user back here rather
   * than on a generic results screen.
   */
  route?: string;
  label?: string;
}

function runBody(
  sessionId: string,
  fileIds: string[],
  formatId: string,
  opts: SingleCellRunOptions = {},
) {
  return JSON.stringify({
    session_id: sessionId,
    file_ids: fileIds,
    format_id: formatId,
    trust4_options: opts.trust4Options ?? null,
    role_file_ids: opts.roleFileIds ?? null,
    allow_productive: opts.allowProductive ?? false,
    barcode_header_regex: opts.barcodeHeaderRegex?.trim() || null,
    route: opts.route ?? null,
    label: opts.label ?? null,
  });
}

export function validateSingleCell(
  sessionId: string,
  fileIds: string[],
  formatId: string,
  opts?: SingleCellRunOptions,
) {
  return publicApi<ValidateResult>("/api/singlecell/validate", {
    method: "POST",
    body: runBody(sessionId, fileIds, formatId, opts),
  });
}

export function startSingleCellJob(
  sessionId: string,
  fileIds: string[],
  formatId: string,
  opts?: SingleCellRunOptions,
) {
  // publicApi() already attaches X-Session-Token when one exists -- passing
  // a custom `headers` here would overwrite (not merge with) its
  // Content-Type: application/json header, since callers' `options` is
  // spread after it in client.ts.
  return publicApi<StartSingleCellJobResponse>("/api/singlecell/jobs/start", {
    method: "POST",
    body: runBody(sessionId, fileIds, formatId, opts),
  });
}

/**
 * Build a URL that downloads one of a single-cell job's output files.
 * Backed by the generic path-based download route at the application root
 * (main.py) -- unlike bulk jobs, single-cell jobs write several output
 * files, so the first-file-only `/sessions/{sid}/jobs/{jid}/download`
 * route (app/api/jobs.py) can't be used to fetch the others.
 *
 * `source_annotations.tsv` is the lossless sidecar: every field the uploaded
 * file carried, including the V(D)J calls and CDR3s the normalized output
 * omits, keyed on the same sequence_id.
 */
export function singleCellOutputUrl(
  sessionId: string,
  jobId: string,
  filename:
    | "final.fasta"
    | "metadata.tsv"
    | "source_annotations.tsv"
    | "provenance.json",
): string {
  const token = getSessionToken();
  const params = new URLSearchParams({ path: `outputs/${filename}` });
  if (token) params.set("token", token);
  return `${API}/jobs/${sessionId}/${jobId}/download?${params.toString()}`;
}
