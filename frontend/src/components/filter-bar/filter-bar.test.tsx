import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { FilterBarPage as Page } from "#/test/filter-bar-page.tsx";
import { renderTranslated } from "#/test/render.tsx";
import { FilterBar } from "./filter-bar.tsx";
import type { FilterValues } from "./filter-values.ts";

// The filters the page holds, as the bar last passed them back.
function filtersSet(): FilterValues {
  return JSON.parse(
    screen.getByRole("status", { name: "Filters" }).textContent ?? "{}",
  ) as FilterValues;
}

// Opens the unset filter `label` (its button is always in view) and returns the picker of its values.
async function openFilter(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(screen.getByRole("button", { name: label }));
  return await screen.findByRole("dialog", { name: label });
}

const RANGE = /^Last change: Oct 1\s–\s20, 2026$/; // Intl puts thin spaces around the dash

test("every filter is in view; ticked value by value, it shows its values", async () => {
  const user = userEvent.setup();
  const { container } = renderTranslated(<Page />);
  expect(screen.getByText("28 Feeds").getAttribute("role")).toBe("status");
  const filters = screen.getByRole("group", { name: "Filters" });
  expect(
    within(filters)
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(["Kind", "Feed", "Sources", "Last change"]);

  const picker = await openFilter(user, "Kind");
  const rss = within(picker).getByRole("checkbox", { name: "RSS 12" });
  await waitFor(() => expect(document.activeElement).toBe(rss)); // focus moved into the picker
  expect(within(picker).getByRole("checkbox", { name: "Web page 1,204" })).toBeTruthy();
  expect(await violations(picker)).toEqual([]);
  await user.click(rss);
  await user.click(within(picker).getByRole("checkbox", { name: "Sitemap 3" }));

  expect(filtersSet()).toEqual({ kind: ["rss", "sitemap"] });
  expect(screen.getByRole("button", { name: "Kind: RSS, Sitemap" })).toBeTruthy();
  expect(screen.getByText("1 of 28 Feeds")).toBeTruthy();
  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Kind: RSS, Sitemap" })),
  );
  expect(await violations(container)).toEqual([]);
});

test("a set filter reopens its values; unticking the last one lifts it", async () => {
  const user = userEvent.setup();
  renderTranslated(<Page initial={{ kind: ["html", "rss", "sitemap"] }} />);

  await user.click(screen.getByRole("button", { name: "Kind: RSS, Sitemap +1" }));
  const picker = await screen.findByRole("dialog", { name: "Kind" });
  await user.click(within(picker).getByRole("checkbox", { name: "Sitemap 3" }));
  await user.click(within(picker).getByRole("checkbox", { name: "Web page 1,204" }));
  expect(screen.getByRole("button", { name: "Kind: RSS" })).toBeTruthy();
  await user.click(within(picker).getByRole("checkbox", { name: "RSS 12" }));

  expect(filtersSet()).toEqual({});
  expect(screen.getByRole("button", { name: "Kind" })).toBeTruthy();
});

test("lifting a filter leaves focus on its own button, unset again", async () => {
  const user = userEvent.setup();
  renderTranslated(<Page initial={{ kind: ["rss"], sources: true }} />);

  await user.click(screen.getByRole("button", { name: "Remove the filter Sources" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Sources" })),
  );
  await user.click(screen.getByRole("button", { name: "Remove the filter Kind" }));

  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Kind" })),
  );
  expect(filtersSet()).toEqual({});
  expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
});

test("yes or no is one choice in the field's words, and choosing closes the picker", async () => {
  const user = userEvent.setup();
  renderTranslated(<Page />);

  const picker = await openFilter(user, "Sources");
  await user.click(within(picker).getByRole("button", { name: "None yet" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(filtersSet()).toEqual({ sources: false });
  await user.click(screen.getByRole("button", { name: "Sources: None yet" }));
  const again = await screen.findByRole("dialog", { name: "Sources" });
  expect(within(again).getByRole("button", { name: "None yet" }).getAttribute("aria-pressed")).toBe(
    "true",
  );
  await user.click(within(again).getByRole("button", { name: "Has Sources" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByRole("button", { name: "Sources: Has Sources" })).toBeTruthy();
});

test("yes and no read Yes and No when the field does not name them", () => {
  renderTranslated(
    <Page
      fields={[{ id: "partial", label: "Partial", type: "boolean" }]}
      initial={{ partial: true }}
    />,
  );

  expect(screen.getByRole("button", { name: "Partial: Yes" })).toBeTruthy();
});

test("a period is a preset, or days of one's own when the field offers them", async () => {
  const user = userEvent.setup();
  const { container } = renderTranslated(<Page />);

  const picker = await openFilter(user, "Last change");
  await user.click(within(picker).getByRole("button", { name: "Last 30 days" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(filtersSet()).toEqual({ changed: { preset: "30d" } });

  await user.click(screen.getByRole("button", { name: "Last change: Last 30 days" }));
  const again = await screen.findByRole("dialog", { name: "Last change" });
  const custom = within(again).getByRole("group", { name: "Custom range" });
  expect(await violations(again)).toEqual([]);
  await user.type(within(custom).getByLabelText("From"), "2026-10-01");

  expect(filtersSet()).toEqual({ changed: { from: "2026-10-01" } });
  expect(screen.getByRole("button", { name: "Last change: Since Oct 1, 2026" })).toBeTruthy();
  await user.type(within(custom).getByLabelText("To"), "2026-10-20");
  expect(screen.getByRole("button", { name: RANGE })).toBeTruthy();
  await user.clear(within(custom).getByLabelText("From"));
  expect(screen.getByRole("button", { name: "Last change: Until Oct 20, 2026" })).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("Clear filters lifts the filters and the search, and focus goes to the search", async () => {
  const user = userEvent.setup();
  renderTranslated(<Page initial={{ kind: ["rss"] }} />);
  const search = screen.getByRole("searchbox", { name: "Search" });
  await user.type(search, "wärmeplan");
  await waitFor(() =>
    expect(screen.getByRole("status", { name: "Search" }).textContent).toBe("wärmeplan"),
  );

  await user.click(screen.getByRole("button", { name: "Clear filters" }));

  expect(filtersSet()).toEqual({});
  expect(screen.getByRole("status", { name: "Search" }).textContent).toBe("");
  expect((search as HTMLInputElement).value).toBe("");
  await waitFor(() => expect(document.activeElement).toBe(search));
  expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
});

test("a page that lifts everything at once is asked to, and without a search none shows", async () => {
  const user = userEvent.setup();
  const onClear = vi.fn();
  const onChange = vi.fn();
  renderTranslated(
    <FilterBar
      fields={[{ id: "partial", label: "Partial", type: "boolean" }]}
      value={{ partial: true }}
      onChange={onChange}
      onClear={onClear}
      sort={<button type="button" aria-label="Sort" />}
    />,
  );

  expect(screen.queryByRole("searchbox")).toBeNull();
  expect(screen.getByRole("button", { name: "Sort" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Clear filters" }));

  expect(onClear).toHaveBeenCalledTimes(1);
  expect(onChange).not.toHaveBeenCalled();
});

test("without a search, Clear filters leaves focus on the first filter", async () => {
  const user = userEvent.setup();
  renderTranslated(<Page initial={{ sources: true }} withSearch={false} />);

  await user.click(screen.getByRole("button", { name: "Clear filters" }));

  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Kind" })),
  );
});

test("setting a filter by one choice leaves focus on its button", async () => {
  const user = userEvent.setup();
  renderTranslated(
    <Page fields={[{ id: "partial", label: "Partial", type: "boolean" }]} withSearch={false} />,
  );

  const picker = await openFilter(user, "Partial");
  await user.click(within(picker).getByRole("button", { name: "Yes" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Partial: Yes" })),
  );
});

test("closing with Escape after ticking an option leaves focus on its button", async () => {
  const user = userEvent.setup();
  renderTranslated(
    <Page
      fields={[
        { id: "kind", label: "Kind", type: "options", options: [{ value: "rss", label: "RSS" }] },
      ]}
      withSearch={false}
    />,
  );

  const picker = await openFilter(user, "Kind");
  await user.click(within(picker).getByRole("checkbox", { name: "RSS" }));
  await user.keyboard("{Escape}");

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Kind: RSS" })),
  );
});

test("without fields there are no filters, only the search", () => {
  renderTranslated(<FilterBar fields={[]} value={{}} onChange={vi.fn()} onSearch={vi.fn()} />);

  expect(screen.getByRole("searchbox", { name: "Search" })).toBeTruthy();
  expect(screen.queryByRole("group", { name: "Filters" })).toBeNull();
});
