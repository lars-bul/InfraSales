import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ApiError } from "#/api/errors.ts";
import { listOpportunitiesOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { OpportunityRead } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Badge } from "#/components/ui/badge.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";

const FORBIDDEN = 403; // the user belongs to no company
const REASONS = new Set(["near", "won_with_buyer", "won_in_land", "no_public_wins"]);

type Reason = "near" | "won_with_buyer" | "won_in_land" | "no_public_wins";

function isReason(value: string): value is Reason {
  return REASONS.has(value);
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="grid gap-2">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

function Row({ item }: { item: OpportunityRead }) {
  const { t, i18n } = useTranslation();
  const percent = new Intl.NumberFormat(i18n.language, {
    style: "percent",
    maximumFractionDigits: 1,
  });
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 });
  const euro = new Intl.NumberFormat(i18n.language, {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  });
  const day = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  const { form } = item;
  return (
    <TableRow>
      <TableCell className="tabular-nums">{percent.format(item.win_chance)}</TableCell>
      <TableCell>
        <Badge variant={item.kind === "open" ? "success" : "outline"}>
          {t(item.kind === "open" ? "opportunities.open" : "opportunities.expected")}
        </Badge>
      </TableCell>
      <TableCell className="whitespace-normal">
        <span className="grid gap-0.5">
          <span className="font-medium">{item.title}</span>
          {item.municipality_ags ? (
            <Link
              to="/forecast/$ags"
              params={{ ags: item.municipality_ags }}
              className="text-muted-foreground text-xs underline-offset-4 hover:underline"
            >
              {item.municipality}
            </Link>
          ) : null}
        </span>
      </TableCell>
      <TableCell className="text-end tabular-nums">
        {item.distance_km === null
          ? ""
          : t("opportunities.km", { km: number.format(item.distance_km) })}
      </TableCell>
      <TableCell>{item.deadline_on ? day.format(new Date(item.deadline_on)) : ""}</TableCell>
      <TableCell className="text-end tabular-nums">
        {item.value_eur === null ? "" : euro.format(item.value_eur)}
      </TableCell>
      <TableCell className="text-end tabular-nums">
        {item.expected_offers === null ? "" : number.format(item.expected_offers)}
      </TableCell>
      <TableCell className="whitespace-normal text-xs">
        {t("opportunities.form", {
          procedure: form.procedure ?? "–",
          lots: form.lots_median === null ? "–" : number.format(form.lots_median),
          price: form.price_only_share === null ? "–" : percent.format(form.price_only_share),
        })}
      </TableCell>
      <TableCell className="whitespace-normal">
        <span className="flex flex-wrap gap-1">
          {item.reasons.filter(isReason).map((reason) => (
            <Badge key={reason} variant="outline">
              {t(`opportunities.reasons.${reason}`)}
            </Badge>
          ))}
        </span>
      </TableCell>
    </TableRow>
  );
}

// Where the company has its best chances (ADR 06 §7): open heat network tenders in its reach
// first, then the municipalities the forecast expects to tender, each with the chance it wins if
// it bids, the likely form of the award and the competition, and why.
export function Opportunities() {
  const { t } = useTranslation();
  const query = useQuery(listOpportunitiesOptions());
  if (query.error instanceof ApiError && query.error.status === FORBIDDEN) {
    return (
      <EmptyState
        title={t("opportunities.noCompany.title")}
        description={t("opportunities.noCompany.description")}
      />
    );
  }
  if (query.isError) {
    return <Unavailable onRetry={() => query.refetch()} />;
  }
  if (!query.data) {
    return <Loading />;
  }
  if (query.data.length === 0) {
    return (
      <EmptyState
        title={t("opportunities.empty.title")}
        description={t("opportunities.empty.description")}
      />
    );
  }
  return (
    <div className="grid gap-3">
      <p className="text-muted-foreground text-sm">{t("opportunities.reading")}</p>
      <DataTable caption={t("opportunities.caption", { count: query.data.length })}>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{t("opportunities.chance")}</TableHead>
            <TableHead scope="col">{t("opportunities.kind")}</TableHead>
            <TableHead scope="col">{t("opportunities.what")}</TableHead>
            <TableHead scope="col" className="text-end">
              {t("opportunities.distance")}
            </TableHead>
            <TableHead scope="col">{t("opportunities.deadline")}</TableHead>
            <TableHead scope="col" className="text-end">
              {t("opportunities.value")}
            </TableHead>
            <TableHead scope="col" className="text-end">
              {t("opportunities.offers")}
            </TableHead>
            <TableHead scope="col">{t("opportunities.formTitle")}</TableHead>
            <TableHead scope="col">{t("opportunities.why")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {query.data.map((item) => (
            <Row key={`${item.kind}-${item.tender_id ?? item.municipality_ags}`} item={item} />
          ))}
        </TableBody>
      </DataTable>
    </div>
  );
}
