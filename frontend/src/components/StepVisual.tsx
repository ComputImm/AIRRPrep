/**
 * <StepVisual/> — before→after illustrations for the documentation page.
 *
 * Every illustration shows an INPUT panel and an OUTPUT panel so the reader can
 * see exactly what a step does:
 *   - "transform" steps: the read itself comes out different (shorter, masked,
 *     merged, or with edited header annotations).
 *   - "filter" steps: surviving reads are drawn byte-for-byte identical to the
 *     input — only which/where/how-many records change.
 *
 * The drawings are schematic, not real pRESTO output.
 */

import type { KindStyle } from "@/lib/stepColors";

export type VisualKind =
  | "trim"
  | "mask"
  | "primer"
  | "collapse"
  | "consensus"
  | "pair"
  | "assemble"
  | "header"
  | "filter-length"
  | "filter-quality"
  | "filter-missing"
  | "filter-repeats"
  | "select"
  | "sort"
  | "sample"
  | "split-count"
  | "split-group"
  | "table";

interface StepVisualProps {
  kind: VisualKind;
  accent: KindStyle;
  headerBefore?: string;
  headerAfter?: string;
}

/** Nucleotide colors (fixed — independent of theme). */
const BASE_FILL: Record<string, string> = {
  A: "#34d399",
  C: "#60a5fa",
  G: "#fbbf24",
  T: "#fb7185",
  N: "#cbd5e1",
};

const CELL_W = 12;
const CELL_H = 16;
const STROKE = "rgba(100,116,139,0.45)";
const MUTED = "rgba(100,116,139,0.95)";

let _k = 0;
const key = () => `v${_k++}`;

/** A run of nucleotide cells. */
function Seq({
  seq,
  x = 0,
  y = 0,
  dim = false,
}: {
  seq: string;
  x?: number;
  y?: number;
  dim?: boolean;
}) {
  return (
    <g opacity={dim ? 0.3 : 1}>
      {seq.split("").map((b, i) => (
        <g key={key()} transform={`translate(${x + i * CELL_W}, ${y})`}>
          <rect width={CELL_W - 1.5} height={CELL_H} rx={2} fill={BASE_FILL[b] ?? "#e2e8f0"} />
          <text
            x={(CELL_W - 1.5) / 2}
            y={CELL_H / 2 + 3}
            textAnchor="middle"
            fontSize={8.5}
            fontFamily="ui-monospace, monospace"
            fill="rgba(15,23,42,0.75)"
          >
            {b}
          </text>
        </g>
      ))}
    </g>
  );
}

function Eyebrow({ x, text }: { x: number; text: string }) {
  return (
    <text x={x} y={18} fontSize={10} fontWeight={700} letterSpacing={1} fill={MUTED}>
      {text}
    </text>
  );
}

function Arrow({ y }: { y: number }) {
  return (
    <g>
      <line x1={256} y1={y} x2={300} y2={y} stroke={MUTED} strokeWidth={2} />
      <path d={`M300 ${y} l-9 -5 v10 z`} fill={MUTED} />
    </g>
  );
}

function XMark({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <circle cx={x} cy={y} r={7} fill="#ef4444" />
      <path
        d={`M${x - 3} ${y - 3} l6 6 M${x + 3} ${y - 3} l-6 6`}
        stroke="#fff"
        strokeWidth={1.6}
        strokeLinecap="round"
      />
    </g>
  );
}

function Chip({
  x,
  y,
  text,
  fill,
  textColor = "#fff",
}: {
  x: number;
  y: number;
  text: string;
  fill: string;
  textColor?: string;
}) {
  const w = text.length * 6 + 12;
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect width={w} height={16} rx={8} fill={fill} />
      <text
        x={w / 2}
        y={11}
        textAnchor="middle"
        fontSize={9}
        fontFamily="ui-monospace, monospace"
        fill={textColor}
      >
        {text}
      </text>
    </g>
  );
}

function Caption({ text, y = 0 }: { text: string; y?: number }) {
  return (
    <text x={280} y={y} textAnchor="middle" fontSize={10.5} fill={MUTED}>
      {text}
    </text>
  );
}

function Frame({ h, children }: { h: number; children: React.ReactNode }) {
  return (
    <svg
      viewBox={`0 0 560 ${h}`}
      className="h-auto w-full select-none"
      fontFamily="ui-sans-serif, system-ui, sans-serif"
      role="img"
    >
      <Eyebrow x={24} text="INPUT" />
      <Eyebrow x={320} text="OUTPUT" />
      {children}
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/* Scenes                                                              */
/* ------------------------------------------------------------------ */

function TrimScene() {
  // low-quality ends (first/last 3 bases) trimmed off
  const seq = "ACGTTAGCCGTAACGTT";
  const keep = seq.slice(3, -3);
  const cut = 3 * CELL_W;
  return (
    <Frame h={150}>
      <g transform="translate(24,40)">
        <Seq seq={seq} />
        <rect x={0} width={cut} height={CELL_H} fill="#ef4444" opacity={0.25} rx={2} />
        <rect
          x={seq.length * CELL_W - cut}
          width={cut}
          height={CELL_H}
          fill="#ef4444"
          opacity={0.25}
          rx={2}
        />
        <text x={0} y={34} fontSize={9.5} fill={MUTED}>
          low-quality ends (windowed Q below cutoff)
        </text>
      </g>
      <Arrow y={48} />
      <g transform="translate(320,40)">
        <Seq seq={keep} />
        <text x={0} y={34} fontSize={9.5} fill={MUTED}>
          {seq.length} bp → {keep.length} bp
        </text>
      </g>
      <Caption text="Read survives but is shortened — the sequence changes." y={120} />
    </Frame>
  );
}

function MaskScene() {
  const seq = "ACGTTAGCCGTAACGT";
  const after = seq
    .split("")
    .map((b, i) => (i === 3 || i === 4 || i === 10 ? "N" : b))
    .join("");
  return (
    <Frame h={150}>
      <g transform="translate(24,40)">
        <Seq seq={seq} />
        <rect
          x={3 * CELL_W}
          width={2 * CELL_W}
          height={CELL_H}
          fill="#ef4444"
          opacity={0.22}
          rx={2}
        />
        <rect x={10 * CELL_W} width={CELL_W} height={CELL_H} fill="#ef4444" opacity={0.22} rx={2} />
        <text x={0} y={34} fontSize={9.5} fill={MUTED}>
          low-quality bases (highlighted)
        </text>
      </g>
      <Arrow y={48} />
      <g transform="translate(320,40)">
        <Seq seq={after} />
        <text x={0} y={34} fontSize={9.5} fill={MUTED}>
          same length, weak bases → N
        </text>
      </g>
      <Caption text="Length is preserved; the content of the read is edited." y={120} />
    </Frame>
  );
}

function PrimerScene({ accent }: { accent: KindStyle }) {
  const seq = "GTACGCAGCTTAGCCGTAAC";
  const primerLen = 6;
  const after = "NNNNNN" + seq.slice(primerLen);
  return (
    <Frame h={160}>
      <g transform="translate(24,42)">
        <Seq seq={seq} />
        <rect
          x={-1}
          y={-2}
          width={primerLen * CELL_W}
          height={CELL_H + 4}
          rx={3}
          fill="none"
          stroke={accent.color}
          strokeWidth={2}
        />
        <text x={0} y={34} fontSize={9.5} fill={accent.color} fontWeight={600}>
          primer region
        </text>
      </g>
      <Arrow y={50} />
      <g transform="translate(320,42)">
        <Seq seq={after} />
        <Chip x={0} y={26} text="PRIMER=VH" fill={accent.color} />
      </g>
      <Caption text="Primer is masked AND a PRIMER annotation is added." y={132} />
    </Frame>
  );
}

function CollapseScene({ accent }: { accent: KindStyle }) {
  const seq = "ACGTTAGCCGTA";
  return (
    <Frame h={170}>
      <g transform="translate(24,36)">
        {[0, 1, 2].map((i) => (
          <g key={key()} transform={`translate(0, ${i * 26})`}>
            <Seq seq={seq} />
          </g>
        ))}
        <text x={0} y={94} fontSize={9.5} fill={MUTED}>
          3 identical reads
        </text>
      </g>
      <Arrow y={70} />
      <g transform="translate(320,62)">
        <Seq seq={seq} />
        <Chip x={0} y={26} text="DUPCOUNT=3" fill={accent.color} />
      </g>
      <Caption text="Duplicates merge into one record carrying the count." y={150} />
    </Frame>
  );
}

function ConsensusScene({ accent }: { accent: KindStyle }) {
  const base = "ACGTTAGCCGTA";
  const variants = [
    base,
    "ACATTAGCCGTA", // pos 2 differs
    "ACGTTAGCCTTA", // pos 9 differs
    base,
  ];
  return (
    <Frame h={185}>
      <g transform="translate(24,36)">
        {variants.map((v, i) => (
          <g key={key()} transform={`translate(0, ${i * 24})`}>
            <Seq seq={v} />
          </g>
        ))}
        <Chip x={0} y={100} text="UMI=ACGT group" fill={MUTED} />
      </g>
      <Arrow y={78} />
      <g transform="translate(320,70)">
        <Seq seq={base} />
        <Chip x={0} y={26} text="CONSCOUNT=4" fill={accent.color} />
      </g>
      <Caption text="One newly computed, error-corrected sequence per group." y={166} />
    </Frame>
  );
}

function AssembleScene({ accent }: { accent: KindStyle }) {
  const r1 = "ACGTTAGCCG";
  const overlap = "TAAC";
  const r2tail = "GGTTCA";
  const merged = r1 + overlap + r2tail;
  return (
    <Frame h={170}>
      <g transform="translate(24,38)">
        <text x={0} y={-4} fontSize={9} fill={MUTED}>
          R1
        </text>
        <Seq seq={r1 + overlap} />
        <g transform="translate(0,30)">
          <text x={0} y={-4} fontSize={9} fill={MUTED}>
            R2
          </text>
          <Seq seq={overlap + r2tail} x={r1.length * CELL_W} />
        </g>
        <rect
          x={r1.length * CELL_W}
          y={-2}
          width={overlap.length * CELL_W}
          height={CELL_H * 2 + 30 - 26}
          rx={3}
          fill={accent.color}
          opacity={0.16}
        />
        <text x={0} y={64} fontSize={9.5} fill={MUTED}>
          overlapping region
        </text>
      </g>
      <Arrow y={62} />
      <g transform="translate(320,54)">
        <Seq seq={merged} />
        <text x={0} y={34} fontSize={9.5} fill={MUTED}>
          one assembled read
        </text>
      </g>
      <Caption text="Two mates → a single, longer sequence." y={150} />
    </Frame>
  );
}

function PairScene({ accent }: { accent: KindStyle }) {
  const r1 = [1, 2, 3];
  const r2 = [1, 3, 4];
  const kept = [1, 3];
  const row = (id: number, dropped: boolean) => (
    <g key={key()}>
      <rect
        width={70}
        height={16}
        rx={3}
        fill={dropped ? "#f1f5f9" : accent.tint}
        stroke={STROKE}
        opacity={dropped ? 0.5 : 1}
      />
      <text
        x={8}
        y={11}
        fontSize={9}
        fontFamily="ui-monospace, monospace"
        fill={accent.text}
        opacity={dropped ? 0.5 : 1}
      >
        read_{id}
      </text>
    </g>
  );
  return (
    <Frame h={168}>
      <g transform="translate(24,34)">
        <text x={0} y={-2} fontSize={9} fill={MUTED}>
          R1 file
        </text>
        {r1.map((id, i) => (
          <g key={key()} transform={`translate(0, ${i * 22})`}>
            {row(id, !kept.includes(id))}
          </g>
        ))}
        <text x={110} y={-2} fontSize={9} fill={MUTED}>
          R2 file
        </text>
        {r2.map((id, i) => (
          <g key={key()} transform={`translate(110, ${i * 22})`}>
            {row(id, !kept.includes(id))}
          </g>
        ))}
        <text x={0} y={84} fontSize={9.5} fill={MUTED}>
          read_2 / read_4 have no mate
        </text>
      </g>
      <Arrow y={58} />
      <g transform="translate(320,40)">
        {kept.map((id, i) => (
          <g key={key()} transform={`translate(0, ${i * 22})`}>
            {row(id, false)}
          </g>
        ))}
        <Chip x={0} y={kept.length * 22 + 4} text="annotations copied across mates" fill={MUTED} />
      </g>
      <Caption text="Unpaired reads dropped; headers synced between mates." y={150} />
    </Frame>
  );
}

function tokensOf(s: string) {
  // "@SEQ1|UMI=ACGT|PRIMER=VH" -> ["@SEQ1", "UMI=ACGT", "PRIMER=VH"]
  return s.split("|");
}

function HeaderScene({
  accent,
  headerBefore = "@SEQ1",
  headerAfter = "@SEQ1|NEW=val",
}: {
  accent: KindStyle;
  headerBefore?: string;
  headerAfter?: string;
}) {
  const seq = "ACGTTAGCCGTA";
  const before = tokensOf(headerBefore);
  const after = tokensOf(headerAfter);
  const beforeSet = new Set(before);
  const afterSet = new Set(after);

  const renderTokens = (tokens: string[], otherSet: Set<string>, mode: "before" | "after") => {
    let x = 0;
    return tokens.map((t, i) => {
      const isId = i === 0;
      const changed = !isId && !otherSet.has(t);
      const fill = isId
        ? "#e2e8f0"
        : changed
          ? mode === "after"
            ? accent.color
            : "#fecaca"
          : "#e2e8f0";
      const textColor = changed && mode === "after" ? "#fff" : "rgba(15,23,42,0.8)";
      const w = t.length * 6.2 + 12;
      const node = (
        <g key={key()} transform={`translate(${x}, 0)`}>
          <rect width={w} height={18} rx={4} fill={fill} stroke={STROKE} />
          <text
            x={w / 2}
            y={12.5}
            textAnchor="middle"
            fontSize={9.5}
            fontFamily="ui-monospace, monospace"
            fill={textColor}
          >
            {t}
          </text>
          {mode === "before" && changed && (
            <line x1={2} y1={9} x2={w - 2} y2={9} stroke="#ef4444" strokeWidth={1.4} />
          )}
        </g>
      );
      x += w + 5;
      return node;
    });
  };

  return (
    <Frame h={148}>
      <g transform="translate(24,40)">
        <text x={0} y={-6} fontSize={9} fill={MUTED}>
          header
        </text>
        {renderTokens(before, afterSet, "before")}
        <g transform="translate(0,26)">
          <Seq seq={seq} />
          <text x={seq.length * CELL_W + 8} y={12} fontSize={9} fill={MUTED}>
            unchanged
          </text>
        </g>
      </g>
      <Arrow y={50} />
      <g transform="translate(320,40)">
        <text x={0} y={-6} fontSize={9} fill={MUTED}>
          header
        </text>
        {renderTokens(after, beforeSet, "after")}
        <g transform="translate(0,26)">
          <Seq seq={seq} />
          <text x={seq.length * CELL_W + 8} y={12} fontSize={9} fill={MUTED}>
            unchanged
          </text>
        </g>
      </g>
      <Caption text="Only the annotation in the header changes — the DNA does not." y={130} />
    </Frame>
  );
}

/** Generic "drop some whole reads" scene used by the FilterSeq filters. */
function FilterScene({
  reads,
  reasonLabel,
  accent,
  guide,
}: {
  // each read: { seq, fail, note? }
  reads: { seq: string; fail: boolean; note?: string }[];
  reasonLabel: string;
  accent: KindStyle;
  guide?: React.ReactNode;
}) {
  const survivors = reads.filter((r) => !r.fail);
  return (
    <Frame h={Math.max(150, reads.length * 26 + 70)}>
      <g transform="translate(24,36)">
        {reads.map((r, i) => (
          <g key={key()} transform={`translate(0, ${i * 26})`}>
            <Seq seq={r.seq} dim={r.fail} />
            {r.note && (
              <text
                x={r.seq.length * CELL_W + 8}
                y={12}
                fontSize={9}
                fill={r.fail ? "#ef4444" : MUTED}
              >
                {r.note}
              </text>
            )}
            {r.fail && <XMark x={-12} y={CELL_H / 2} />}
          </g>
        ))}
        {guide}
        <text x={0} y={reads.length * 26 + 8} fontSize={9.5} fill={MUTED}>
          {reasonLabel}
        </text>
      </g>
      <Arrow y={36 + (reads.length * 26) / 2 - 8} />
      <g transform="translate(320,36)">
        {survivors.map((r, i) => (
          <g key={key()} transform={`translate(0, ${i * 26})`}>
            <Seq seq={r.seq} />
          </g>
        ))}
        <text x={0} y={survivors.length * 26 + 8} fontSize={9.5} fill={accent.text}>
          survivors — byte-for-byte identical
        </text>
      </g>
    </Frame>
  );
}

function FilterLengthScene({ accent }: { accent: KindStyle }) {
  const minLen = 10;
  const reads = [
    { seq: "ACGTTAGCCGTAAC", fail: false },
    { seq: "ACGTTAG", fail: true, note: "too short" },
    { seq: "ACGTTAGCCGTA", fail: false },
    { seq: "ACGTT", fail: true, note: "too short" },
  ];
  const guide = (
    <line
      x1={minLen * CELL_W}
      y1={-6}
      x2={minLen * CELL_W}
      y2={reads.length * 26 - 8}
      stroke={accent.color}
      strokeWidth={1.6}
      strokeDasharray="4 3"
    />
  );
  return (
    <FilterScene
      reads={reads}
      accent={accent}
      guide={guide}
      reasonLabel="dashed line = minimum length"
    />
  );
}

function FilterQualityScene({ accent }: { accent: KindStyle }) {
  const reads = [
    { seq: "ACGTTAGCCGTA", fail: false, note: "Q38" },
    { seq: "ACGTTAGCCGTA", fail: true, note: "Q14" },
    { seq: "ACGTTAGCCGTA", fail: false, note: "Q33" },
    { seq: "ACGTTAGCCGTA", fail: true, note: "Q9" },
  ];
  return (
    <FilterScene reads={reads} accent={accent} reasonLabel="mean quality below cutoff fails" />
  );
}

function FilterMissingScene({ accent }: { accent: KindStyle }) {
  const reads = [
    { seq: "ACGTTAGCCGTA", fail: false, note: "0 N" },
    { seq: "ACNNNAGNNGTA", fail: true, note: "5 N" },
    { seq: "ACGTNAGCCGTA", fail: false, note: "1 N" },
    { seq: "NNGTNAGNNNTA", fail: true, note: "6 N" },
  ];
  return <FilterScene reads={reads} accent={accent} reasonLabel="too many N (gray) fails" />;
}

function FilterRepeatsScene({ accent }: { accent: KindStyle }) {
  const reads = [
    { seq: "ACGTTAGCCGTA", fail: false },
    { seq: "AAAAAAAAACGT", fail: true, note: "homopolymer" },
    { seq: "ACGTTAGCCGTA", fail: false },
    { seq: "TTTTTTTTAGCC", fail: true, note: "homopolymer" },
  ];
  return (
    <FilterScene
      reads={reads}
      accent={accent}
      reasonLabel="long single-base runs = low complexity"
    />
  );
}

function SelectScene({ accent }: { accent: KindStyle }) {
  const reads = [
    { id: "A", keep: true },
    { id: "B", keep: false },
    { id: "A", keep: true },
    { id: "B", keep: false },
  ];
  const seq = "ACGTTAGCCGTA";
  const survivors = reads.filter((r) => r.keep);
  const rowFor = (id: string, dim: boolean) => (
    <>
      <Seq seq={seq} dim={dim} />
      <Chip
        x={seq.length * CELL_W + 8}
        y={1}
        text={`SAMPLE=${id}`}
        fill={id === "A" ? accent.color : MUTED}
      />
    </>
  );
  return (
    <Frame h={160}>
      <g transform="translate(24,36)">
        {reads.map((r, i) => (
          <g key={key()} transform={`translate(0, ${i * 26})`}>
            {rowFor(r.id, !r.keep)}
            {!r.keep && <XMark x={-12} y={CELL_H / 2} />}
          </g>
        ))}
        <text x={0} y={reads.length * 26 + 8} fontSize={9.5} fill={MUTED}>
          keep SAMPLE=A, drop the rest
        </text>
      </g>
      <Arrow y={70} />
      <g transform="translate(320,36)">
        {survivors.map((r, i) => (
          <g key={key()} transform={`translate(0, ${i * 26})`}>
            {rowFor(r.id, false)}
          </g>
        ))}
        <text x={0} y={survivors.length * 26 + 8} fontSize={9.5} fill={accent.text}>
          selected reads, unchanged
        </text>
      </g>
    </Frame>
  );
}

function SortScene({ accent }: { accent: KindStyle }) {
  const seq = "ACGTTAGCCGTA";
  const before = [3, 1, 2];
  const after = [1, 2, 3];
  const rowFor = (n: number) => (
    <>
      <Seq seq={seq} />
      <Chip x={seq.length * CELL_W + 8} y={1} text={`POS=${n}`} fill={accent.color} />
    </>
  );
  return (
    <Frame h={150}>
      <g transform="translate(24,36)">
        {before.map((n, i) => (
          <g key={key()} transform={`translate(0, ${i * 26})`}>
            {rowFor(n)}
          </g>
        ))}
        <text x={0} y={before.length * 26 + 8} fontSize={9.5} fill={MUTED}>
          unsorted
        </text>
      </g>
      <Arrow y={62} />
      <g transform="translate(320,36)">
        {after.map((n, i) => (
          <g key={key()} transform={`translate(0, ${i * 26})`}>
            {rowFor(n)}
          </g>
        ))}
        <text x={0} y={after.length * 26 + 8} fontSize={9.5} fill={accent.text}>
          same reads, reordered
        </text>
      </g>
    </Frame>
  );
}

function SampleScene({ accent }: { accent: KindStyle }) {
  const seq = "ACGTTAGCCGTA";
  const before = [true, true, true, true, true, true];
  const keptIdx = [0, 2, 4];
  return (
    <Frame h={188}>
      <g transform="translate(24,32)">
        {before.map((_, i) => (
          <g key={key()} transform={`translate(0, ${i * 22})`}>
            <Seq seq={seq} dim={!keptIdx.includes(i)} />
          </g>
        ))}
        <text x={0} y={before.length * 22 + 6} fontSize={9.5} fill={MUTED}>
          6 reads
        </text>
      </g>
      <Arrow y={86} />
      <g transform="translate(320,58)">
        {keptIdx.map((_, i) => (
          <g key={key()} transform={`translate(0, ${i * 22})`}>
            <Seq seq={seq} />
          </g>
        ))}
        <Chip x={0} y={keptIdx.length * 22 + 2} text="random subset (n=3)" fill={accent.color} />
      </g>
      <Caption text="A random subset is kept; kept reads are unchanged." y={172} />
    </Frame>
  );
}

function FileBox({
  x,
  y,
  label,
  count,
  accent,
}: {
  x: number;
  y: number;
  label: string;
  count: number;
  accent: KindStyle;
}) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect width={120} height={28 + count * 12} rx={6} fill={accent.tint} stroke={accent.border} />
      <text x={8} y={16} fontSize={9.5} fontWeight={600} fill={accent.text}>
        {label}
      </text>
      {Array.from({ length: count }).map((_, i) => (
        <rect
          key={key()}
          x={8}
          y={22 + i * 12}
          width={104}
          height={7}
          rx={2}
          fill={accent.color}
          opacity={0.65}
        />
      ))}
    </g>
  );
}

function SplitCountScene({ accent }: { accent: KindStyle }) {
  return (
    <Frame h={170}>
      <g transform="translate(24,40)">
        <FileBox x={0} y={0} label="reads.fastq (5)" count={5} accent={accent} />
      </g>
      <Arrow y={70} />
      <g transform="translate(320,34)">
        <FileBox x={0} y={0} label="part_1 (≤3)" count={3} accent={accent} />
        <FileBox x={0} y={70} label="part_2 (≤3)" count={2} accent={accent} />
      </g>
      <Caption text="One file → several parts; reads are unchanged." y={156} />
    </Frame>
  );
}

function SplitGroupScene({ accent }: { accent: KindStyle }) {
  return (
    <Frame h={176}>
      <g transform="translate(24,42)">
        <FileBox x={0} y={0} label="mixed (A,B,A,B)" count={4} accent={accent} />
      </g>
      <Arrow y={70} />
      <g transform="translate(320,34)">
        <FileBox x={0} y={0} label="SAMPLE=A" count={2} accent={accent} />
        <FileBox x={0} y={62} label="SAMPLE=B" count={2} accent={accent} />
      </g>
      <Caption text="Reads routed to files by annotation value." y={162} />
    </Frame>
  );
}

function TableScene({ accent }: { accent: KindStyle }) {
  const seq = "ACGTTAGCCGTA";
  const rows = [
    ["SEQ1", "ACGT", "VH"],
    ["SEQ2", "TTGC", "VK"],
    ["SEQ3", "GGAA", "VH"],
  ];
  const colW = [44, 44, 34];
  const colX = [0, 44, 88];
  return (
    <Frame h={160}>
      <g transform="translate(24,34)">
        {[0, 1, 2].map((i) => (
          <g key={key()} transform={`translate(0, ${i * 24})`}>
            <Seq seq={seq} />
          </g>
        ))}
        <text x={0} y={84} fontSize={9.5} fill={MUTED}>
          reads with annotations
        </text>
      </g>
      <Arrow y={60} />
      <g transform="translate(320,30)">
        {/* header row */}
        {["ID", "UMI", "PRIMER"].map((h, c) => (
          <g key={key()} transform={`translate(${colX[c]}, 0)`}>
            <rect width={colW[c]} height={18} fill={accent.color} />
            <text
              x={colW[c] / 2}
              y={12.5}
              textAnchor="middle"
              fontSize={8.5}
              fill="#fff"
              fontFamily="ui-monospace, monospace"
            >
              {h}
            </text>
          </g>
        ))}
        {rows.map((r, ri) => (
          <g key={key()} transform={`translate(0, ${18 + ri * 16})`}>
            {r.map((cell, c) => (
              <g key={key()} transform={`translate(${colX[c]}, 0)`}>
                <rect width={colW[c]} height={16} fill="#fff" stroke={STROKE} />
                <text
                  x={colW[c] / 2}
                  y={11}
                  textAnchor="middle"
                  fontSize={8}
                  fill="rgba(15,23,42,0.8)"
                  fontFamily="ui-monospace, monospace"
                >
                  {cell}
                </text>
              </g>
            ))}
          </g>
        ))}
        <text x={0} y={18 + rows.length * 16 + 14} fontSize={9.5} fill={MUTED}>
          TSV table (.tab)
        </text>
      </g>
      <Caption text="Annotations are read out to a table — reads aren't edited." y={148} />
    </Frame>
  );
}

export function StepVisual({ kind, accent, headerBefore, headerAfter }: StepVisualProps) {
  switch (kind) {
    case "trim":
      return <TrimScene />;
    case "mask":
      return <MaskScene />;
    case "primer":
      return <PrimerScene accent={accent} />;
    case "collapse":
      return <CollapseScene accent={accent} />;
    case "consensus":
      return <ConsensusScene accent={accent} />;
    case "pair":
      return <PairScene accent={accent} />;
    case "assemble":
      return <AssembleScene accent={accent} />;
    case "header":
      return <HeaderScene accent={accent} headerBefore={headerBefore} headerAfter={headerAfter} />;
    case "filter-length":
      return <FilterLengthScene accent={accent} />;
    case "filter-quality":
      return <FilterQualityScene accent={accent} />;
    case "filter-missing":
      return <FilterMissingScene accent={accent} />;
    case "filter-repeats":
      return <FilterRepeatsScene accent={accent} />;
    case "select":
      return <SelectScene accent={accent} />;
    case "sort":
      return <SortScene accent={accent} />;
    case "sample":
      return <SampleScene accent={accent} />;
    case "split-count":
      return <SplitCountScene accent={accent} />;
    case "split-group":
      return <SplitGroupScene accent={accent} />;
    case "table":
      return <TableScene accent={accent} />;
    default:
      return null;
  }
}
