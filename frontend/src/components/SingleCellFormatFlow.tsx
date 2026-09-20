/**
 * Vertical flow diagram for the single-cell docs + the single-cell page's
 * "how it works" panel. Unlike bulk's flowcharts (which show a chain of
 * pRESTO steps), a single-cell format is: one or two input files -> an
 * adapter that extracts + strips annotation fields -> one unified record ->
 * one or two output files. This renders that shape schematically:
 *
 *   [input box(es)]  (converge arrow if 2)
 *         |
 *   [processing box(es), stacked]
 *         |
 *   [output box(es)]  (diverge arrow if 2)
 */

import { useRef, useState } from "react";
import { toPng } from "html-to-image";
import { KIND_STYLE, type StepKind } from "@/lib/stepColors";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Download, Loader2 } from "lucide-react";

export interface FlowBox {
  label: string;
  sub?: string;
}

export interface FormatFlowSpec {
  kind: StepKind;
  inputs: FlowBox[];
  steps: FlowBox[];
  outputs: FlowBox[];
  warning?: string;
}

function Box({
  box,
  kind,
  variant = "step",
}: {
  box: FlowBox;
  kind: StepKind;
  variant?: "io" | "step";
}) {
  const style = KIND_STYLE[kind];
  return (
    <div
      className={cn(
        "w-full max-w-[15rem] rounded-xl border-2 px-3 py-2.5 text-center",
        variant === "io" && "bg-muted/60 border-border",
      )}
      style={
        variant === "step"
          ? { borderColor: style.border, background: style.tint, color: style.text }
          : undefined
      }
    >
      <div
        className={cn(
          "font-semibold leading-tight break-words",
          variant === "io" ? "text-xs" : "text-sm",
        )}
      >
        {box.label}
      </div>
      {box.sub && (
        <div
          className={cn(
            "text-[11px] leading-tight",
            variant === "io" ? "text-muted-foreground" : "opacity-75",
          )}
        >
          {box.sub}
        </div>
      )}
    </div>
  );
}

function VerticalArrow() {
  return (
    <div className="flex flex-col items-center">
      <div className="h-4 w-px bg-border" />
      <div className="h-0 w-0 border-l-[4px] border-r-[4px] border-t-[5px] border-l-transparent border-r-transparent border-t-border" />
    </div>
  );
}

/** Converge (2 boxes -> 1 point) or diverge (1 point -> 2 boxes) connector. */
function ConvergeConnector({ direction }: { direction: "in" | "out" }) {
  const stroke = "oklch(0.6 0.02 250)";
  const d =
    direction === "in"
      ? "M 50 0 Q 50 24 100 26 M 150 0 Q 150 24 100 26"
      : "M 100 0 Q 100 24 50 26 M 100 0 Q 100 24 150 26";
  return (
    <svg viewBox="0 0 200 32" className="my-1 h-7 w-full max-w-[22rem]" aria-hidden>
      <path d={d} stroke={stroke} strokeWidth={1.75} fill="none" />
    </svg>
  );
}

function BoxRow({
  boxes,
  kind,
  variant,
}: {
  boxes: FlowBox[];
  kind: StepKind;
  variant: "io" | "step";
}) {
  if (boxes.length <= 1) {
    return (
      <div className="flex w-full justify-center">
        {boxes.map((b, i) => (
          <Box key={i} box={b} kind={kind} variant={variant} />
        ))}
      </div>
    );
  }
  return (
    <div className="grid w-full max-w-[22rem] grid-cols-2 gap-3">
      {boxes.map((b, i) => (
        <Box key={i} box={b} kind={kind} variant={variant} />
      ))}
    </div>
  );
}

export function SingleCellFormatFlow({ 
  spec,
  showDownload = true,
  className,
}: { 
  spec: FormatFlowSpec;
  showDownload?: boolean;
  className?: string;
}) {
  const flowRef = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (!flowRef.current) return;
    setDownloading(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 150));
      const dataUrl = await toPng(flowRef.current, {
        pixelRatio: 2.5,
        backgroundColor: "#ffffff",
        cacheBust: true,
      });
      const a = document.createElement("a");
      a.download = `single-cell-flow-${new Date().toISOString().slice(0, 10)}.png`;
      a.href = dataUrl;
      a.click();
    } catch (e) {
      console.error("Download single-cell flow chart failed", e);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className={cn("relative", className)}>
      {showDownload && (
        <div className="mb-3 flex justify-end">
          <Button
            size="sm"
            variant="ghost"
            onClick={handleDownload}
            disabled={downloading}
            className="h-7 gap-1 px-2 text-xs"
            title="Download single-cell flow chart as PNG"
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
      <div ref={flowRef} className="flex flex-col items-center gap-1">
        <BoxRow boxes={spec.inputs} kind={spec.kind} variant="io" />
        {spec.inputs.length > 1 ? (
          <ConvergeConnector direction="in" />
        ) : (
          <VerticalArrow />
        )}

        {spec.steps.map((step, i) => (
          <div key={i} className="flex w-full flex-col items-center gap-1">
            <Box box={step} kind={spec.kind} variant="step" />
            <VerticalArrow />
          </div>
        ))}

        {spec.outputs.length > 1 ? (
          <ConvergeConnector direction="out" />
        ) : null}
        <BoxRow boxes={spec.outputs} kind={spec.kind} variant="io" />

        {spec.warning && (
          <p className="mt-3 max-w-xs rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-center text-xs leading-relaxed text-amber-700">
            {spec.warning}
          </p>
        )}
      </div>
    </div>
  );
}