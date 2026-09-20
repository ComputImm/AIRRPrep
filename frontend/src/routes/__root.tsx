import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";

import appCss from "../styles.css?url";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "AIRR Preprocessor" },
      { name: "description", content: "AIRR Preprocessor prepares immune receptor repertoire sequencing data for analysis via guided workflows." },
      { name: "author", content: "AIRR Preprocessor" },
      { property: "og:title", content: "AIRR Preprocessor" },
      { property: "og:description", content: "AIRR Preprocessor prepares immune receptor repertoire sequencing data for analysis via guided workflows." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "twitter:site", content: "@Lovable" },
      { name: "twitter:title", content: "AIRR Preprocessor" },
      { name: "twitter:description", content: "AIRR Preprocessor prepares immune receptor repertoire sequencing data for analysis via guided workflows." },
      { property: "og:image", content: "https://pub-bb2e103a32db4e198524a2e9ed8f35b4.r2.dev/6fa999e9-3027-4c4e-9858-63da8bf4750a/id-preview-bc058212--9df5caa2-8c76-40f9-92a1-a1100ec12cb1.lovable.app-1779552908292.png" },
      { name: "twitter:image", content: "https://pub-bb2e103a32db4e198524a2e9ed8f35b4.r2.dev/6fa999e9-3027-4c4e-9858-63da8bf4750a/id-preview-bc058212--9df5caa2-8c76-40f9-92a1-a1100ec12cb1.lovable.app-1779552908292.png" },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
      // A DNA helix narrowing into a funnel (public/favicon.svg): the two
      // reads going in, the filtered repertoire coming out. `sizes="any"`
      // tells browsers the SVG scales, so they prefer it over a bitmap.
      { rel: "icon", type: "image/svg+xml", href: "/favicon.svg", sizes: "any" },
      { rel: "apple-touch-icon", href: "/favicon.svg" },
      { rel: "mask-icon", href: "/favicon.svg", color: "#2563eb" },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}
import { useEffect } from "react";
import { getSessionId } from "@/api/session";

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  useEffect(() => {
    getSessionId().catch(console.error);
  }, []);


  return (
    <QueryClientProvider client={queryClient}>
      <Outlet />
    </QueryClientProvider>
  );
}
