import { createFileRoute } from "@tanstack/react-router";
import { ComingSoon } from "#/components/coming-soon.tsx";

// Not built yet (ADR 06 §9): listed in the sidebar (marked Soon) for everyone, the heading saying
// what will come.
export const Route = createFileRoute("/_signed-in/projects")({
  staticData: { title: "projects.title", description: "projects.description" },
  component: ComingSoon,
});
