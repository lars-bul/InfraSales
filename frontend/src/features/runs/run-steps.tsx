import { cn } from "cn";
import {
  CircleCheckIcon,
  CircleIcon,
  CircleXIcon,
  LoaderCircleIcon,
  type LucideIcon,
  RotateCwIcon,
  XIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { RunProgress } from "#/client/types.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import type { Translate } from "#/i18n/i18n.ts";
import { FeedProgress } from "./feed-progress.tsx";
import type { RunNowState } from "./use-run-now.ts";

type StepState = "done" | "current" | "retrying" | "upcoming" | "failed";
type StepName = "queued" | "running" | "succeeded" | "failed";

interface Step {
  name: StepName;
  state: StepState;
  attempt?: number; // shown from the second attempt on
}

// Each state as icon and colour (the word says it, too: never colour alone).
const LOOKS = {
  done: { icon: CircleCheckIcon, className: "text-success" },
  current: { icon: LoaderCircleIcon, className: "animate-spin text-primary" },
  retrying: { icon: RotateCwIcon, className: "text-warning" },
  upcoming: { icon: CircleIcon, className: "text-muted-foreground" },
  failed: { icon: CircleXIcon, className: "text-destructive" },
} as const satisfies Record<StepState, { icon: LucideIcon; className: string }>;

// Queued → Running → Finished (or Failed), as far as the run got. A run waiting for its next
// attempt is still on Running, with the attempt it waits for.
function stepsOf(run: RunProgress): Step[] {
  const last: StepName = run.status === "failed" ? "failed" : "succeeded";
  switch (run.status) {
    case "pending":
      return run.attempts === 0
        ? [
            { name: "queued", state: "current" },
            { name: "running", state: "upcoming" },
            { name: last, state: "upcoming" },
          ]
        : [
            { name: "queued", state: "done" },
            { name: "running", state: "retrying", attempt: run.attempts + 1 },
            { name: last, state: "upcoming" },
          ];
    case "running":
      return [
        { name: "queued", state: "done" },
        { name: "running", state: "current", attempt: run.attempts },
        { name: last, state: "upcoming" },
      ];
    case "succeeded":
      return [
        { name: "queued", state: "done" },
        { name: "running", state: "done" },
        { name: last, state: "done" },
      ];
    default:
      return [
        { name: "queued", state: "done" },
        { name: "running", state: "done" },
        { name: last, state: "failed" },
      ];
  }
}

// What is announced as the run moves on (a failure is an alert instead).
function announcement(run: RunProgress, t: Translate) {
  switch (run.status) {
    case "pending":
      return t(run.attempts > 0 ? "jobs.progress.retrying" : "jobs.progress.queued");
    case "running":
      return run.attempts > 1
        ? t("jobs.progress.runningAttempt", { attempt: run.attempts, max: run.max_attempts })
        : t("jobs.progress.running");
    case "succeeded":
      return t("jobs.progress.succeeded");
    default:
      return null;
  }
}

// What the steps show in words as it is: queued and retrying say more (what happens next).
const SAID_BY_THE_STEPS = new Set<RunProgress["status"]>(["running", "succeeded"]);

// One step: its state as an icon named for screen readers, its word, and on a retry the attempt.
function StepItem({ step, max }: { step: Step; max: number }) {
  const { t } = useTranslation();
  const look = LOOKS[step.state];
  const current = step.state === "current" || step.state === "retrying";
  return (
    <li aria-current={current ? "step" : undefined} className="flex items-center gap-2 text-sm">
      <span role="img" aria-label={t(`jobs.steps.states.${step.state}`)}>
        <look.icon aria-hidden={true} className={cn("size-4", look.className)} />
      </span>
      <span
        className={cn(
          step.state === "upcoming" && "text-muted-foreground",
          step.state === "failed" && "text-destructive",
          current && "font-medium",
        )}
      >
        {t(`jobs.steps.${step.name}`)}
      </span>
      {step.attempt !== undefined && step.attempt > 1 ? (
        <span className="text-muted-foreground">
          {t("jobs.steps.attempt", { attempt: step.attempt, max })}
        </span>
      ) : null}
    </li>
  );
}

// What the run's progress says out loud: its step as it moves on, and as alerts what went wrong.
function Announcements({ runNow }: { runNow: RunNowState }) {
  const { t } = useTranslation();
  const { run, lost, reconnecting, notQueued } = runNow;
  return (
    <div className="grid gap-1 text-sm">
      <p role="status">
        {reconnecting ? t("jobs.reconnecting") : null}
        {run && !(reconnecting || lost) ? (
          // Running or finished, the steps above say so already: for screen readers only.
          <span className={cn(SAID_BY_THE_STEPS.has(run.status) && "sr-only")}>
            {announcement(run, t)}
          </span>
        ) : null}
      </p>
      {run?.status === "failed" ? (
        <p role="alert" className="text-destructive">
          {t("jobs.progress.failed", { error: run.error ?? t("jobs.unknownError") })}
        </p>
      ) : null}
      {lost ? <p role="alert">{t("jobs.lost")}</p> : null}
      {notQueued ? <p role="alert">{t("jobs.notQueued")}</p> : null}
    </div>
  );
}

interface Props {
  name: string; // the job's display name
  runNow: RunNowState;
}

// The progress of the run under way (Run now's, or a scheduled one), as a list of steps; while it
// runs, how far it got (Source Collection: Feed by Feed). Once finished, it stays (with the run's
// session in Langfuse, if traced) until dismissed.
export function RunSteps({ name, runNow }: Props) {
  const { t } = useTranslation();
  const { run, finished, lost, notQueued } = runNow;
  // Nothing to show: no room taken. The live regions stay in place, so what follows is announced.
  const shown = run !== undefined || notQueued;

  return (
    // biome-ignore lint/a11y/useSemanticElements: what a run did, not form controls (fieldset)
    <div
      role="group"
      aria-label={t("jobs.steps.label", { name })}
      className={cn("grid gap-2", shown && "mb-4")}
    >
      {run ? (
        // As wide as there is room, whatever it says: the box keeps its size as the run goes on.
        <div className="flex w-full items-start justify-between gap-2 rounded-lg border bg-muted/30 p-3">
          <div className="grid min-w-0 flex-1 gap-3">
            <ol className="grid gap-2">
              {stepsOf(run).map((step) => (
                <StepItem key={step.name} step={step} max={run.max_attempts} />
              ))}
            </ol>
            {run.status === "running" && run.job === "scrape" ? (
              <FeedProgress progress={run.progress ?? null} />
            ) : null}
            {run.langfuse_url && finished ? (
              <a
                href={run.langfuse_url}
                target="_blank"
                rel="noreferrer"
                className="justify-self-start text-primary text-sm underline underline-offset-4"
                aria-label={t("jobs.langfuseNamed", { name })}
              >
                {t("jobs.langfuse")}
              </a>
            ) : null}
          </div>
          {finished || lost ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("jobs.steps.dismiss", { name })}
              onClick={runNow.dismiss}
            >
              <XIcon aria-hidden={true} />
            </Button>
          ) : null}
        </div>
      ) : null}
      <Announcements runNow={runNow} />
    </div>
  );
}
