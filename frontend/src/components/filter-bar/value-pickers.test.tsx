import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { ValuePickerPage as Picker } from "#/test/filter-bar-page.tsx";
import { renderTranslated } from "#/test/render.tsx";
import type { FilterField } from "./filter-values.ts";

const KIND: FilterField = {
  id: "kind",
  label: "Kind",
  type: "options",
  options: [
    { value: "rss", label: "RSS", count: 12 },
    { value: "sitemap", label: "Sitemap", count: 3 },
    { value: "html", label: "Web page", count: 1204 },
  ],
};
const FEED: FilterField = {
  id: "feed",
  label: "Feed",
  type: "options",
  searchable: true,
  options: [
    { value: "tiefbau-aktuell", label: "Tiefbau Aktuell", group: "Press" },
    { value: "trassenbau", label: "Trassenbau Report", group: "Press" },
    { value: "bnetza", label: "BNetzA", group: "Verwaltung" },
  ],
};
const SOURCES: FilterField = {
  id: "sources",
  label: "Sources",
  type: "boolean",
  yes: "Has Sources",
  no: "None yet",
};
const CHANGED: FilterField = { id: "changed", label: "Last change", type: "period", custom: true };

test("each option is a checkbox with its count, and every tick applies at once", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const onDone = vi.fn();
  const { container } = renderTranslated(
    <Picker field={KIND} onChange={onChange} onDone={onDone} focusFirst={true} />,
  );

  const rss = screen.getByRole("checkbox", { name: "RSS 12" });
  await waitFor(() => expect(document.activeElement).toBe(rss)); // it replaced what had focus
  expect(screen.getByRole("group", { name: "Kind" })).toBeTruthy();
  expect(await violations(container)).toEqual([]);
  await user.click(rss);
  await user.click(screen.getByRole("checkbox", { name: "Web page 1,204" }));
  await user.click(rss);

  expect(onChange.mock.calls).toEqual([[["rss"]], [["rss", "html"]], [["html"]]]);
  expect(onDone).not.toHaveBeenCalled(); // several may be ticked
  expect(screen.queryByRole("searchbox")).toBeNull(); // not searchable
});

test("a searchable field narrows its options as one types, under their groups", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderTranslated(<Picker field={FEED} onChange={onChange} focusFirst={true} />);

  const search = screen.getByRole("searchbox", { name: "Search Feed" });
  await waitFor(() => expect(document.activeElement).toBe(search));
  expect(screen.getByRole("group", { name: "Verwaltung" })).toBeTruthy();
  await user.type(search, "trassen");

  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  expect(screen.queryByRole("group", { name: "Verwaltung" })).toBeNull();
  await user.click(within(screen.getByRole("group", { name: "Press" })).getByRole("checkbox"));
  await user.clear(search);
  await user.type(search, "nothing like it");
  expect(screen.getByText("Nothing matches.")).toBeTruthy();

  expect(onChange).toHaveBeenLastCalledWith(["trassenbau"]);
});

test("a field with nothing to offer yet says so", () => {
  renderTranslated(<Picker field={{ id: "feed", label: "Feed", type: "options", options: [] }} />);

  expect(screen.getByText("Nothing to choose yet.")).toBeTruthy();
});

test("yes or no is one choice in the field's words; choosing it is done", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const onDone = vi.fn();
  renderTranslated(<Picker field={SOURCES} initial={false} onChange={onChange} onDone={onDone} />);

  expect(screen.getByRole("button", { name: "None yet" }).getAttribute("aria-pressed")).toBe(
    "true",
  );
  expect(screen.getByRole("button", { name: "Has Sources" }).getAttribute("aria-pressed")).toBe(
    "false",
  );
  await user.click(screen.getByRole("button", { name: "Has Sources" }));

  expect(onChange).toHaveBeenCalledWith(true);
  expect(onDone).toHaveBeenCalledTimes(1);
});

test("yes and no read Yes and No when the field does not name them", () => {
  renderTranslated(<Picker field={{ id: "partial", label: "Partial", type: "boolean" }} />);

  expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Yes", "No"]);
});

test("a preset period is one choice, and choosing it is done", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const onDone = vi.fn();
  renderTranslated(
    <Picker
      field={{ id: "changed", label: "Last change", type: "period" }}
      onChange={onChange}
      onDone={onDone}
    />,
  );

  expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
    "Last 24 hours",
    "Last 7 days",
    "Last 30 days",
  ]);
  expect(screen.queryByRole("group", { name: "Custom range" })).toBeNull(); // not offered
  await user.click(screen.getByRole("button", { name: "Last 7 days" }));

  expect(onChange).toHaveBeenCalledWith({ preset: "7d" });
  expect(onDone).toHaveBeenCalledTimes(1);
});

test("days of one's own replace a preset, each applied as it is entered", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const onDone = vi.fn();
  const { container } = renderTranslated(
    <Picker field={CHANGED} initial={{ preset: "30d" }} onChange={onChange} onDone={onDone} />,
  );

  expect(screen.getByRole("button", { name: "Last 30 days" }).getAttribute("aria-pressed")).toBe(
    "true",
  );
  const custom = screen.getByRole("group", { name: "Custom range" });
  expect(await violations(container)).toEqual([]);
  const from = within(custom).getByLabelText("From") as HTMLInputElement;
  const to = within(custom).getByLabelText("To") as HTMLInputElement;
  await user.type(from, "2026-10-01");
  expect(onChange).toHaveBeenLastCalledWith({ from: "2026-10-01", to: undefined });
  expect(to.min).toBe("2026-10-01"); // the last day is not before the first
  await user.type(to, "2026-10-20");
  expect(onChange).toHaveBeenLastCalledWith({ from: "2026-10-01", to: "2026-10-20" });
  expect(from.max).toBe("2026-10-20");
  await user.clear(from);

  expect(onChange).toHaveBeenLastCalledWith({ from: undefined, to: "2026-10-20" });
  expect(onDone).not.toHaveBeenCalled(); // a second day may follow
});
