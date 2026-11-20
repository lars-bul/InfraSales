import AxeBuilder from "@axe-core/playwright";
import { test as base, type Page } from "@playwright/test";

const serverError = 500; // 5xx: the server failed
const unauthorized = 401; // the session ended

// WCAG 2.0 and 2.1, levels A and AA: colour contrast included, which jsdom cannot evaluate.
const wcag = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

interface Visit {
  url: string;
  scanned: boolean;
}

interface Fixtures {
  // What went wrong in the browser so far: the guard fails the test on any of it.
  problems: string[];
  // Checks the page as it is now with axe. The page a test ends on is checked anyway; any other
  // page must be checked before the test leaves it, or the guard fails the test. `except` leaves
  // out rules a state breaks on purpose (say why where it is used).
  scan: (except?: string[]) => Promise<void>;
  visits: Visit[];
  guard: undefined;
}

// Bindings the init script calls in the browser.
interface Reports {
  reportCspViolation: (violation: string) => void;
  reportRedirect: (from: string) => void;
}

function isPage(url: string): boolean {
  return url.startsWith("http");
}

// Transitions and animations that end (menus fading in or out), finished: axe measures colours
// as they are at rest, not halfway through a fade. Endless ones (spinners) are not waited for.
function settled(): Promise<unknown> {
  return Promise.all(
    document
      .getAnimations()
      .filter(
        (animation) => animation.effect?.getComputedTiming().endTime !== Number.POSITIVE_INFINITY,
      )
      .map((animation) => animation.finished.catch(() => undefined)), // cancelled: gone too
  );
}

async function accessibilityProblems(page: Page, except: string[] = []): Promise<string[]> {
  await page.evaluate(settled);
  const { violations } = await new AxeBuilder({ page })
    .withTags(wcag)
    .disableRules(except)
    .analyze();
  return violations.map(
    ({ id, help, nodes }) =>
      `axe ${id} on ${page.url()}: ${help} (${nodes.map(({ target }) => target.join(" ")).join(", ")})`,
  );
}

// In the browser, before the app: CSP violations, and the pages the app redirects away from
// (it replaces their history entry) before anyone could see them.
function reportFromTheBrowser() {
  const reports = globalThis as unknown as Reports;
  document.addEventListener("securitypolicyviolation", (event) => {
    reports.reportCspViolation(
      `${event.effectiveDirective} blocked ${event.blockedURI || "inline"} on ${event.documentURI}`,
    );
  });
  const { replaceState } = History.prototype;
  History.prototype.replaceState = function replace(this: History, ...args) {
    const [, , url] = args;
    if (url !== undefined && url !== null && new URL(url, location.href).href !== location.href) {
      reports.reportRedirect(location.href);
    }
    replaceState.apply(this, args);
  };
}

// Every spec fails on a CSP violation, a console error, a page error, a 5xx answer or an axe
// violation on any page it shows, so a library that breaks under the production headers or an
// unreadable colour is caught on its first run.
export const test = base.extend<Fixtures>({
  // biome-ignore lint/correctness/noEmptyPattern: Playwright reads a fixture's dependencies from it
  problems: async ({}, use) => {
    await use([]);
  },
  // biome-ignore lint/correctness/noEmptyPattern: Playwright reads a fixture's dependencies from it
  visits: async ({}, use) => {
    await use([]);
  },
  scan: async ({ page, problems, visits }, use) => {
    await use(async (except) => {
      problems.push(...(await accessibilityProblems(page, except)));
      for (const visit of visits.filter(({ url }) => url === page.url())) {
        visit.scanned = true;
      }
    });
  },
  guard: [
    async ({ page, problems, scan, visits }, use) => {
      const redirected = new Set<string>();
      // A page that is being left can still send a request (a poll, say) after a sign-out has
      // ended the session. The server rightly refuses it with a 401, which the browser logs as a
      // console error, and the app may still move to "session ended" in place before the next
      // document arrives. Neither is a problem of the page; any other 401 still counts.
      let leavingFor: string | undefined; // the document the main frame is loading next
      const refusedWhileLeaving = new Set<string>();
      const consoleErrors: { text: string; on: string; resource: string }[] = [];
      await page.exposeBinding("reportCspViolation", (_source, violation: string) => {
        problems.push(`CSP violation: ${violation}`);
      });
      await page.exposeBinding("reportRedirect", (_source, from: string) => {
        redirected.add(from);
      });
      await page.addInitScript(reportFromTheBrowser);
      page.on("console", (message) => {
        if (message.type() === "error") {
          consoleErrors.push({
            text: message.text(),
            on: page.url(),
            resource: message.location().url,
          });
        }
      });
      page.on("request", (request) => {
        if (request.isNavigationRequest() && request.frame() === page.mainFrame()) {
          leavingFor = request.url();
        }
      });
      page.on("pageerror", (error) => {
        problems.push(`page error on ${page.url()}: ${error.message}`);
      });
      page.on("response", (response) => {
        if (response.status() === unauthorized && leavingFor !== undefined) {
          refusedWhileLeaving.add(response.url());
        }
        if (response.status() >= serverError) {
          problems.push(
            `${response.status()} from ${response.request().method()} ${response.url()}`,
          );
        }
      });
      page.on("framenavigated", (frame) => {
        const url = frame.url();
        if (frame !== page.mainFrame() || (leavingFor !== undefined && leavingFor !== url)) {
          return; // another frame, or the page being left moving in place
        }
        leavingFor = undefined;
        if (isPage(url) && visits.at(-1)?.url !== url) {
          visits.push({ url, scanned: false });
        }
      });

      await use(undefined);

      if (visits.at(-1)?.scanned === false && isPage(page.url())) {
        await scan();
      }
      for (const { url, scanned } of visits) {
        if (!(scanned || redirected.has(url))) {
          problems.push(`left ${url} unchecked: scan() it before leaving`);
        }
      }
      for (const { text, on, resource } of consoleErrors) {
        if (!(refusedWhileLeaving.has(resource) && text.includes(`status of ${unauthorized}`))) {
          problems.push(`console error on ${on}: ${text}`);
        }
      }
      base.expect(problems, "problems in the browser").toEqual([]);
    },
    { auto: true },
  ],
});

export const { expect } = test;
