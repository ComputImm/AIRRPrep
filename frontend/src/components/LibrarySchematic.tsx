type Variant = "umi" | "nonumi" | "race";

type Block = {
  label: string;
  flex: number;
  color: string;
  bp?: string;
  textColor?: string;
};

const PALETTE = {
  umi: "oklch(0.72 0.13 290)",
  vprimer: "oklch(0.68 0.12 195)",
  cprimer: "oklch(0.68 0.13 230)",
  vdj: "oklch(0.78 0.11 160)",
  leader: "oklch(0.82 0.08 100)",
  tss: "oklch(0.72 0.12 30)",
  internalC: "oklch(0.62 0.12 260)",
  read1: "oklch(0.55 0.13 230)",
  read2: "oklch(0.58 0.12 195)",
};

const ANNOTATION = "oklch(0.45 0.03 250)";

function Construct({ blocks }: { blocks: Block[] }) {
  return (
    <div className="flex flex-col gap-1 w-full">
      <div className="flex h-7 w-full overflow-hidden rounded-md ring-1 ring-border/60">
        {blocks.map((b, i) => (
          <div
            key={i}
            className="flex items-center justify-center text-[9px] font-medium tracking-tight"
            style={{
              flex: b.flex,
              backgroundColor: b.color,
              color: b.textColor ?? "oklch(0.25 0.04 250)",
            }}
            title={b.label}
          >
            <span className="truncate px-1">{b.label}</span>
          </div>
        ))}
      </div>
      <div className="flex w-full">
        {blocks.map((b, i) => (
          <div
            key={i}
            className="flex justify-center text-[8px] font-medium leading-none"
            style={{ flex: b.flex, color: ANNOTATION }}
          >
            <span className="truncate">{b.bp ?? ""}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReadBar({
  label,
  bp,
  side,
  widthPct,
  color,
}: {
  label: string;
  bp?: string;
  side: "left" | "right";
  widthPct: number;
  color: string;
}) {
  return (
    <div className="relative h-4 w-full">
      <div
        className="absolute top-1/2 flex h-[14px] -translate-y-1/2 items-center justify-between rounded-sm px-1.5"
        style={{ width: `${widthPct}%`, [side]: 0, backgroundColor: color }}
      >
        <span
          className="truncate text-[9px] font-semibold tracking-tight"
          style={{ color: "oklch(0.99 0.005 220)" }}
        >
          {side === "left" ? label : bp ?? ""}
        </span>
        {bp && (
          <span
            className="truncate text-[9px] font-semibold tracking-tight"
            style={{ color: "oklch(0.99 0.005 220)" }}
          >
            {side === "left" ? bp : label}
          </span>
        )}
      </div>
    </div>
  );
}

export function LibrarySchematic({ variant }: { variant: Variant }) {
  if (variant === "umi") {
    const blocks: Block[] = [
      { label: "V-primer", flex: 1.1, color: PALETTE.vprimer, bp: "20–22 bp" },
      { label: "V(D)J", flex: 3, color: PALETTE.vdj, bp: "224–230 bp" },
      { label: "C-primer", flex: 1, color: PALETTE.cprimer, bp: "18 bp" },
      { label: "UMI", flex: 0.8, color: PALETTE.umi, bp: "15 bp" },
    ];
    return (
      <div className="flex w-full flex-col gap-1.5">
        <ReadBar label="Read 1" bp="250 bp" side="left" widthPct={62} color={PALETTE.read1} />
        <Construct blocks={blocks} />
        <ReadBar label="Read 2" bp="250 bp" side="right" widthPct={62} color={PALETTE.read2} />
      </div>
    );
  }

  if (variant === "nonumi") {
    const blocks: Block[] = [
      { label: "5′", flex: 0.4, color: PALETTE.leader, bp: "4 bp" },
      { label: "V-primer", flex: 1.2, color: PALETTE.vprimer, bp: "20–22 bp" },
      { label: "V(D)J", flex: 3.2, color: PALETTE.vdj, bp: "224–226 bp" },
      { label: "C-primer", flex: 1.1, color: PALETTE.cprimer, bp: "20 bp" },
      { label: "3′", flex: 0.4, color: PALETTE.leader, bp: "4 bp" },
    ];
    return (
      <div className="flex w-full flex-col gap-1.5">
        <ReadBar label="Read 1" bp="250 bp" side="left" widthPct={62} color={PALETTE.read1} />
        <Construct blocks={blocks} />
        <ReadBar label="Read 2" bp="250 bp" side="right" widthPct={62} color={PALETTE.read2} />
      </div>
    );
  }

  const blocks: Block[] = [
    { label: "UMI", flex: 0.9, color: PALETTE.umi, bp: "17 bp" },
    { label: "TSS", flex: 0.9, color: PALETTE.tss, bp: "6–10 bp" },
    { label: "Leader", flex: 1, color: PALETTE.leader, bp: "—" },
    { label: "V(D)J", flex: 2.8, color: PALETTE.vdj, bp: "248–252 bp" },
    { label: "C-primer", flex: 1.1, color: PALETTE.cprimer, bp: "18–22 bp" },
    { label: "Int. C", flex: 1, color: PALETTE.internalC, bp: "303–307 bp", textColor: "oklch(0.98 0 0)" },
  ];
  return (
    <div className="flex w-full flex-col gap-1.5">
      <ReadBar label="Read 1" bp="325 bp" side="left" widthPct={72} color={PALETTE.read1} />
      <Construct blocks={blocks} />
      <ReadBar label="Read 2" bp="275 bp" side="right" widthPct={58} color={PALETTE.read2} />
    </div>
  );
}
