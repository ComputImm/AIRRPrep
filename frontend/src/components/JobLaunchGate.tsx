import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Loader2,
  Mail,
  ShieldCheck,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { readApiError } from "@/api/jobs";
import { CaptchaField, type CaptchaHandle } from "@/components/CaptchaField";
import {
  formatDuration,
  requestEmailCode,
  verifyEmailCode,
  type JobEstimate,
} from "@/api/notifications";

/**
 * The dialog that opens when a run is too long to sit and watch: it explains
 * the estimate, takes an email address, and walks the user through the
 * 6-digit code. On success it calls `onVerified`, and the caller starts the
 * job exactly as it would have without the gate.
 */
export function JobLaunchGate({
  open,
  estimate,
  onOpenChange,
  onVerified,
}: {
  open: boolean;
  estimate: JobEstimate | null;
  onOpenChange: (open: boolean) => void;
  /** Called once the address is verified; should start the job. */
  onVerified: () => void | Promise<void>;
}) {
  const [stage, setStage] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const codeRef = useRef<HTMLInputElement>(null);

  const [captchaId, setCaptchaId] = useState<string | null>(null);
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const captchaRef = useRef<CaptchaHandle>(null);

  // Each opening is a fresh attempt — a stale half-entered code from a
  // previous run would just produce a confusing error.
  useEffect(() => {
    if (open) {
      setStage("email");
      setCode("");
      setError(null);
      setBusy(false);
      setCaptchaAnswer("");
      // The dialog's content is *not* remounted between openings, so
      // CaptchaField's mount fetch does not run again — without this, the
      // second opening would show an image the server has already consumed.
      captchaRef.current?.refresh();
    }
  }, [open]);

  useEffect(() => {
    if (stage === "code") codeRef.current?.focus();
  }, [stage]);

  const handleSendCode = async () => {
    setBusy(true);
    setError(null);
    try {
      await requestEmailCode(email, {
        captcha_id: captchaId,
        captcha_answer: captchaAnswer,
      });
      setStage("code");
    } catch (e) {
      setError(readApiError(e));
      // The server consumes the challenge whether or not the answer was
      // right, so the image on screen is spent either way.
      captchaRef.current?.refresh();
    } finally {
      setBusy(false);
    }
  };

  const handleVerify = async () => {
    setBusy(true);
    setError(null);
    try {
      await verifyEmailCode(email, code);
      await onVerified();
      onOpenChange(false);
    } catch (e) {
      setError(readApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const handleResend = () => {
    // Resending needs a fresh challenge — the one solved to send the first
    // code was consumed by that request. Bounce back to the email stage,
    // where the field lives, rather than duplicating it here.
    setStage("email");
    setError("Confirm the characters again to send a new code.");
    setCode("");
    captchaRef.current?.refresh();
  };

  const emailLooksValid = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(email.trim());
  const codeComplete = /^\d{6}$/.test(code);
  const canSendCode = emailLooksValid && captchaAnswer.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mail className="h-4 w-4 text-primary" />
            {stage === "email"
              ? "This run needs an email address"
              : "Enter your verification code"}
          </DialogTitle>
          <DialogDescription>
            {stage === "email"
              ? "We will email you a tracking code when it starts, and a link to your results when it finishes."
              : `We sent a 6-digit code to ${email}. It expires in 15 minutes.`}
          </DialogDescription>
        </DialogHeader>

        {stage === "email" ? (
          <div className="flex flex-col gap-4">
            {estimate && <EstimateSummary estimate={estimate} />}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="notify-email">Email address</Label>
              <Input
                id="notify-email"
                type="email"
                autoComplete="email"
                placeholder="you@lab.example.edu"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && canSendCode && !busy) {
                    handleSendCode();
                  }
                }}
              />
              <p className="text-xs text-muted-foreground">
                Used only to notify you about this run.
              </p>
            </div>

            <CaptchaField
              ref={captchaRef}
              value={captchaAnswer}
              onChange={setCaptchaAnswer}
              onIdChange={setCaptchaId}
              onSubmit={() => {
                if (canSendCode && !busy) handleSendCode();
              }}
            />
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="notify-code">6-digit code</Label>
              <Input
                id="notify-code"
                ref={codeRef}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="000000"
                value={code}
                onChange={(e) =>
                  setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" && codeComplete && !busy) handleVerify();
                }}
                className="text-center text-lg font-semibold tracking-[0.4em]"
              />
            </div>

            <button
              type="button"
              onClick={handleResend}
              disabled={busy}
              className="self-start text-xs font-medium text-primary transition-colors hover:underline disabled:opacity-50"
            >
              Send a new code
            </button>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-2">
          {stage === "code" && (
            <Button
              variant="ghost"
              onClick={() => {
                setStage("email");
                setError(null);
              }}
              disabled={busy}
              className="gap-1.5 sm:mr-auto"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Change address
            </Button>
          )}

          {stage === "email" ? (
            <Button
              onClick={handleSendCode}
              disabled={!canSendCode || busy}
              className="gap-2"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Mail className="h-4 w-4" />
              )}
              {busy ? "Sending…" : "Send code"}
            </Button>
          ) : (
            <Button
              onClick={handleVerify}
              disabled={!codeComplete || busy}
              className="gap-2"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {busy ? "Verifying…" : "Verify and start"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The "why are you asking me this" panel. */
function EstimateSummary({ estimate }: { estimate: JobEstimate }) {
  return (
    <div className="rounded-xl border border-border bg-muted/40 p-4">
      <div className="flex items-center gap-2">
        <Clock className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold text-foreground">
          Estimated runtime: {formatDuration(estimate.estimated_seconds)}
        </span>
      </div>
      {estimate.reasons.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {estimate.reasons.map((reason) => (
            <li
              key={reason}
              className="flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground"
            >
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
              {/* Capitalised here rather than in the backend copy so the
                  same phrases read correctly mid-sentence elsewhere. */}
              {reason.charAt(0).toUpperCase() + reason.slice(1)}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
        Estimates are rough — the real time depends on your data and how busy
        the server is.
      </p>
    </div>
  );
}

/**
 * The tracking code, shown beside the progress panel once a notified run has
 * started. The same code is in the user's inbox; having it on screen means
 * they can note it down before closing the tab.
 */
export function TrackingCodeCard({
  trackingCode,
  email,
  className,
}: {
  trackingCode: string;
  email?: string | null;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-primary/30 bg-primary/5 p-4",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 text-primary" />
        <span className="text-xs font-semibold uppercase tracking-wide text-primary">
          Tracking code
        </span>
      </div>
      <p className="mt-2 text-center text-2xl font-bold tracking-[0.3em] tabular-nums text-foreground">
        {trackingCode}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        You can close this page. We will email{" "}
        {email ? <span className="font-medium">{email}</span> : "you"} when the
        run finishes. To come back, open{" "}
        <span className="font-medium text-foreground">/track</span> and enter
        this code with that address.
      </p>
    </div>
  );
}
