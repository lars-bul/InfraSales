import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { savesOf, scheduleAdminPage, scheduleForm } from "#/test/schedules.ts";

test("the time zone is found by typing part of its name", async () => {
  const { calls, container } = scheduleAdminPage();
  const user = userEvent.setup();
  const schedule = await scheduleForm();
  const zone = schedule.getByRole("combobox", { name: "Time zone" }) as HTMLInputElement;
  expect(zone.value).toBe("Europe/Berlin");

  await user.clear(zone);
  await user.type(zone, "berl");

  const found = within(await screen.findByRole("listbox"));
  expect(found.getAllByRole("option").map((option) => option.textContent)).toEqual([
    "Europe/Berlin",
  ]);
  expect(await violations(container)).toEqual([]);
  await user.clear(zone);
  await user.type(zone, "new_y");
  await user.click(await screen.findByRole("option", { name: "America/New_York" }));

  expect(zone.value).toBe("America/New_York");
  expect(schedule.getByRole("note", { name: "Summary" }).textContent).toBe(
    "Mon at 08:00 (America/New_York)",
  );
  expect(await violations(container)).toEqual([]);
  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");
  expect((await savesOf(calls))[0]?.body.timezone).toBe("America/New_York");
});

test("a name no time zone has says so", async () => {
  const { container } = scheduleAdminPage();
  const user = userEvent.setup();
  const zone = (await scheduleForm()).getByRole("combobox", { name: "Time zone" });

  await user.clear(zone);
  await user.type(zone, "atlantis");

  expect(await screen.findByText("No time zone has that name.")).toBeTruthy();
  expect(screen.queryAllByRole("option")).toEqual([]);
  expect(await violations(container)).toEqual([]);
});

test("a stored time zone is kept even if the browser does not list it", async () => {
  const legacy = { ...weekly, value: { ...weekly.value, timezone: "Etc/Legacy" } };
  const { calls } = scheduleAdminPage(legacy);
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  expect((schedule.getByRole("combobox", { name: "Time zone" }) as HTMLInputElement).value).toBe(
    "Etc/Legacy",
  );
  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");
  expect((await savesOf(calls))[0]?.body.timezone).toBe("Etc/Legacy");
});
