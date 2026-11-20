import type { RunActivity, RunSummary } from "#/client/types.gen.ts";

const WEEK = [
  "2026-10-10",
  "2026-10-11",
  "2026-10-12",
  "2026-10-13",
  "2026-10-14",
  "2026-10-15",
  "2026-10-16",
];

function summary(
  last24h: [number, number],
  last7d: [number, number],
  days: [number, number][],
): RunSummary {
  return {
    last_24h: { succeeded: last24h[0], failed: last24h[1] },
    last_7d: { succeeded: last7d[0], failed: last7d[1] },
    days: WEEK.map((day, index) => {
      const [succeeded, failed] = days[index] ?? [0, 0];
      return { day, succeeded, failed };
    }),
  };
}

// The jobs' runs per day over the same week, as the run activity counts them: each day begins
// at midnight in the browser's time zone (the API counts in it), so the days read the same in
// any time zone the tests run in.
function activity(...jobs: RunSummary[]): RunActivity {
  const midnight = (day: string) => new Date(`${day}T00:00`).toISOString();
  return {
    start: new Date(`${WEEK.at(0)}T00:00`).toISOString(),
    end: new Date(`${WEEK.at(-1)}T12:00`).toISOString(),
    unit: "day",
    buckets: WEEK.map((day, index) => ({
      start: midnight(day),
      succeeded: jobs.reduce((sum, job) => sum + (job.days[index]?.succeeded ?? 0), 0),
      failed: jobs.reduce((sum, job) => sum + (job.days[index]?.failed ?? 0), 0),
    })),
  };
}

// Source Collection's last week: 18 succeeded, 2 failed, every day (Sat 10 to Fri 16 October).
export const scrapeSummary = summary(
  [3, 1],
  [18, 2],
  [
    [3, 0],
    [2, 1],
    [3, 0],
    [2, 0],
    [3, 1],
    [2, 0],
    [3, 0],
  ],
);

export const scrapeActivity = activity(scrapeSummary);
export const allActivity = activity(scrapeSummary);

// What the jobs' pages ask of the API besides the runs: each job's run summary (a job's page
// asks for its own) and the activity of the runs listed (the Job runs page), of the job asked
// for or of every job.
export const summaries = {
  "GET /api/jobs/scrape/runs/summary": { body: scrapeSummary },
  "GET /api/jobs/runs/activity": (request: Request) => {
    const job = new URL(request.url).searchParams.get("job");
    return { body: job === "scrape" ? scrapeActivity : allActivity };
  },
};
