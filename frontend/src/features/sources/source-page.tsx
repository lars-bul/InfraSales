import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronRightIcon, DownloadIcon, ExternalLinkIcon } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "#/api/errors.ts";
import { readSourceOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { SourceRead, VersionRead } from "#/client/types.gen.ts";
import { EmptyState } from "#/components/empty-state.tsx";
import { Badge } from "#/components/ui/badge.tsx";
import { buttonVariants } from "#/components/ui/button.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { hostOf, shortUrl, type View } from "./source-query.ts";
import { VersionHistory } from "./version-history.tsx";
import { VersionChanges, VersionText } from "./version-view.tsx";

const NOT_FOUND = 404;

interface Props {
  sourceId: string;
  v?: number | undefined; // the version to show; none: the latest
  view?: View | undefined; // none: its text
}

// The way back to the Sources, as the job page has it.
function Breadcrumb() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("sources.breadcrumb")}>
      <ol className="flex items-center gap-1 text-muted-foreground text-sm">
        <li>
          <Link to="/sources" className="hover:text-foreground">
            {t("sources.title")}
          </Link>
        </li>
        <li aria-hidden={true}>
          <ChevronRightIcon className="size-3.5" />
        </li>
      </ol>
    </nav>
  );
}

// What is known of the Source and of the version shown: where it is, when it was seen and
// checked, how the version was got and read.
function Details({ source, version }: { source: SourceRead; version: VersionRead }) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  const fetched =
    version.http_status === null
      ? t("sources.details.carried", { type: version.media_type })
      : t("sources.details.fetchedAs", { status: version.http_status, type: version.media_type });
  return (
    <section
      aria-labelledby={id}
      className="grid content-start gap-3 rounded-lg border bg-card p-4"
    >
      <h2 id={id} className="font-heading font-medium">
        {t("sources.details.title")}
      </h2>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">{t("sources.details.address")}</dt>
        <dd className="break-all">{source.url}</dd>
        <dt className="text-muted-foreground">{t("sources.feed")}</dt>
        <dd>{version.feed.name}</dd>
        <dt className="text-muted-foreground">{t("sources.details.firstSeen")}</dt>
        <dd>
          <time dateTime={source.first_seen_at}>{time.format(new Date(source.first_seen_at))}</time>
        </dd>
        <dt className="text-muted-foreground">{t("sources.details.lastChecked")}</dt>
        <dd>
          <time dateTime={source.last_checked_at}>
            {time.format(new Date(source.last_checked_at))}
          </time>
        </dd>
        <dt className="text-muted-foreground">{t("sources.details.fetched")}</dt>
        <dd>{fetched}</dd>
        <dt className="text-muted-foreground">{t("sources.details.extractor")}</dt>
        <dd>
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            {`${version.extractor} ${version.extractor_version}`}
          </code>
        </dd>
      </dl>
    </section>
  );
}

interface ViewProps {
  source: SourceRead;
  version: VersionRead;
  view: View;
}

// A Source's page, laid out as a job's: its title over where it is, with the original page and
// the raw file beside it; the version's text and what changed in it as tabs; at the side, every
// version to step through (Snowflake's and GitBook's version history) and the details.
function SourceView({ source, version, view }: ViewProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate({ from: "/sources/$sourceId" });
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  const raw = `/api/sources/${source.id}/versions/${version.number}/raw`;

  return (
    <div className="grid gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid min-w-0 gap-1">
          <Breadcrumb />
          <h1 className="font-heading font-semibold text-2xl tracking-tight">
            {version.title ?? shortUrl(source.url)}
          </h1>
          <p className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              aria-label={t("sources.page.original")}
              className="inline-flex items-center gap-1 underline-offset-4 hover:text-foreground hover:underline"
            >
              {hostOf(source.url)}
              <ExternalLinkIcon aria-hidden={true} className="size-3.5" />
            </a>
            {version.feed.name}
            {version.partial ? <Badge variant="warning">{t("sources.partial")}</Badge> : null}
          </p>
        </div>
        {/* a link: the browser downloads the file (the API says so), sandboxed, never shown */}
        <a
          href={raw}
          download={true}
          aria-label={t("sources.page.downloadNamed", { number: version.number })}
          className={buttonVariants({ variant: "outline" })}
        >
          <DownloadIcon aria-hidden={true} data-icon="inline-start" />
          {t("sources.page.download")}
        </a>
      </header>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="grid min-w-0 gap-3">
          <p className="text-muted-foreground text-sm">
            {t("sources.page.showing", {
              number: version.number,
              count: source.versions.length,
              time: time.format(new Date(version.fetched_at)),
            })}
          </p>
          <Tabs
            value={view}
            onValueChange={(chosen: View) =>
              navigate({ search: (search) => ({ ...search, view: chosen }), replace: true })
            }
          >
            <TabsList
              variant="line"
              aria-label={t("sources.page.tabs", { number: version.number })}
            >
              <TabsTrigger value="text">{t("sources.page.text")}</TabsTrigger>
              <TabsTrigger value="changes">{t("sources.page.changes")}</TabsTrigger>
            </TabsList>
            <TabsContent value="text" className="pt-3">
              <VersionText sourceId={source.id} number={version.number} />
            </TabsContent>
            <TabsContent value="changes" className="pt-3">
              <VersionChanges sourceId={source.id} number={version.number} />
            </TabsContent>
          </Tabs>
        </div>
        <div className="grid gap-4">
          <VersionHistory
            sourceId={source.id}
            versions={source.versions}
            shown={version.number}
            view={view}
          />
          <Details source={source} version={version} />
        </div>
      </div>
    </div>
  );
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="grid gap-4">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

// The Source `sourceId` at version `v` (its latest without one), in its text or changes view. A
// Source retention deleted, or a version it no longer has, leads back to the Sources.
export function SourcePage({ sourceId, v, view = "text" }: Props) {
  const { t } = useTranslation();
  const source = useQuery(readSourceOptions({ path: { source_id: sourceId } }));
  if (source.status === "pending") {
    return <Loading />;
  }
  if (source.isError && !(source.error instanceof ApiError && source.error.status === NOT_FOUND)) {
    return <Unavailable onRetry={() => source.refetch()} />;
  }
  const version = source.data?.versions.find((each) => v === undefined || each.number === v);
  if (!(source.data && version)) {
    return (
      <div className="grid gap-4">
        <Breadcrumb />
        <EmptyState
          title={t("sources.page.notFound.title")}
          description={t("sources.page.notFound.description")}
          className="rounded-lg border border-dashed"
        />
      </div>
    );
  }
  return <SourceView source={source.data} version={version} view={view} />;
}
