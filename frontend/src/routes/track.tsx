import { createFileRoute, useLocation } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, Search } from "lucide-react";
import { AppHeader } from "@/components/AppHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { adoptSession } from "@/api/session";
import { readApiError } from "@/api/jobs";
import { resumeFromTrackingCode } from "@/api/notifications";
import { CaptchaField, type CaptchaHandle } from "@/components/CaptchaField";

/**
 * Recovery page: tracking code + email address in, the user's own run out.
 *
 * The emails link here with `?code=` prefilled but never the address — the
 * two together are what unlock a run, so putting both in a URL would defeat
 * requiring both. The address is the one thing the recipient already knows.
 */
/**
 * No `validateSearch` here on purpose. The router JSON-parses search values,
 * so an all-digit `?code=987654` arrives as a number and a declared string
 * schema round-trips it back out as `?code="987654"` — with a redirect on
 * every emailed link. Reading the raw value below sidesteps both.
 */
export const Route = createFileRoute("/track")({
  head: () => ({
    meta: [
      { title: "Find a run — AIRR Preprocessor" },
      {
        name: "description",
        content:
          "Return to a preprocessing run using the tracking code from your email.",
      },
    ],
  }),
  component: TrackPage,
});

function TrackPage() {
  const codeFromLink = useLocation({
    select: (location) => {
      const value = (location.search as Record<string, unknown> | undefined)
        ?.code;
      return value === undefined || value === null ? "" : String(value);
    },
  });

  const [code, setCode] = useState(codeFromLink);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  const [captchaId, setCaptchaId] = useState<string | null>(null);
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const captchaRef = useRef<CaptchaHandle>(null);

  // Arriving from an email link, the code is already filled in — put the
  // cursor where the one remaining piece of information goes.
  useEffect(() => {
    if (codeFromLink) emailRef.current?.focus();
  }, [codeFromLink]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await resumeFromTrackingCode(code, email, {
        captcha_id: captchaId,
        captcha_answer: captchaAnswer,
      });

      // Adopting the recovered session is what makes the destination page
      // behave exactly as it did for whoever started the run: every status
      // poll and download link reads the session from storage.
      adoptSession(result.session_id, result.session_token);

      // A hard navigation rather than router.navigate(): the destination
      // comes from the server as a plain string, so it is outside the
      // router's typed route union, and a recovered run wants a clean mount
      // against the session that was just adopted anyway.
      window.location.assign(
        `${result.route}?job=${encodeURIComponent(result.job_id)}`,
      );
    } catch (e) {
      setError(readApiError(e));
      // Spent on the attempt, right or wrong — get a new one.
      captchaRef.current?.refresh();
      setBusy(false);
    }
  };

  const ready =
    /^\d{4,10}$/.test(code.trim()) &&
    email.trim().length > 3 &&
    captchaAnswer.trim().length > 0;

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto max-w-md px-6 py-16">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Find your run
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Enter the tracking code we emailed you, along with the address it
            was sent to. You will be taken straight back to your run.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="mt-8 flex flex-col gap-5 rounded-2xl border border-border bg-card p-6"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="track-code">Tracking code</Label>
            <Input
              id="track-code"
              inputMode="numeric"
              autoComplete="off"
              maxLength={10}
              placeholder="000000"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              className="text-center text-lg font-semibold tracking-[0.4em]"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="track-email">Email address</Label>
            <Input
              id="track-email"
              ref={emailRef}
              type="email"
              autoComplete="email"
              placeholder="you@lab.example.edu"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              The address the tracking code was sent to.
            </p>
          </div>

          <CaptchaField
            ref={captchaRef}
            value={captchaAnswer}
            onChange={setCaptchaAnswer}
            onIdChange={setCaptchaId}
          />

          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button type="submit" disabled={!ready || busy} className="gap-2">
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            {busy ? "Looking up…" : "Open my run"}
          </Button>
        </form>

        <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
          Runs and their results are kept for 7 days. After that the tracking
          code stops working and the files are gone.
        </p>
      </main>
    </div>
  );
}
