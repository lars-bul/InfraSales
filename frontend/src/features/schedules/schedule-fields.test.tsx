import { fireEvent, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { savesOf, scheduleAdminPage, scheduleForm } from "#/test/schedules.ts";

// The Source Collection goes out Mondays at 08:00 (Europe/Berlin): once a week.

const summary = (form: ReturnType<typeof within>) =>
  form.getByRole("note", { name: "Summary" }).textContent;

test("the frequency is one of three pills, the stored one checked", async () => {
  const { container } = scheduleAdminPage();
  const schedule = await scheduleForm();
  const frequency = within(schedule.getByRole("radiogroup", { name: "Frequency" }));

  expect(frequency.getAllByRole("radio").map((radio) => radio.getAttribute("aria-label"))).toEqual([
    "Hour",
    "Day",
    "Week",
  ]);
  expect((frequency.getByRole("radio", { name: "Week" }) as HTMLInputElement).checked).toBe(true);
  expect(summary(schedule)).toBe("Mon at 08:00 (Europe/Berlin)");
  expect(await violations(container)).toEqual([]);
});

test("once a week falls on one day, chosen among the pills, and is saved so", async () => {
  const { calls } = scheduleAdminPage();
  const user = userEvent.setup();
  const schedule = await scheduleForm();
  const day = within(schedule.getByRole("radiogroup", { name: "On" }));

  await user.click(day.getByRole("radio", { name: "Friday" }));
  fireEvent.change(schedule.getByLabelText("Time"), { target: { value: "17:30" } });

  expect((day.getByRole("radio", { name: "Monday" }) as HTMLInputElement).checked).toBe(false);
  expect(summary(schedule)).toBe("Fri at 17:30 (Europe/Berlin)");
  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");
  expect((await savesOf(calls))[0]?.body).toEqual({
    ...weekly.value,
    days: ["fri"],
    time: "17:30",
  });
});

test("once a day runs every day, unless Only on is ticked and days are dropped", async () => {
  const { calls, container } = scheduleAdminPage();
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  await user.click(schedule.getByRole("radio", { name: "Day" }));
  const days = within(schedule.getByRole("group", { name: "Days" }));
  expect(summary(schedule)).toBe("Every day at 08:00 (Europe/Berlin)");
  expect((schedule.getByRole("checkbox", { name: "Only on" }) as HTMLInputElement).checked).toBe(
    false,
  );
  expect((days.getByRole("button", { name: "Saturday" }) as HTMLButtonElement).disabled).toBe(true);
  expect(await violations(container)).toEqual([]);

  await user.click(schedule.getByRole("checkbox", { name: "Only on" }));
  await user.click(days.getByRole("button", { name: "Saturday" }));
  await user.click(days.getByRole("button", { name: "Sunday" }));

  expect(days.getByRole("button", { name: "Sunday" }).getAttribute("aria-pressed")).toBe("false");
  expect(summary(schedule)).toBe("Mon–Fri at 08:00 (Europe/Berlin)");
  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");
  expect((await savesOf(calls))[0]?.body.days).toEqual(["mon", "tue", "wed", "thu", "fri"]);
});

test("every few hours offers the repeats the API takes, from midnight or a time set", async () => {
  const { calls, container } = scheduleAdminPage();
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  await user.click(schedule.getByRole("radio", { name: "Hour" }));
  const hours = schedule.getByRole("combobox", { name: "Every how many hours" });
  expect(
    within(hours)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["1", "2", "3", "4", "6", "8", "12"]);
  expect(summary(schedule)).toBe("Every day, every hour (Europe/Berlin)");
  expect(await violations(container)).toEqual([]);

  await user.selectOptions(hours, "3");
  fireEvent.change(schedule.getByLabelText("Start time"), { target: { value: "06:00" } });

  expect(summary(schedule)).toBe("Every day, every 3 hours from 06:00 (Europe/Berlin)");
  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");
  expect((await savesOf(calls))[0]?.body).toEqual({
    ...weekly.value,
    days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    time: "06:00",
    every_hours: 3,
  });
});

test("back from every few hours, once a week is at its time again", async () => {
  scheduleAdminPage();
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  await user.click(schedule.getByRole("radio", { name: "Hour" }));
  await user.click(schedule.getByRole("radio", { name: "Week" }));

  expect((schedule.getByLabelText("Time") as HTMLInputElement).value).toBe("08:00");
  expect(summary(schedule)).toBe("Mon at 08:00 (Europe/Berlin)");
});

test("a stored repeat from another time opens on Hour, and is saved as it was", async () => {
  const fromSix = { ...weekly.value, time: "06:00", every_hours: 3 as const };
  const { calls } = scheduleAdminPage({ ...weekly, value: fromSix });
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  expect((schedule.getByRole("radio", { name: "Hour" }) as HTMLInputElement).checked).toBe(true);
  expect((schedule.getByLabelText("Start time") as HTMLInputElement).value).toBe("06:00");
  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");
  expect((await savesOf(calls))[0]?.body).toEqual(fromSix);
});
