import { fireEvent, screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { noRuns } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

// The filters above every job's runs: which job, scheduled from when until when, which status,
// what started the run.

function options(select: HTMLElement) {
  return within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);
}

function jobRuns(url = "/runs") {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/jobs/runs": noRuns,
    ...summaries,
  });
  return renderApp(url);
}

test("each filter offers everything first, then each choice by name", async () => {
  const { container } = jobRuns();

  const job = await screen.findByRole("combobox", { name: "Job" });

  expect(options(job)).toEqual(["All jobs", "Source Collection", "Forecast"]);
  expect(options(screen.getByRole("combobox", { name: "Status" }))).toEqual([
    "Any status",
    "Succeeded",
    "Failed",
    "Running",
    "Waiting",
  ]);
  expect(options(screen.getByRole("combobox", { name: "Started by" }))).toEqual([
    "Anyone",
    "The schedule",
    "Run now",
    "After another job",
  ]);
  expect((job as HTMLSelectElement).value).toBe("");
  expect(await violations(container)).toEqual([]);
});

test("the filters show what the URL chose, and choosing everything lifts a filter", async () => {
  const { router } = jobRuns(`/runs?${new URLSearchParams({ job: "scrape", status: "failed" })}`);
  const status = await screen.findByRole("combobox", { name: "Status" });
  expect((screen.getByRole("combobox", { name: "Job" }) as HTMLSelectElement).value).toBe("scrape");
  expect((status as HTMLSelectElement).value).toBe("failed");

  await userEvent.selectOptions(status, "Any status");

  await expect.poll(() => router.state.location.search).toEqual({ job: "scrape" });
});

test("a start and an end are chosen as local dates and times, and cleared beside them", async () => {
  const { container, router } = jobRuns("/runs?start=2026-10-10T10:00");
  const start = await screen.findByLabelText("Start");
  const end = screen.getByLabelText("End");
  expect((start as HTMLInputElement).value).toBe("2026-10-10T10:00");
  expect(end.getAttribute("min")).toBe("2026-10-10T10:00"); // the picker offers no end before it
  expect(screen.queryByRole("button", { name: "Clear the end" })).toBeNull(); // nothing to clear

  fireEvent.change(end, { target: { value: "2026-10-12T09:30" } });

  await expect
    .poll(() => router.state.location.search)
    .toEqual({ start: "2026-10-10T10:00", end: "2026-10-12T09:30" });
  expect(await violations(container)).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Clear the start" }));
  await expect.poll(() => router.state.location.search).toEqual({ end: "2026-10-12T09:30" });
});
