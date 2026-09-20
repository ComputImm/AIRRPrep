import { useCallback, useEffect, useImperativeHandle, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getCaptcha, type Captcha } from "@/api/captcha";

/**
 * The anti-bot challenge: an image of five characters plus a box to type
 * them into.
 *
 * The parent owns the answer (it has to travel with the parent's own
 * request), and holds a ref so it can force a fresh image — a challenge is
 * consumed by the server on any verification attempt, right or wrong, so
 * after a rejected submit the old image is already dead and must be
 * replaced.
 */
export interface CaptchaHandle {
  /** Discard the current challenge and load a new one. */
  refresh: () => void;
}

export function CaptchaField({
  value,
  onChange,
  onIdChange,
  onSubmit,
  ref,
}: {
  value: string;
  onChange: (answer: string) => void;
  /** Receives the id that must accompany the answer. */
  onIdChange: (captchaId: string | null) => void;
  /** Called on Enter, so the field behaves like the rest of the form. */
  onSubmit?: () => void;
  ref?: React.Ref<CaptchaHandle>;
}) {
  const [captcha, setCaptcha] = useState<Captcha | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    onChange("");
    try {
      const next = await getCaptcha();
      setCaptcha(next);
      onIdChange(next.captcha_id);
    } catch {
      setCaptcha(null);
      onIdChange(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [onChange, onIdChange]);

  useEffect(() => {
    load();
    // Once on mount. `load` changes identity with its callback props, and
    // re-running on that would fetch a new image mid-typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useImperativeHandle(ref, () => ({ refresh: load }), [load]);

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="captcha-answer">Type the characters shown</Label>
      <div className="flex items-center gap-2">
        <div className="flex h-14 w-40 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : captcha ? (
            <img
              src={captcha.image}
              alt="Characters to type"
              className="h-full w-full"
            />
          ) : (
            <span className="px-2 text-center text-[10px] text-muted-foreground">
              Could not load
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={load}
          disabled={loading}
          title="Show different characters"
          aria-label="Show different characters"
          className="rounded-md border border-border p-2 text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>

        <Input
          id="captcha-answer"
          autoComplete="off"
          spellCheck={false}
          maxLength={8}
          placeholder="ABCDE"
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          onKeyDown={(e) => {
            if (e.key === "Enter" && onSubmit) {
              e.preventDefault();
              onSubmit();
            }
          }}
          className="uppercase tracking-widest"
        />
      </div>
      {failed && (
        <p className="text-xs text-destructive">
          The anti-bot check could not be loaded. Check your connection and use
          the refresh button.
        </p>
      )}
    </div>
  );
}
