import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { DownloadIcon } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { readRankingOptions } from "#/client/@tanstack/react-query.gen.ts";
import { readRanking } from "#/client/sdk.gen.ts";
import type { RankedMunicipality, Ranking, User } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Badge } from "#/components/ui/badge.tsx";
import { Button } from "#/components/ui/button.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { download, rankingCsv } from "./csv.ts";
import { featureLabel, LAENDER } from "./labels.ts";
import { Models } from "./models.tsx";
import { EXPORT_LIMIT, type ForecastSearch, LIMIT } from "./search.ts";

interface Props {
  user: User;
  search: ForecastSearch;
  onSearch: (search: ForecastSearch) => void;
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="grid gap-2">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

// How to read the scores, and the day they are for: a heuristic orders, a learned model gives
// probabilities within its horizon.
function Reading({ ranking }: { ranking: Ranking }) {
  const { t, i18n } = useTranslation();
  if (!(ranking.model && ranking.as_of)) {
    return null;
  }
  const day = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  const months = ranking.model.horizon_months;
  return (
    <p className="text-muted-foreground text-sm">
      {t("forecast.asOf", { date: day.format(new Date(ranking.as_of)) })}{" "}
      {ranking.model.calibrated ? t("forecast.learned", { months }) : t("forecast.heuristic")}
    </p>
  );
}

function Reasons({ item }: { item: RankedMunicipality }) {
  const { t } = useTranslation();
  if (item.reasons.length === 0) {
    return <span className="text-muted-foreground">{t("forecast.noReasons")}</span>;
  }
  return (
    <span className="flex flex-wrap gap-1">
      {item.reasons.map((reason) => (
        <Badge key={reason.feature} variant="outline">
          {featureLabel(t, reason.feature)}
        </Badge>
      ))}
    </span>
  );
}

function RankingTable({ ranking, offset }: { ranking: Ranking; offset: number }) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language);
  const percent = new Intl.NumberFormat(i18n.language, {
    style: "percent",
    maximumFractionDigits: 1,
  });
  const calibrated = ranking.model?.calibrated === true;
  const caption = t("forecast.caption", {
    count: ranking.items.length,
    total: number.format(ranking.total),
  });
  return (
    <DataTable caption={caption}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col" className="w-16">
            {t("forecast.rank")}
          </TableHead>
          <TableHead scope="col">{t("forecast.municipality")}</TableHead>
          <TableHead scope="col" className="text-end">
            {t("forecast.population")}
          </TableHead>
          {calibrated ? (
            <TableHead scope="col" className="text-end">
              {t("forecast.probability")}
            </TableHead>
          ) : null}
          <TableHead scope="col">{t("forecast.reasons")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody data-offset={offset}>
        {ranking.items.map((item) => (
          <TableRow key={item.ags}>
            <TableCell className="tabular-nums">{item.rank}</TableCell>
            <TableCell>
              <Link
                to="/forecast/$ags"
                params={{ ags: item.ags }}
                className="font-medium underline-offset-4 hover:underline"
              >
                {item.name}
              </Link>
            </TableCell>
            <TableCell className="text-end tabular-nums">
              {item.population === null ? "" : number.format(item.population)}
            </TableCell>
            {calibrated ? (
              <TableCell className="text-end tabular-nums">{percent.format(item.score)}</TableCell>
            ) : null}
            <TableCell className="whitespace-normal">
              <Reasons item={item} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </DataTable>
  );
}

function Pages({
  ranking,
  page,
  onPage,
}: {
  ranking: Ranking;
  page: number;
  onPage: (page: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language);
  const from = (page - 1) * LIMIT + 1;
  const to = from + ranking.items.length - 1;
  return (
    <nav aria-label={t("forecast.title")} className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground text-sm">
        {t("forecast.page", {
          from: number.format(from),
          to: number.format(to),
          total: number.format(ranking.total),
        })}
      </span>
      <span className="flex gap-2">
        <Button variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          {t("forecast.previous")}
        </Button>
        <Button variant="outline" disabled={to >= ranking.total} onClick={() => onPage(page + 1)}>
          {t("forecast.next")}
        </Button>
      </span>
    </nav>
  );
}

// The region select and the export: the list a sales team takes into its CRM.
function Toolbar({
  region,
  onRegion,
  exportable,
}: {
  region: string | undefined;
  onRegion: (region: string | undefined) => void;
  exportable: boolean;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [exporting, setExporting] = useState(false);
  const header = [
    t("forecast.rank"),
    "AGS",
    t("forecast.municipality"),
    t("forecast.population"),
    t("forecast.score"),
    t("forecast.reasons"),
  ];
  const exportList = async () => {
    setExporting(true);
    try {
      const { data } = await readRanking({
        query: { region: region ?? "", limit: EXPORT_LIMIT, offset: 0 },
        throwOnError: true,
      });
      const csv = rankingCsv(data.items, header, (feature) => featureLabel(t, feature));
      download(csv, `forecast-${region ?? "de"}-${data.as_of ?? "none"}.csv`);
    } finally {
      setExporting(false);
    }
  };
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="grid gap-1">
        <label htmlFor={id} className="font-medium text-sm">
          {t("forecast.region")}
        </label>
        <NativeSelect
          id={id}
          value={region ?? ""}
          onChange={(event) => onRegion(event.target.value || undefined)}
        >
          <NativeSelectOption value="">{t("forecast.everywhere")}</NativeSelectOption>
          {LAENDER.map(([prefix, name]) => (
            <NativeSelectOption key={prefix} value={prefix}>
              {name}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      <Button variant="outline" disabled={!exportable || exporting} onClick={exportList}>
        <DownloadIcon aria-hidden={true} />
        {exporting ? t("forecast.exporting") : t("forecast.export")}
      </Button>
    </div>
  );
}

function Listing({
  ranking,
  page,
  region,
  onPage,
}: {
  ranking: Ranking;
  page: number;
  region: string | undefined;
  onPage: (page: number) => void;
}) {
  const { t } = useTranslation();
  if (ranking.model === null) {
    return (
      <EmptyState title={t("forecast.empty.title")} description={t("forecast.empty.description")} />
    );
  }
  if (ranking.as_of === null) {
    return (
      <EmptyState
        title={t("forecast.pending.title")}
        description={t("forecast.pending.description")}
      />
    );
  }
  if (ranking.items.length === 0) {
    return region ? (
      <EmptyState
        title={t("forecast.noMatch.title")}
        description={t("forecast.noMatch.description")}
      />
    ) : (
      <EmptyState title={t("forecast.empty.title")} description={t("forecast.empty.description")} />
    );
  }
  return (
    <div className="grid gap-3">
      <Reading ranking={ranking} />
      <RankingTable ranking={ranking} offset={(page - 1) * LIMIT} />
      <Pages ranking={ranking} page={page} onPage={onPage} />
    </div>
  );
}

// Where a heat network's construction is likely put out to tender next (ADR 06 §7): every
// municipality, most likely first, each with the reasons that set it apart. A region narrows
// the list; the region and the page live in the URL. The list goes to a CRM as CSV. Admins see
// the model versions below and choose the one that serves.
export function Forecast({ user, search, onSearch }: Props) {
  const page = search.page ?? 1;
  const query = useQuery({
    ...readRankingOptions({
      query: { region: search.region ?? "", limit: LIMIT, offset: (page - 1) * LIMIT },
    }),
    placeholderData: (previous) => previous,
  });
  let listing = <Loading />;
  if (query.data) {
    listing = (
      <Listing
        ranking={query.data}
        page={page}
        region={search.region}
        onPage={(next) => onSearch({ ...search, page: next > 1 ? next : undefined })}
      />
    );
  } else if (query.isError) {
    listing = <Unavailable onRetry={() => query.refetch()} />;
  }
  return (
    <div className="grid gap-6">
      <Toolbar
        region={search.region}
        onRegion={(region) => onSearch({ region, page: undefined })}
        exportable={(query.data?.items.length ?? 0) > 0}
      />
      {listing}
      {user.role === "admin" ? <Models /> : null}
    </div>
  );
}
