import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const MINUTE_MS = 60_000;
const TICK_MS = 30_000; // the countdown shows minutes: half a minute keeps it close
const MINUTES_PER_HOUR = 60;
const MINUTES_PER_DAY = 1440;

// The current time, again every TICK_MS.
function useNow(): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);
  return now;
}

// "Next run in 2 h 10 min", "in 3 d 4 h", "in 5 min": the two largest units, rounded up to the
// minute (a run due or just passed is "1 min" away until the one after it is read).
export function NextRun({ at }: { at: string }) {
  const { t } = useTranslation();
  const minutes = Math.max(1, Math.ceil((Date.parse(at) - useNow()) / MINUTE_MS));
  const units = [
    ["days", Math.floor(minutes / MINUTES_PER_DAY)],
    ["hours", Math.floor((minutes % MINUTES_PER_DAY) / MINUTES_PER_HOUR)],
    ["minutes", minutes % MINUTES_PER_HOUR],
  ] as const;
  const largest = units.findIndex(([, count]) => count > 0);
  const duration = units
    .slice(largest, largest + 2)
    .filter(([, count]) => count > 0)
    .map(([unit, count]) => t(`jobs.duration.${unit}`, { count }))
    .join(" ");
  return <time dateTime={at}>{t("jobs.nextRun", { duration })}</time>;
}
