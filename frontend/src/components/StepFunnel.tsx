import { useRef, useState } from "react";
import { toPng } from "html-to-image";
import type { StepStat } from "@/api/jobs";
import { KIND_STYLE, familyKind, type StepKind } from "@/lib/stepColors";
import { Button } from "@/components/ui/button";
import { Download, Loader2 } from "lucide-react";

export type { StepKind };

/** Color family for a step (re-exported for callers that build progress steps). */
export const kindForStep = familyKind;

export function humanizeStepName(name: string, lanes?: string[]): string {
  const base = name.replace(/\./g, " ");
  const lane = lanes && lanes.length === 1 && lanes[0] !== "R1" ? ` · ${lanes[0]}` : "";
  return `${base}${lane}`;
}

const fmtInt = (n: number) => Math.round(n).toLocaleString();
const fmtPct = (n: number) => (Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—");

function FunnelArrow() {
  return (
    <div className="flex justify-center py-1">
      <div className="h-3 w-px bg-border" />
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
        className="flex h-11 w-full items-center justify-between rounded-lg border px-3 text-[11px] font-semibold text-white shadow-sm"
        style={{
          background: `linear-gradient(180deg, ${color} 0%, oklch(0.4 0.05 240) 100%)`,
          borderColor: color,
        }}
      >
        <span className="truncate">{label}</span>
        <span className="tabular-nums">100%</span>
      </div>
      <div className="mt-1 text-[10px] text-muted-foreground">
        <span className="font-semibold tabular-nums text-foreground/80">{fmtInt(count)}</span>{" "}
        sequences
      </div>
    </div>
  );
}

/** One funnel bar: step name, cumulative %, and remaining/removed/step stats. */
function FunnelRow({
  index,
  name,
  lanes,
  input,
  output,
  initial,
}: {
  index: number;
  name: string;
  lanes?: string[];
  input: number;
  output: number;
  initial: number;
}) {
  const removed = Math.max(0, input - output);
  const stepRetention = input > 0 ? output / input : 0;
  const cumulative = initial > 0 ? output / initial : 0;
  const widthPct = Math.max(8, cumulative * 100);
  const c = KIND_STYLE[familyKind(name)];

  return (
    <div className="flex flex-col items-center">
      <FunnelArrow />
      {/* The name sits above the bar, not inside it: the bar narrows with
          retention, and a name inside a narrow bar was clipped to nothing,
          leaving late steps unlabelled in the exported figure. */}
      <div className="mb-1 w-full px-1 text-center text-[11px] font-medium text-foreground/80">
        {index}. {humanizeStepName(name, lanes)}
      </div>
      <div className="relative h-10 w-full">
        <div
          className="absolute left-1/2 top-0 -translate-x-1/2 rounded-lg shadow-sm transition-all"
          style={{
            width: `${widthPct}%`,
            height: "100%",
            background: `linear-gradient(180deg, ${c.tint} 0%, ${c.color} 100%)`,
            border: `1px solid ${c.border}`,
          }}
        >
          <div className="flex h-full items-center justify-center px-3 text-[11px] font-medium text-white drop-shadow-sm">
            <span className="tabular-nums">{fmtPct(cumulative)}</span>
          </div>
        </div>
      </div>
      <div className="mt-1 grid w-full grid-cols-3 gap-2 px-1 text-[10px] text-muted-foreground">
        <div>
          <div className="font-semibold tabular-nums text-foreground/80">{fmtInt(output)}</div>
          <div>remaining</div>
        </div>
        <div className="text-center">
          <div className="font-semibold tabular-nums text-rose-600/80">−{fmtInt(removed)}</div>
          <div>removed</div>
        </div>
        <div className="text-right">
          <div className="font-semibold tabular-nums text-foreground/80">
            {fmtPct(stepRetention)}
          </div>
          <div>step</div>
        </div>
      </div>
    </div>
  );
}

/** Single-stream funnel (one input → steps → output). */
function SingleColumnFunnel({ rows }: { rows: StepStat[] }) {
  const initial = rows[0]?.before ?? 0;
  return (
    <>
      <InputBar label="Input sequences" count={initial} />
      {rows.map((row) => (
        <FunnelRow
          key={row.index}
          index={row.index}
          name={row.name}
          lanes={row.lanes}
          input={row.before ?? 0}
          output={row.remaining ?? 0}
          initial={initial}
        />
      ))}
    </>
  );
}

type LanePoint = { index: number; name: string; before: number; remaining: number };

function laneSeries(rows: StepStat[], lane: string): LanePoint[] {
  const out: LanePoint[] = [];
  for (const r of rows) {
    const cell = r.by_lane?.[lane];
    if (!cell) continue;
    out.push({
      index: r.index,
      name: r.name,
      before: cell.before ?? 0,
      remaining: cell.remaining ?? 0,
    });
  }
  return out;
}

function LaneFunnelColumn({
  title,
  rows,
  initial,
}: {
  title: string;
  rows: LanePoint[];
  initial: number;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 text-center text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </div>
      <InputBar label={`${title} input`} count={initial} />
      {rows.length === 0 ? (
        <div className="py-3 text-center text-[10px] italic text-muted-foreground">no steps</div>
      ) : (
        rows.map((r) => (
          <FunnelRow
            key={r.index}
            index={r.index}
            name={r.name}
            input={r.before}
            output={r.remaining}
            initial={initial}
          />
        ))
      )}
    </div>
  );
}

/**
 * Paired-end funnel: Read 1 and Read 2 are drawn as two separate columns in the
 * same frame. If the pipeline merges (AssembleSeq), a merge banner is shown and
 * the assembled stream continues as a single centered column.
 */
function PairedFunnel({ rows }: { rows: StepStat[] }) {
  const mergeIdx = rows.findIndex((r) => r.by_lane && "merged" in r.by_lane);
  const pre = mergeIdx < 0 ? rows : rows.slice(0, mergeIdx);
  const mergeRow = mergeIdx >= 0 ? rows[mergeIdx] : null;
  const post = mergeIdx >= 0 ? rows.slice(mergeIdx + 1) : [];

  const r1 = laneSeries(pre, "R1");
  const r2 = laneSeries(pre, "R2");
  const r1Init = r1[0]?.before ?? 0;
  const r2Init = r2[0]?.before ?? 0;

  const mergedCell = mergeRow?.by_lane?.merged;
  const assembledCount = mergedCell?.remaining ?? mergeRow?.remaining ?? 0;
  const pairsBefore = mergedCell?.before ?? mergeRow?.before ?? 0;

  return (
    <div>
      <div className="grid grid-cols-2 gap-4">
        <LaneFunnelColumn title="Read 1" rows={r1} initial={r1Init} />
        <div className="relative">
          <div className="absolute -left-2 top-6 hidden h-[calc(100%-1.5rem)] w-px bg-border sm:block" />
          <LaneFunnelColumn title="Read 2" rows={r2} initial={r2Init} />
        </div>
      </div>

      {mergeRow && (
        <div className="mt-4">
          <div
            className="mx-auto max-w-sm rounded-lg border px-4 py-2.5 text-center text-xs font-semibold text-white shadow-sm"
            style={{
              background: `linear-gradient(180deg, ${KIND_STYLE[familyKind(mergeRow.name)].color} 0%, oklch(0.4 0.05 160) 100%)`,
              borderColor: KIND_STYLE[familyKind(mergeRow.name)].border,
            }}
          >
            {mergeRow.name} · merge
            <div className="mt-0.5 text-[10px] font-normal opacity-90">
              {fmtInt(pairsBefore)} pairs → {fmtInt(assembledCount)} assembled
            </div>
          </div>

          <div className="mx-auto mt-3 max-w-sm">
            <InputBar label="Assembled" count={assembledCount} color="oklch(0.6 0.13 160)" />
            {post.map((r) => (
              <FunnelRow
                key={r.index}
                index={r.index}
                name={r.name}
                lanes={r.lanes}
                input={r.before ?? 0}
                output={r.remaining ?? 0}
                initial={assembledCount}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Funnel of real sequence retention across the pipeline, built from the
 * backend's per-step `before` / `remaining` / `failed` counts. Renders one
 * column for single-stream runs and two columns (R1 / R2) for paired runs.
 */
export function StepFunnel({
  stepStats,
  className,
  showDownload = false,
}: {
  stepStats: StepStat[];
  className?: string;
  showDownload?: boolean;
}) {
  const rows = [...stepStats].sort((a, b) => a.index - b.index);
  if (rows.length === 0) return null;

  const isPaired = rows.some((r) => r.by_lane && "R2" in r.by_lane);

  const funnelRef = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (!funnelRef.current) return;
    setDownloading(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 150));
      const dataUrl = await toPng(funnelRef.current, {
        pixelRatio: 2.5,
        backgroundColor: "#ffffff",
        cacheBust: true,
      });
      const a = document.createElement("a");
      a.download = `sequence-retention-${new Date().toISOString().slice(0, 10)}.png`;
      a.href = dataUrl;
      a.click();
    } catch (e) {
      console.error("Download funnel chart failed", e);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className={className}>
      {showDownload && (
        <div className="mb-3 flex justify-end">
          <Button
            size="sm"
            variant="ghost"
            onClick={handleDownload}
            disabled={downloading}
            className="h-7 gap-1 px-2 text-xs"
            title="Download retention chart as PNG"
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            <span className="hidden sm:inline">PNG</span>
          </Button>
        </div>
      )}
      <div ref={funnelRef}>
        {isPaired ? <PairedFunnel rows={rows} /> : <SingleColumnFunnel rows={rows} />}
      </div>
    </div>
  );
}