import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { createRef } from "react";
import { I18nextProvider } from "react-i18next";
import { expect, test, vi } from "vitest";
import { i18n } from "#/i18n/i18n.ts";
import { violations } from "#/test/axe.ts";
import { SearchBox } from "./search-box.tsx";

// The box as a page holds it: the words passed back as `search`.
function box(search: string | undefined, onSearch: (search: string | undefined) => void) {
  return (
    <I18nextProvider i18n={i18n}>
      <SearchBox
        search={search}
        onSearch={onSearch}
        placeholder="Name or address"
        input={createRef()}
      />
    </I18nextProvider>
  );
}

test("the search waits for a pause in typing, then passes the words on once", async () => {
  const user = userEvent.setup();
  const onSearch = vi.fn();
  const { container } = render(box(undefined, onSearch));

  const search = screen.getByRole("searchbox", { name: "Search" }) as HTMLInputElement;
  expect(search.placeholder).toBe("Name or address");
  expect(await violations(container)).toEqual([]);
  await user.type(search, "  fernwaerme satzung ");

  await waitFor(() => expect(onSearch).toHaveBeenCalledWith("fernwaerme satzung"));
  expect(onSearch).toHaveBeenCalledTimes(1);
  expect(search.value).toBe("  fernwaerme satzung "); // what was typed stays
});

test("words changed from outside (going back) replace what the box shows", async () => {
  const user = userEvent.setup();
  const onSearch = vi.fn();
  const { rerender } = render(box("wärmeplan", onSearch));
  const search = screen.getByRole("searchbox", { name: "Search" }) as HTMLInputElement;
  expect(search.value).toBe("wärmeplan");

  await user.type(search, "s");
  await waitFor(() => expect(onSearch).toHaveBeenCalledWith("wärmeplans"));
  rerender(box("wärmeplans", onSearch)); // the page passes the words back
  expect(search.value).toBe("wärmeplans");
  rerender(box(undefined, onSearch)); // back
  expect(search.value).toBe("");
  rerender(box("wärmeplans", onSearch)); // forward

  expect(search.value).toBe("wärmeplans");
  expect(onSearch).toHaveBeenCalledTimes(1);
});

test("emptying the box passes on no words at all, not spaces", async () => {
  const user = userEvent.setup();
  const onSearch = vi.fn();
  render(box("wärmeplan", onSearch));

  const search = screen.getByRole("searchbox", { name: "Search" });
  await user.clear(search);
  await user.type(search, "   ");

  await waitFor(() => expect(onSearch).toHaveBeenCalledWith(undefined));
  expect(onSearch).toHaveBeenCalledTimes(1);
});
