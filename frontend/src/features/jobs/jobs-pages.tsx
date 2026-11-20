import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

const TAB =
  "-mb-px border-transparent border-b-2 px-1 pb-2 font-medium text-muted-foreground text-sm transition-colors hover:text-foreground data-[status=active]:border-foreground data-[status=active]:text-foreground";

// The Jobs page's two lists as tabs under its heading, as Databricks has "Jobs & pipelines" and
// "Job runs": each its own address, the current one marked as the page (`aria-current`).
export function JobsPages() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("jobs.pages.label")} className="flex gap-4 border-b">
      <Link to="/jobs" activeOptions={{ exact: true }} className={TAB}>
        {t("jobs.pages.jobs")}
      </Link>
      <Link to="/runs" activeOptions={{ includeSearch: false }} className={TAB}>
        {t("jobs.pages.runs")}
      </Link>
    </nav>
  );
}
