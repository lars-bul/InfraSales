import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRightIcon, ExternalLinkIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ApiError } from "#/api/errors.ts";
import { readMunicipalityOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { MunicipalityForecast as File, SignalRead, TenderRead } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Panel } from "#/components/panel.tsx";
import { Badge } from "#/components/ui/badge.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { featureLabel } from "./labels.ts";

const NOT_FOUND = 404; // no municipality has that AGS

// The way back to the ranking, as a Source's page has it.
function Breadcrumb() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("forecast.breadcrumb")}>
      <ol className="flex items-center gap-1 text-muted-foreground text-sm">
        <li>
          <Link to="/forecast" className="hover:text-foreground">
            {t("forecast.title")}
          </Link>
        </li>
        <li aria-hidden={true}>
          <ChevronRightIcon className="size-3.5" />
        </li>
      </ol>
    </nav>
  );
}

function useFormats() {
  const { i18n } = useTranslation();
  return {
    day: new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }),
    number: new Intl.NumberFormat(i18n.language),
    euro: new Intl.NumberFormat(i18n.language, {
      style: "currency",
      currency: "EUR",
      maximumFractionDigits: 0,
    }),
    decimal: new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 3 }),
    percent: new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 }),
  };
}

function Heading({ file }: { file: File }) {
  const { t } = useTranslation();
  const { number, percent } = useFormats();
  const facts = [
    t("forecast.file.ags", { ags: file.ags }),
    file.population === null
      ? undefined
      : t("forecast.file.inhabitants", { formatted: number.format(file.population) }),
  ].filter((fact) => fact !== undefined);
  return (
    <header className="grid gap-1">
      <Breadcrumb />
      <h1 className="font-heading font-semibold text-2xl tracking-tight">{file.name}</h1>
      <p className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
        {facts.join(" · ")}
        {file.rank === null ? (
          <Badge variant="outline">{t("forecast.file.unranked")}</Badge>
        ) : (
          <Badge variant="outline">
            {t("forecast.file.rank", {
              rank: number.format(file.rank),
              total: number.format(file.total),
            })}
          </Badge>
        )}
        {file.model?.calibrated && file.score !== null ? (
          <Badge variant="success">
            {t("forecast.probability")} {percent.format(file.score)}
          </Badge>
        ) : null}
      </p>
    </header>
  );
}

function Reasons({ file }: { file: File }) {
  const { t } = useTranslation();
  const { decimal } = useFormats();
  return (
    <Panel title={t("forecast.file.reasons")} description={t("forecast.file.reasonsDescription")}>
      {file.reasons.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("forecast.noReasons")}</p>
      ) : (
        <ul className="grid gap-2">
          {file.reasons.map((reason) => (
            <li key={reason.feature} className="flex items-center justify-between gap-3">
              <span>{featureLabel(t, reason.feature)}</span>
              <span className="text-muted-foreground text-sm tabular-nums">
                {decimal.format(reason.value)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SignalRow({ signal }: { signal: SignalRead }) {
  const { t } = useTranslation();
  const { day } = useFormats();
  return (
    <TableRow>
      <TableCell>{t(`forecast.signals.${signal.kind}`)}</TableCell>
      <TableCell>{signal.occurred_on ? day.format(new Date(signal.occurred_on)) : ""}</TableCell>
      <TableCell>{day.format(new Date(signal.available_on))}</TableCell>
      <TableCell className="whitespace-normal">{signal.note}</TableCell>
      <TableCell>
        {signal.url ? (
          <a
            href={signal.url}
            target="_blank"
            rel="noreferrer"
            aria-label={t("forecast.file.open")}
            className="inline-flex items-center text-muted-foreground hover:text-foreground"
          >
            <ExternalLinkIcon aria-hidden={true} className="size-4" />
          </a>
        ) : null}
      </TableCell>
    </TableRow>
  );
}

function Signals({ signals }: { signals: SignalRead[] }) {
  const { t } = useTranslation();
  return (
    <Panel title={t("forecast.file.signals")} description={t("forecast.file.signalsDescription")}>
      {signals.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("forecast.file.noSignals")}</p>
      ) : (
        <DataTable caption={t("forecast.file.captions.signals", { count: signals.length })}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("forecast.file.kind")}</TableHead>
              <TableHead scope="col">{t("forecast.file.occurred")}</TableHead>
              <TableHead scope="col">{t("forecast.file.known")}</TableHead>
              <TableHead scope="col">{t("forecast.file.note")}</TableHead>
              <TableHead scope="col">{t("forecast.file.link")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {signals.map((signal) => (
              <SignalRow
                key={`${signal.kind}-${signal.available_on}-${signal.url ?? signal.note}`}
                signal={signal}
              />
            ))}
          </TableBody>
        </DataTable>
      )}
    </Panel>
  );
}

function TenderRow({ tender }: { tender: TenderRead }) {
  const { t } = useTranslation();
  const { day, euro } = useFormats();
  const value = tender.award_value_eur ?? tender.estimated_value_eur;
  return (
    <TableRow>
      <TableCell className="whitespace-normal">
        <span className="grid gap-0.5">
          {tender.url ? (
            <a
              href={tender.url}
              target="_blank"
              rel="noreferrer"
              className="font-medium underline-offset-4 hover:underline"
            >
              {tender.title}
            </a>
          ) : (
            <span className="font-medium">{tender.title}</span>
          )}
          <span className="flex flex-wrap gap-1 text-muted-foreground text-xs">
            {tender.buyer_name}
            {tender.framework ? (
              <Badge variant="outline">{t("forecast.file.framework")}</Badge>
            ) : null}
          </span>
        </span>
      </TableCell>
      <TableCell>{t(`forecast.tenderKinds.${tender.kind}`)}</TableCell>
      <TableCell>{t(`forecast.tenderStatuses.${tender.status}`)}</TableCell>
      <TableCell>{tender.published_on ? day.format(new Date(tender.published_on)) : ""}</TableCell>
      <TableCell className="text-end tabular-nums">
        {value === null ? "" : euro.format(value)}
      </TableCell>
      <TableCell className="whitespace-normal">{tender.winner_name ?? ""}</TableCell>
    </TableRow>
  );
}

function Tenders({ tenders }: { tenders: TenderRead[] }) {
  const { t } = useTranslation();
  return (
    <Panel title={t("forecast.file.tenders")} description={t("forecast.file.tendersDescription")}>
      {tenders.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("forecast.file.noTenders")}</p>
      ) : (
        <DataTable caption={t("forecast.file.captions.tenders", { count: tenders.length })}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("forecast.file.title")}</TableHead>
              <TableHead scope="col">{t("forecast.file.kind")}</TableHead>
              <TableHead scope="col">{t("forecast.file.status")}</TableHead>
              <TableHead scope="col">{t("forecast.file.published")}</TableHead>
              <TableHead scope="col" className="text-end">
                {t("forecast.file.value")}
              </TableHead>
              <TableHead scope="col">{t("forecast.file.winner")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tenders.map((tender) => (
              <TenderRow
                key={`${tender.origin}-${tender.title}-${tender.available_on}`}
                tender={tender}
              />
            ))}
          </TableBody>
        </DataTable>
      )}
    </Panel>
  );
}

function History({ file }: { file: File }) {
  const { t } = useTranslation();
  const { day, decimal } = useFormats();
  if (file.history.length === 0) {
    return null;
  }
  return (
    <Panel title={t("forecast.file.history")} description={t("forecast.file.historyDescription")}>
      <DataTable caption={t("forecast.file.captions.history", { count: file.history.length })}>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{t("forecast.file.day")}</TableHead>
            <TableHead scope="col" className="text-end">
              {t("forecast.score")}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {file.history.map((point) => (
            <TableRow key={point.as_of}>
              <TableCell>{day.format(new Date(point.as_of))}</TableCell>
              <TableCell className="text-end tabular-nums">{decimal.format(point.score)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
    </Panel>
  );
}

function Features({ file }: { file: File }) {
  const { t } = useTranslation();
  const { decimal } = useFormats();
  if (file.features.length === 0) {
    return null;
  }
  return (
    <Panel title={t("forecast.file.features")} description={t("forecast.file.featuresDescription")}>
      <DataTable caption={t("forecast.file.captions.features", { count: file.features.length })}>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{t("forecast.file.feature")}</TableHead>
            <TableHead scope="col" className="text-end">
              {t("forecast.file.featureValue")}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {file.features.map((feature) => (
            <TableRow key={feature.name}>
              <TableCell>{featureLabel(t, feature.name)}</TableCell>
              <TableCell className="text-end tabular-nums">
                {decimal.format(feature.value)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
    </Panel>
  );
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="grid gap-3">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

// A municipality's forecast file: where it ranks and why, the signals and tenders it rests on,
// its score over time and every feature the model saw. What a sales call is prepared with.
export function MunicipalityForecast({ ags }: { ags: string }) {
  const { t } = useTranslation();
  const query = useQuery(readMunicipalityOptions({ path: { ags } }));
  if (query.error instanceof ApiError && query.error.status === NOT_FOUND) {
    return (
      <div className="grid gap-6">
        <Breadcrumb />
        <EmptyState
          title={t("forecast.file.notFound.title")}
          description={t("forecast.file.notFound.description")}
        />
      </div>
    );
  }
  if (query.isError) {
    return <Unavailable onRetry={() => query.refetch()} />;
  }
  if (!query.data) {
    return <Loading />;
  }
  const file = query.data;
  return (
    <div className="grid gap-6">
      <Heading file={file} />
      {file.as_of === null ? (
        <EmptyState
          title={t("forecast.empty.title")}
          description={t("forecast.empty.description")}
        />
      ) : null}
      <div className="grid gap-6 lg:grid-cols-2">
        <Reasons file={file} />
        <History file={file} />
      </div>
      <Signals signals={file.signals} />
      <Tenders tenders={file.tenders} />
      <Features file={file} />
    </div>
  );
}
