const DIGITS = /^\d{1,8}$/;

/** Municipalities per page. */
export const LIMIT = 50;

/** The most an export holds: the API's largest page. */
export const EXPORT_LIMIT = 500;

/** What the forecast's URL keeps (`/forecast?region=08&page=2`). */
export interface ForecastSearch {
  region?: string | undefined; // an AGS prefix: "08" Baden-Württemberg
  page?: number | undefined; // 1-based; none: the first
}

/** A region as the URL keeps it: an AGS prefix of 1 to 8 digits, else none. */
export function regionOf(value: unknown): string | undefined {
  return typeof value === "string" && DIGITS.test(value) ? value : undefined;
}

/**
 * The search parameters as the forecast reads them; anything that does not parse is dropped. A
 * region the router read as a number ("08" as 8) gets its leading zero back.
 */
export function forecastSearchIn({ region, page }: Record<string, unknown>): ForecastSearch {
  const number = Number(page);
  return {
    region: regionOf(typeof region === "number" ? String(region).padStart(2, "0") : region),
    page: Number.isInteger(number) && number > 1 ? number : undefined,
  };
}
