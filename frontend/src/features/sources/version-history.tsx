import { Link } from "@tanstack/react-router";
import { cn } from "cn";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { VersionRead } from "#/client/types.gen.ts";
import { Badge } from "#/components/ui/badge.tsx";

interface Props {
  sourceId: string;
  versions: VersionRead[]; // newest first
  shown: number; // the version on the page
  view: "text" | "changes";
}

// Versions by day, as GitBook's version history groups them: "Oct 17, 2026" → its versions.
function byDay(versions: VersionRead[], day: Intl.DateTimeFormat) {
  const days = new Map<string, VersionRead[]>();
  for (const version of versions) {
    const key = day.format(new Date(version.fetched_at));
    days.set(key, [...(days.get(key) ?? []), version]);
  }
  return [...days];
}

// Every version of a Source, newest first and grouped by day, each one a link to it (the open
// one marked as current): one click shows what the page said then, or what changed then.
export function VersionHistory({ sourceId, versions, shown, view }: Props) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const day = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  const time = new Intl.DateTimeFormat(i18n.language, { timeStyle: "short" });
  const latest = versions[0]?.number;

  return (
    <section
      aria-labelledby={id}
      className="grid content-start gap-3 rounded-lg border bg-card p-4"
    >
      <h2 id={id} className="font-heading font-medium">
        {t("sources.history.title")}
      </h2>
      <ul aria-label={t("sources.history.label")} className="grid gap-3">
        {byDay(versions, day).map(([date, ofDay]) => (
          <li key={date} className="grid gap-1">
            <p className="text-muted-foreground text-xs">{date}</p>
            <ol className="grid gap-1">
              {ofDay.map((version) => {
                const current = version.number === shown;
                return (
                  <li key={version.id}>
                    <Link
                      to="/sources/$sourceId"
                      params={{ sourceId }}
                      search={{ v: version.number, view }}
                      aria-current={current ? "page" : undefined}
                      className={cn(
                        "flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted",
                        current && "bg-muted font-medium",
                      )}
                    >
                      <span className="flex items-center gap-2">
                        {t("sources.history.version", { number: version.number })}
                        {version.number === latest ? (
                          <Badge variant="success">{t("sources.history.latest")}</Badge>
                        ) : null}
                        {version.partial ? (
                          <Badge variant="warning">{t("sources.partial")}</Badge>
                        ) : null}
                      </span>
                      <time dateTime={version.fetched_at} className="text-muted-foreground">
                        {time.format(new Date(version.fetched_at))}
                      </time>
                    </Link>
                  </li>
                );
              })}
            </ol>
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground text-xs">{t("sources.history.pruned")}</p>
    </section>
  );
}
