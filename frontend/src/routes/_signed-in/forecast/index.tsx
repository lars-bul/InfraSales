import { createFileRoute } from "@tanstack/react-router";
import { Forecast } from "#/features/forecast/forecast.tsx";
import { forecastSearchIn } from "#/features/forecast/search.ts";

function ForecastPage() {
  const { user } = Route.useRouteContext();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <Forecast
      user={user}
      search={search}
      onSearch={(next) => navigate({ search: next, replace: true })}
    />
  );
}

// The forecast, for everyone signed in: the region and the page live in the URL
// (`/forecast?region=08&page=2`), so a list can be linked to and shared.
export const Route = createFileRoute("/_signed-in/forecast/")({
  validateSearch: forecastSearchIn,
  staticData: { title: "forecast.title", description: "forecast.description" },
  component: ForecastPage,
});
