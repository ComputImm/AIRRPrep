import { Link, useLocation } from "@tanstack/react-router";
import { Dna } from "lucide-react";

export function AppHeader() {
  const pathname = useLocation({ select: (l) => l.pathname });

  const docsHref = pathname.startsWith("/single-cell")
    ? "/documentation-single-cell"
    : pathname.startsWith("/bulk") || pathname.startsWith("/pipeline")
      ? "/documentation-bulk"
      : "/documentation";

  return (
    <header className="border-b border-border/60 bg-card/70 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/20">
            <Dna className="h-5 w-5" />
          </div>

          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold tracking-tight text-foreground">
              AIRR Preprocessor
            </span>
            <span className="text-[11px] text-muted-foreground">
              Immune repertoire data platform
            </span>
          </div>
        </Link>

        <nav className="flex items-center gap-3 text-xs text-muted-foreground sm:gap-6 sm:text-sm">
          <Link
            to={docsHref}
            className="whitespace-nowrap transition-colors hover:text-foreground [&.active]:font-medium [&.active]:text-foreground"
          >
            Documentation
          </Link>

          {/* Reachable without the emailed link, for anyone who has the
              tracking code but not the message it came in. */}
          <Link
            to="/track"
            className="whitespace-nowrap transition-colors hover:text-foreground [&.active]:font-medium [&.active]:text-foreground"
          >
            Find a run
          </Link>

          <span className="cursor-pointer whitespace-nowrap transition-colors hover:text-foreground">
            <Link to="https://computimm.com/"             className="whitespace-nowrap transition-colors hover:text-foreground [&.active]:font-medium [&.active]:text-foreground"
>
            About
            </Link>
          </span>
        </nav>
      </div>
    </header>
  );
}