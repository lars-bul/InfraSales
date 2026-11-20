import { createFileRoute } from "@tanstack/react-router";
import { Opportunities } from "#/features/opportunities/opportunities.tsx";

// The company's chances, for every member of a company (the API checks the membership).
export const Route = createFileRoute("/_signed-in/opportunities")({
  staticData: { title: "opportunities.title", description: "opportunities.description" },
  component: Opportunities,
});
