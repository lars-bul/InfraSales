import { AiSettings } from "#/features/settings/ai/ai-settings.tsx";

// InfraSales' settings: the models and their connections. Schedules are set on each job's page.
export function SettingsPage() {
  return (
    <div className="grid max-w-3xl gap-6">
      <AiSettings />
    </div>
  );
}
