import type { ConfigEntryRead } from "#/client/types.gen.ts";

// Source Collection's schedule changed to once a week: what the schedule forms start from.
export const weekly: ConfigEntryRead = {
  key: "scrape_schedule",
  value: {
    days: ["mon"],
    time: "08:00",
    timezone: "Europe/Berlin",
    enabled: true,
    every_hours: null,
  },
  revision: 1,
  updated_at: "2026-10-01T06:00:00Z",
  next_run_at: "2026-10-05T06:00:00Z", // Monday 08:00 in Berlin
};

export const scrape: ConfigEntryRead = {
  key: "scrape_schedule",
  value: {
    days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    time: "00:00",
    timezone: "Europe/Berlin",
    enabled: true,
    every_hours: 3,
  },
  revision: 1,
  updated_at: "2026-10-01T06:00:00Z",
  next_run_at: "2026-10-05T04:00:00Z", // 06:00 in Berlin
};

// The forecast's default: Mondays before the sales week starts.
export const forecast: ConfigEntryRead = {
  key: "forecast_schedule",
  value: {
    days: ["mon"],
    time: "05:00",
    timezone: "Europe/Berlin",
    enabled: true,
    every_hours: null,
  },
  revision: 1,
  updated_at: "2026-10-01T06:00:00Z",
  next_run_at: "2026-10-05T03:00:00Z", // Monday 05:00 in Berlin
};
