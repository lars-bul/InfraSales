import { PlayIcon } from "lucide-react";
import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";
import type { JobName } from "#/client/types.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import type { RunNowState } from "./use-run-now.ts";

interface Props {
  job: JobName;
  name: string; // the job's display name, for the button's accessible name
  runNow: RunNowState;
}

// A primary button with an icon, as Databricks has it beside a job's name.
function RunButton({ name, ...props }: ComponentProps<typeof Button> & { name: string }) {
  const { t } = useTranslation();
  return (
    <Button aria-label={t("jobs.runNamed", { name })} {...props}>
      <PlayIcon aria-hidden={true} data-icon="inline-start" />
      {t("jobs.runNow")}
    </Button>
  );
}

// Run now, for a card's header (admins): the request is sent at once.
export function RunNowButton({ name, runNow }: Props) {
  return <RunButton name={name} onClick={runNow.start} />;
}
