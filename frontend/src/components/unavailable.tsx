import { useRouter } from "@tanstack/react-router";
import { RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CentredScreen } from "#/components/centred-screen.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Button } from "#/components/ui/button.tsx";

// A whole page could not load: the empty-state pattern (a title and one line), announced, and
// Try again below it. Trying again reloads the page's routes, asking again for what failed.
function Outage() {
  const { t } = useTranslation();
  const router = useRouter();
  return (
    <div className="grid w-full justify-items-center gap-2 rounded-xl border bg-card pb-8">
      <div role="alert" className="w-full text-foreground">
        <EmptyState
          title={t("app.outage.title")}
          description={t("app.outage.description")}
          className="pb-2"
        />
      </div>
      <Button variant="outline" onClick={() => router.invalidate()}>
        <RotateCw aria-hidden={true} data-icon="inline-start" />
        {t("app.retry")}
      </Button>
    </div>
  );
}

// The service did not answer: say so, and offer to try again in place.
export function Unavailable({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <p role="alert" className="flex flex-wrap items-center gap-x-2 text-sm">
      {t("app.unavailable")}
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RotateCw aria-hidden={true} data-icon="inline-start" />
        {t("app.retry")}
      </Button>
    </p>
  );
}

// A page inside the app shell could not load its data. The shell holds the page's <main>
// already, so this is the outage notice alone.
export function PageError() {
  return <Outage />;
}

// The router's error screen, outside the shell: a page could not load (the session check failed).
export function RouteError() {
  return (
    <CentredScreen>
      <div className="w-full max-w-sm">
        <Outage />
      </div>
    </CentredScreen>
  );
}

// Shown while a page loads for longer than a moment.
export function Loading() {
  const { t } = useTranslation();
  return <p role="status">{t("app.loading")}</p>;
}
