import { createFileRoute } from "@tanstack/react-router";
import { MunicipalityForecast } from "#/features/forecast/municipality.tsx";

function MunicipalityPage() {
  const { ags } = Route.useParams();
  return <MunicipalityForecast ags={ags} />;
}

// A municipality's forecast file (`/forecast/08221000`), for everyone signed in. The page heads
// itself (its name, under a breadcrumb).
export const Route = createFileRoute("/_signed-in/forecast/$ags")({
  staticData: { title: "forecast.title", headed: true },
  component: MunicipalityPage,
});
