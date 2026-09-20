import { AlertTriangle, CheckCircle2, Cpu, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type {
  SingleCellFormatId,
  Trust4Chemistry,
  Trust4Options,
  Trust4Species,
  Trust4Status,
} from "@/api/singleCell";

/**
 * Assembly settings for the two raw-read formats. Shown only when the
 * detected format needs a TRUST4 run — every other format arrives already
 * assembled, so none of this applies to it.
 */

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { id: T; label: string; disabled?: boolean; title?: string }[];
  onChange: (id: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          disabled={o.disabled}
          title={o.title}
          onClick={() => onChange(o.id)}
          className={cn(
            "rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
            value === o.id
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-border bg-background text-muted-foreground hover:text-foreground",
            o.disabled && "cursor-not-allowed opacity-40 hover:text-muted-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function RangeInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="grid gap-1.5">
      <label className="text-xs font-medium text-foreground">{label}</label>
      <Input
        type="number"
        min={0}
        value={String(value)}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

export function Trust4OptionsCard({
  status,
  isLoading,
  formatId,
  options,
  onChange,
}: {
  status: Trust4Status | undefined;
  isLoading: boolean;
  formatId: SingleCellFormatId;
  options: Trust4Options;
  onChange: (next: Trust4Options) => void;
}) {
  // A BAM already carries its barcode and UMI in the CB/UB tags, so the
  // read-1 offsets that FASTQ input needs are meaningless here.
  const needsChemistry = formatId === "fastq_10x";
  const selectedSpecies = status?.species.find((s) => s.id === options.species);

  return (
    <div
      className="rounded-2xl border border-border bg-card p-5"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          TRUST4 assembly
        </h3>
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : status?.available ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
            <CheckCircle2 className="h-3 w-3" />
            Ready
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-destructive/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-destructive">
            <AlertTriangle className="h-3 w-3" />
            Unavailable
          </span>
        )}
      </div>

      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        This input is raw reads, so TRUST4 assembles per-cell V(D)J contigs on
        the server before the standard parse → validate → write stages run.
      </p>

      {status && !status.available && status.problems.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs leading-relaxed text-destructive">
          {status.problems.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      )}

      {status && (
        <div className="mt-5 flex flex-col gap-5">
          <div className="grid gap-2">
            <label className="text-xs font-medium text-foreground">
              Reference species
            </label>
            <Segmented<Trust4Species>
              value={options.species}
              options={status.species.map((s) => ({
                id: s.id as Trust4Species,
                label: s.label,
                disabled: !s.available,
                title: s.problems.join("; ") || undefined,
              }))}
              onChange={(species) => onChange({ ...options, species })}
            />
            {selectedSpecies && !selectedSpecies.available && (
              <p className="text-[11px] leading-relaxed text-destructive">
                {selectedSpecies.problems.join(" ")}
              </p>
            )}
          </div>

          {needsChemistry ? (
            <div className="grid gap-2">
              <label className="text-xs font-medium text-foreground">
                Read 1 layout
              </label>
              <Segmented<Trust4Chemistry>
                value={options.chemistry}
                options={status.chemistries.map((c) => ({
                  id: c.id,
                  label: c.label,
                }))}
                onChange={(chemistry) => onChange({ ...options, chemistry })}
              />
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                R1 supplies the cell barcode and UMI; R2 supplies the cDNA
                read. Offsets are 0-based and inclusive.
              </p>
            </div>
          ) : (
            <div className="grid gap-3">
              <p className="rounded-lg border border-border/60 bg-background px-3 py-2 text-xs leading-relaxed text-muted-foreground">
                Cell barcodes and UMIs are read from the BAM's{" "}
                <span className="font-mono">CB</span> /{" "}
                <span className="font-mono">UB</span> tags, so no read layout
                needs to be chosen.
              </p>

              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={options.bam_extract_with_samtools}
                  onChange={(e) =>
                    onChange({
                      ...options,
                      bam_extract_with_samtools: e.target.checked,
                    })
                  }
                  className="mt-0.5 h-4 w-4 shrink-0 accent-[oklch(0.55_0.13_230)]"
                />
                <span>
                  <span className="text-xs font-medium text-foreground">
                    Extract reads with samtools first
                  </span>
                  <span className="mt-1 block text-[11px] leading-relaxed text-muted-foreground">
                    Converts the BAM to FASTQ before assembly, instead of
                    handing it straight to TRUST4. Needed whenever the BAM is
                    not aligned to a reference genome — Cell Ranger's{" "}
                    <span className="font-mono">all_contig.bam</span> is the
                    common case, since it is aligned to the assembled contigs
                    and TRUST4 otherwise fails with{" "}
                    <span className="font-mono">unknown genome name chr1</span>.
                    Barcodes and UMIs are carried across from the CB/UB tags.
                  </span>
                </span>
              </label>
            </div>
          )}

          {needsChemistry && options.chemistry === "custom" && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <RangeInput
                label="Barcode start"
                value={options.barcode_start}
                onChange={(n) => onChange({ ...options, barcode_start: n })}
              />
              <RangeInput
                label="Barcode end"
                value={options.barcode_end}
                onChange={(n) => onChange({ ...options, barcode_end: n })}
              />
              <RangeInput
                label="UMI start"
                value={options.umi_start}
                onChange={(n) => onChange({ ...options, umi_start: n })}
              />
              <RangeInput
                label="UMI end"
                value={options.umi_end}
                onChange={(n) => onChange({ ...options, umi_end: n })}
              />
            </div>
          )}

          <p className="flex items-center gap-1.5 border-t border-border/60 pt-3 text-[11px] text-muted-foreground">
            <Cpu className="h-3 w-3" />
            Runs with {status.threads} thread{status.threads === 1 ? "" : "s"}
            {status.barcode_whitelist_configured
              ? " against the configured barcode whitelist."
              : "; no barcode whitelist configured."}
          </p>
        </div>
      )}
    </div>
  );
}
