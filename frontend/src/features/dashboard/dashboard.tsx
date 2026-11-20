import { useTranslation } from "react-i18next";
import type { User } from "#/client/types.gen.ts";
import { CollectionHealth } from "./collection-health.tsx";
import { NextRuns } from "./next-runs.tsx";
import { Pipeline } from "./pipeline.tsx";

// Today as a full date in the browser's time zone, over the heading (as Jobber's home has it).
function Today() {
  const { i18n } = useTranslation();
  const now = new Date();
  const day = [now.getFullYear(), now.getMonth() + 1, now.getDate()]
    .map((part) => String(part).padStart(2, "0"))
    .join("-");
  return (
    <p className="text-muted-foreground text-sm">
      <time dateTime={day}>
        {new Intl.DateTimeFormat(i18n.language, { dateStyle: "full" }).format(now)}
      </time>
    </p>
  );
}

// Where InfraSales stands (CONTEXT.md): the stages of its work across the top, then cards that
// summarise and lead onward, as Cloudflare's account home. Everyone sees it; the stages and cards
// on admin pages (Feeds, Sources, Source Collection's health) are left out for viewers, who
// may not open those pages.
export function Dashboard({ user }: { user: User }) {
  const { t } = useTranslation();
  const admin = user.role === "admin";
  return (
    <div className="grid gap-6">
      <hgroup className="grid gap-1">
        <Today />
        <h1 className="font-heading font-semibold text-2xl tracking-tight">
          {t("dashboard.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("dashboard.description")}</p>
      </hgroup>
      {admin ? <Pipeline /> : null}
      <div className="grid gap-4 lg:grid-cols-3">
        {admin ? <CollectionHealth className="lg:col-span-2" /> : null}
        <NextRuns admin={admin} />
      </div>
    </div>
  );
}
