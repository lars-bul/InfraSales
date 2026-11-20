import axe from "axe-core";

/** Accessibility violations in `container` (WCAG rules axe can check without a real layout). */
export async function violations(container: Element): Promise<string[]> {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return results.violations.map((violation) => violation.id);
}
