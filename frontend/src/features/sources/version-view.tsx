import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "#/api/errors.ts";
import { readVersionTextOptions } from "#/client/@tanstack/react-query.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { aroundChanges, wordDiff } from "./word-diff.ts";

const GONE = 410;

function textQuery(sourceId: string, number: number) {
  return readVersionTextOptions({ path: { source_id: sourceId, number } });
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="grid gap-2">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}

// A failure to read a text: its files deleted (said as such), or the service unreachable.
function Failure({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useTranslation();
  if (error instanceof ApiError && error.status === GONE) {
    return <p className="text-muted-foreground text-sm">{t("sources.page.gone")}</p>;
  }
  return <Unavailable onRetry={onRetry} />;
}

const PROSE = "max-w-prose whitespace-pre-wrap text-sm leading-7";

// What version `number` of the Source said, as its extractor read it: its byline and date, then
// its text, kept as written (paragraphs, line breaks).
export function VersionText({ sourceId, number }: { sourceId: string; number: number }) {
  const { t, i18n } = useTranslation();
  const text = useQuery(textQuery(sourceId, number));
  if (text.isError) {
    return <Failure error={text.error} onRetry={() => text.refetch()} />;
  }
  if (!text.isSuccess) {
    return <Loading />;
  }
  const day = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  const { author, published_at: published } = text.data;
  return (
    <article className="grid gap-3">
      {author || published ? (
        <p className="text-muted-foreground text-sm">
          {[
            author ? t("sources.page.author", { author }) : null,
            published
              ? t("sources.page.published", { time: day.format(new Date(published)) })
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
      <p className={PROSE}>{text.data.text}</p>
    </article>
  );
}

// What changed from the version before `number` to it, word by word, as GitBook shows a page's
// changes: inserted words underlined in green, removed ones struck through in red, in the text.
// The words added and removed are counted above it. Long unchanged stretches fold to the words
// around the changes (as GitHub folds unchanged lines), the whole text a click away. The first
// version has nothing before it.
export function VersionChanges({ sourceId, number }: { sourceId: string; number: number }) {
  const { t } = useTranslation();
  const [whole, setWhole] = useState(false);
  const previous = number - 1;
  const before = useQuery({ ...textQuery(sourceId, previous), enabled: previous > 0 });
  const after = useQuery(textQuery(sourceId, number));
  if (previous < 1) {
    return <p className="text-muted-foreground text-sm">{t("sources.page.firstVersion")}</p>;
  }
  if (before.isError || after.isError) {
    const failed = before.isError ? before : after;
    return <Failure error={failed.error} onRetry={() => failed.refetch()} />;
  }
  if (!(before.isSuccess && after.isSuccess)) {
    return <Loading />;
  }
  const diff = wordDiff(before.data.text, after.data.text);
  const unchanged = diff.added === 0 && diff.removed === 0;
  const folded = aroundChanges(diff.stretches);
  const foldable = folded.some((piece) => piece.change === "skipped");
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          {unchanged
            ? t("sources.page.unchanged", { previous })
            : t("sources.page.changed", { previous, added: diff.added, removed: diff.removed })}
        </p>
        {foldable ? (
          <Button variant="outline" size="sm" onClick={() => setWhole(!whole)}>
            {t(whole ? "sources.page.onlyChanges" : "sources.page.wholeText")}
          </Button>
        ) : null}
      </div>
      <p className={PROSE}>
        {(whole ? diff.stretches : folded).map((stretch, index) => {
          const key = `${index}-${stretch.change}`;
          if (stretch.change === "skipped") {
            return (
              <span
                key={key}
                className="my-3 block border-y border-dashed py-1 text-center text-muted-foreground text-xs"
              >
                {t("sources.page.skipped", { count: stretch.words })}
              </span>
            );
          }
          if (stretch.change === "added") {
            return (
              <ins
                key={key}
                className="rounded-sm bg-success/15 text-foreground decoration-success underline-offset-4"
              >
                <span className="sr-only">{t("sources.page.addedStart")}</span>
                {stretch.text}
                <span className="sr-only">{t("sources.page.changeEnd")}</span>
              </ins>
            );
          }
          if (stretch.change === "removed") {
            return (
              <del
                key={key}
                className="rounded-sm bg-destructive/15 text-muted-foreground decoration-destructive"
              >
                <span className="sr-only">{t("sources.page.removedStart")}</span>
                {stretch.text}
                <span className="sr-only">{t("sources.page.changeEnd")}</span>
              </del>
            );
          }
          return <span key={key}>{stretch.text}</span>;
        })}
      </p>
    </div>
  );
}
