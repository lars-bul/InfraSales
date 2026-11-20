import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  activateModelMutation,
  listModelsOptions,
  listModelsQueryKey,
  readRankingQueryKey,
} from "#/client/@tanstack/react-query.gen.ts";
import type { ModelRead } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { Panel } from "#/components/panel.tsx";
import { Badge } from "#/components/ui/badge.tsx";
import { Button } from "#/components/ui/button.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";

type Metrics = Record<string, unknown>;

function isMetrics(value: unknown): value is Metrics {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function measure(metrics: unknown, side: string, name: string): number | undefined {
  if (!isMetrics(metrics)) {
    return undefined;
  }
  const part = metrics[side];
  const value = isMetrics(part) ? part[name] : undefined;
  return typeof value === "number" ? value : undefined;
}

// A learned model's backtest beside the heuristic's on the same rows: AUC, and the share of the
// top 50 that did tender.
function Backtest({ model }: { model: ModelRead }) {
  const { t, i18n } = useTranslation();
  const auc = measure(model.metrics, "learned", "roc_auc");
  const top = measure(model.metrics, "learned", "precision_at_50");
  const heuristicAuc = measure(model.metrics, "heuristic", "roc_auc");
  if (auc === undefined || top === undefined || heuristicAuc === undefined) {
    return <>{t("forecast.models.noBacktest")}</>;
  }
  const decimal = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent" });
  return (
    <>
      {t("forecast.models.metrics", {
        auc: decimal.format(auc),
        top: percent.format(top),
        heuristicAuc: decimal.format(heuristicAuc),
      })}
    </>
  );
}

// The model versions for admins, newest first: the active one marked, another one activated by
// a click (a forecast run is queued at once, so the list follows it soon).
export function Models() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const models = useQuery(listModelsOptions());
  const [message, setMessage] = useState<string>();
  const activate = useMutation({
    ...activateModelMutation(),
    onSuccess: async (model) => {
      setMessage(t("forecast.models.activated", { version: model.version }));
      await queryClient.invalidateQueries({ queryKey: listModelsQueryKey() });
      await queryClient.invalidateQueries({ queryKey: readRankingQueryKey() });
    },
    onError: () => setMessage(t("forecast.models.failed")),
  });
  const day = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  return (
    <Panel title={t("forecast.models.title")} description={t("forecast.models.description")}>
      {models.isError ? <Unavailable onRetry={() => models.refetch()} /> : null}
      {models.data ? (
        <div className="grid gap-3">
          <DataTable caption={t("forecast.models.caption", { count: models.data.length })}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{t("forecast.models.version")}</TableHead>
                <TableHead scope="col">{t("forecast.models.kind")}</TableHead>
                <TableHead scope="col">{t("forecast.models.trained")}</TableHead>
                <TableHead scope="col">{t("forecast.models.backtest")}</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">{t("forecast.models.active")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {models.data.map((model) => (
                <TableRow key={model.id}>
                  <TableCell className="font-mono text-xs">{model.version}</TableCell>
                  <TableCell>{t(`forecast.models.kinds.${model.kind}`)}</TableCell>
                  <TableCell>
                    {model.trained_until ? day.format(new Date(model.trained_until)) : ""}
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <Backtest model={model} />
                  </TableCell>
                  <TableCell className="text-end">
                    {model.active ? (
                      <Badge variant="success">{t("forecast.models.active")}</Badge>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={activate.isPending}
                        onClick={() => activate.mutate({ path: { model_id: model.id } })}
                      >
                        {activate.isPending
                          ? t("forecast.models.activating")
                          : t("forecast.models.activate")}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </DataTable>
          <p role="status" className="text-sm">
            {message}
          </p>
        </div>
      ) : null}
    </Panel>
  );
}
