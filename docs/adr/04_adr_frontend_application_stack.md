# ADR 04: Frontend application stack

This ADR records how the web interface is built: routing, server data, the generated API client,
components, accessibility, the development loop and the tests. It extends the
[Frontend: React](01_adr_baseline.md#frontend-react) section of ADR 01 and replaces three of its
statements (see [What this supersedes](#what-this-supersedes-in-adr-01)).

## Context

ADR 01 chose React with TypeScript, built with Vite, because the planned screens (browsing and
curating what was found) keep a lot of state in the browser. Release 0.1.0 built the interface as a single
page with hand-written data fetching: `useState` and `useEffect` around a thin typed fetch client.
It had no routing, no shared cache of server data, no component library and no tests in a real
browser.

That was enough for two schedules and an audit log, but every new screen would have repeated the
same loading, retry, error and session-expiry handling by hand. Nothing showed a developer what was
cached or which page was active, and the development loop rebuilt the whole bundle on every change.
Three kinds of problems only show up in a real browser, and nothing checked them:

- the backend's Content-Security-Policy (`default-src 'self'`, see
  [`security.py`](../../src/infrasales/core/security.py)) blocking a library that injects `<style>` or
  `<script>` elements;
- colour contrast, which needs a real layout ([X1](01_adr_baseline.md#x1));
- a real sign-in round trip with the session cookie and the cross-site request check
  ([S1](01_adr_baseline.md#s1)).

One test of "run now" also failed at random, because it waited on real time.

The constraints from ADR 01 stay as they are. Sign-in, sessions, cookies and the CSP do not change
([U1](01_adr_baseline.md#u1), [U2](01_adr_baseline.md#u2), [S1](01_adr_baseline.md#s1)). The
interface must meet WCAG 2.1 AA ([X1](01_adr_baseline.md#x1)). Every package is pinned to an exact
version and installed only after a seven-day cooldown ([S2](01_adr_baseline.md#s2)), with strict
TypeScript (version 7), Biome with all rules, and an 85 % coverage gate for the hand-written code
([Q1](01_adr_baseline.md#q1)).

We compare options with the four questions of ADR 01
([How we compare options](01_adr_baseline.md#how-we-compare-options)): fit, effort, handover and
risk. Download figures are npm's weekly downloads for 9–15 October 2026
([npm download counts API](https://github.com/npm/registry/blob/main/docs/download-counts.md)).
They count installs, including CI and dependencies of other packages, not projects; we use them
only as a rough sign of how many people could take over the code.

## Decision

| Concern | Choice |
|---|---|
| Routing | TanStack Router: file-based, type-checked routes; the query client in the router context |
| Server data | TanStack Query with the query-options pattern; one place for retries, the deadline and session expiry |
| API client | Generated from the checked-in `openapi.json` by hey-api, with its TanStack Query plugin |
| Components | shadcn/ui on Base UI, with Tailwind CSS 4; no toast library for now |
| Accessibility | Adjusted colour tokens; axe in the browser tests for text, a unit test for non-text contrast |
| Dev loop | The Vite dev server with an API proxy to FastAPI; TanStack devtools, removed from every build |
| Testing | Two seams: the whole app at a URL with a fake `fetch`, and Playwright against the production build |

Imports between folders use Node's [subpath imports](https://nodejs.org/api/packages.html#subpath-imports)
(`#/…`, declared in `package.json`) instead of a bundler alias or tsconfig `paths`, so Node, Vite,
Vitest and TypeScript all read the same declaration.

### Routing: TanStack Router

Each page gets its own URL: `/sign-in` (outside the app shell), and inside a pathless `_signed-in`
layout `/` (schedules, run now and run history) and `/audit` (the audit log, admins only). We use
**[TanStack Router](https://tanstack.com/router/latest/docs/framework/react/routing/file-based-routing)**
with file-based routes in `src/routes/`, through its Vite plugin with
[automatic code splitting](https://tanstack.com/router/latest/docs/framework/react/guide/automatic-code-splitting).
The plugin writes the route tree to `src/routeTree.gen.ts`, which is committed and excluded from
Biome and coverage.

- **Type-checked routes.** Once the router is registered, every link, route parameter and search
  parameter is checked against the route tree
  ([type safety](https://tanstack.com/router/latest/docs/framework/react/guide/type-safety)). A link
  to a page that does not exist fails `tsc`; `router.test.tsx` holds such a link under
  `@ts-expect-error`, so the check itself is tested.
- **Validated search parameters.** `/sign-in` accepts `signin` (failed, denied, unavailable) and
  `ended`; any other value of them is ignored
  ([search params](https://tanstack.com/router/latest/docs/framework/react/guide/search-params)).
- **Guards in `beforeLoad`.** The `_signed-in` layout reads the session through the query cache and
  redirects to `/sign-in` when no one is signed in, carrying over a `signin` parameter, because the
  backend's built-in sign-in still redirects failures to `/?signin=failed`. `/audit` sends viewers
  to `/`, and `/sign-in` sends a signed-in user to `/`. The backend remains the access control
  ([U2](01_adr_baseline.md#u2)); the guards only spare users pages they cannot use.
- **The query client in the router context.** Route loaders fill the query cache
  (`ensureQueryData`) before a page renders, as the router's documentation describes for
  [external data loading](https://tanstack.com/router/latest/docs/framework/react/guide/external-data-loading)
  and the [router context](https://tanstack.com/router/latest/docs/framework/react/guide/router-context).
  Links preload on intent (hover or focus), and the router keeps no cache of its own
  (`defaultPreloadStaleTime: 0`), so TanStack Query is the only cache.
- **Errors.** The "unavailable" screen is the router's error component; its retry invalidates the
  router. Pages inside the shell use `PageError`, which has no `<main>` of its own, so the page
  keeps one main landmark.

FastAPI's existing fallback to `index.html` serves every client-side URL, so routing needed no
backend change.

**Cost:** the router is a second TanStack library to keep up to date, and its generated route
tree only updates when Vite runs (build, dev server or tests); `tsc` alone can see a stale one. In
Vitest, code splitting makes v8 report a few route lines as uncovered although they run.

<details><summary>Alternatives to TanStack Router</summary>

| Option | Fit | Effort | Handover | Risk |
|---|---|---|---|---|
| **TanStack Router** (chosen) | Type-checked links and search parameters, loaders that fill the TanStack Query cache, file-based routes in a plain Vite app | Low | 13.0 million weekly downloads; named by React's [guide to building an app from scratch](https://react.dev/learn/build-a-react-app-from-scratch) | Low: version 1, stable API |
| React Router, data mode | Loaders and actions; full type safety and typegen only in [framework mode](https://reactrouter.com/start/modes) | Low | The best known router: 33.2 million weekly downloads; also named by React's guide | Low |
| React Router, framework mode | Typed routes, but it takes over the build and rendering | Medium: a framework around the app | Well known | Medium: more to change on its upgrades |
| [wouter](https://github.com/molefrog/wouter) | Small; matching and links only, no loaders or typed links | Medium: guards and loading by hand | 1.2 million weekly downloads | Low |
| No router (one page, as in 0.1.0) | No URLs per page, no back button | High for every new screen | Our own code | Low |

TanStack's own [comparison](https://tanstack.com/router/latest/docs/framework/react/comparison)
lists type-safe navigation and validated search parameters as the main differences to React
Router; it says itself that it may not capture every nuance. React Router in data mode is the
closest alternative and the better known one. We chose TanStack Router because it checks every link
and search parameter in a plain Vite app without a framework, and because it is designed to load
through the same query cache as the rest of the app.

</details>

### Server data: TanStack Query with query options

All server data goes through **[TanStack Query](https://tanstack.com/query/latest/docs/framework/react/guides/query-options)**.
React's own guide recommends a data-fetching library over fetching in effects
([build a React app from scratch](https://react.dev/learn/build-a-react-app-from-scratch)). One
`QueryClient` is created at start and handed to the router. The rules live in one place,
[`lib/query-client.ts`](../../frontend/src/lib/query-client.ts):

- **Retries.** A query is retried at most twice, and only when it got no answer (no connection, or
  the 15-second deadline passed) or a 5xx answer. A 4xx answer would fail the same way again, so it
  shows at once. Mutations are never retried automatically, so no write happens twice behind the
  user's back. "Run now" keeps its own deliberate retry of an unanswered request, with the same
  `Idempotency-Key` ([Retries](https://tanstack.com/query/latest/docs/framework/react/guides/query-retries)).
- **The deadline.** Every request through the generated client gives up after 15 seconds
  ([`client-config.ts`](../../frontend/src/api/client-config.ts)), so no screen waits forever.
- **The session.** `GET /api/auth/session` is the one source of truth for who is signed in; nothing
  is kept in browser storage. Its query never goes stale on its own. A response interceptor on the
  generated client treats a 401 on any other route as the end of the session: it invalidates the
  session query and navigates to `/sign-in?ended=true`
  ([`features/auth/session.ts`](../../frontend/src/features/auth/session.ts)).
- **The usage rule.** Components and loaders use the generated `…Options()`, `…QueryKey()`,
  `…InfiniteOptions()` and `…Mutation()` helpers directly. A custom hook is written only when it
  adds logic. This is the query-options pattern that TanStack Query's maintainer recommends over
  custom hooks that only wrap `useQuery`
  ([The Query Options API](https://tkdodo.eu/blog/the-query-options-api),
  [Creating Query Abstractions](https://tkdodo.eu/blog/creating-query-abstractions)).

The screens map onto it as follows: schedules are a query and a mutation that keeps the `If-Match`
revision and shows a 412 as a conflict; "run now" is a mutation plus a polling query per run; run
history and the audit log are infinite queries paged with a `before` cursor. The audit log never
refetches in the background, because every read of it is itself audited.

**Cost:** one more library with its own concepts (stale time, invalidation, suspense), which a
maintainer has to learn. The generated client's error type does not match the runtime: after the
app starts, errors are our `ApiError` with `status` and `body`, not the parsed body the generated
types claim. Code checks `error instanceof ApiError`.

<details><summary>Alternatives to TanStack Query</summary>

| Option | Fit | Effort | Handover | Risk |
|---|---|---|---|---|
| **TanStack Query** (chosen) | Cache, retries, polling, infinite queries, mutations; works with the router's loaders; generated helpers exist for it | Low | 40.6 million weekly downloads; named by React's guide | Low: version 5 |
| [SWR](https://swr.vercel.app/) | Cache and revalidation; mutations and paging less complete | Medium | 11.2 million weekly downloads; named by React's guide | Low |
| [RTK Query](https://redux-toolkit.js.org/rtk-query/overview) | Complete, but brings Redux as the store | Medium: a store the app does not otherwise need | 19.5 million weekly downloads (Redux Toolkit); named by React's guide | Low |
| Hand-written `useEffect` fetching (0.1.0) | Works for two screens | High: loading, retry, error and expiry for every screen | Our own code | Medium: every screen gets it slightly differently |

</details>

### API client: generated by hey-api

ADR 01 generated only the API's types (openapi-typescript) and called them through openapi-fetch.
The interface now uses a client generated by
**[hey-api](https://heyapi.dev/openapi-ts/get-started)** (`@hey-api/openapi-ts`) with the plugins
`@hey-api/typescript`, `@hey-api/sdk`, `@hey-api/client-fetch` and
[`@tanstack/react-query`](https://heyapi.dev/openapi-ts/plugins/tanstack-query). For each API
operation it writes an SDK function, query options, a query key, infinite query options where the
operation pages, and mutation options. FastAPI's own guide to
[generating clients](https://fastapi.tiangolo.com/advanced/generate-clients/) names hey-api for
TypeScript.

- **Input and output.** The input is the checked-in `openapi.json`, never a running server:
  `/openapi.json` stays switched off ([Internal architecture](01_adr_baseline.md#internal-architecture)).
  The output in `frontend/src/client/` is committed, and the frontend lint fails when it differs
  from what the contract produces (`tools/api-client/check.ts`).
- **Short operation IDs.** FastAPI's default IDs (such as `list_runs_api_jobs__job__runs_get`)
  would become the helpers' names. The API router now takes the ID from the route function's name
  (`generate_unique_id_function`, as FastAPI's guide shows), so the helpers are called
  `listRunsInfiniteOptions`, `runNowMutation` and so on. The API's behaviour did not change; the
  backend's test for an out-of-date `openapi.json` covers the change.
- **A tools package with TypeScript 6.** The generator uses the TypeScript compiler as a library.
  TypeScript 7 [ships without that API](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
  until 7.1, and recommends running TypeScript 6 side by side for such tools. Next to TypeScript 7
  the generator crashed (`Cannot read properties of undefined (reading 'AnyKeyword')`), and pnpm
  overrides could not pin it. So it runs in its own workspace package, `frontend/tools/api-client`,
  with TypeScript 6.0.3; the app type-checks with TypeScript 7.
- **`@ts-nocheck` on the copied runtime files only.** hey-api copies its fetch client's runtime
  into the output. Those 12 files fail our `exactOptionalPropertyTypes`, so the output's
  [`header` option](https://heyapi.dev/openapi-ts/configuration/output) adds `// @ts-nocheck` to
  them and to nothing else. The generated types, the SDK and the Query helpers are checked in full.
  A separate tsconfig for the folder does not help: imported files are checked with the importing
  project's options.
- **Runtime settings in our own module.** Same-origin base URL and the request deadline come from
  `src/api/client-config.ts`, which the generated client loads at creation.

**Cost:** hey-api is still version 0.x; its documentation asks users to pin an exact version
because minor releases can break. Its client is bundled with the generator, so an upgrade changes
both. The second TypeScript version stays until the generator supports TypeScript 7's new API.

<details><summary>Alternatives to hey-api</summary>

| Option | Fit | Effort | Handover | Risk |
|---|---|---|---|---|
| **hey-api** with its TanStack Query plugin (chosen) | Named helpers per operation: query options, keys, infinite options, mutations; output header option for the strict config | Low | 3.0 million weekly downloads; named in FastAPI's guide | Medium: version 0.x, pinned exactly; needs TypeScript 6 beside 7 |
| [openapi-fetch](https://openapi-ts.dev/openapi-fetch/) with [openapi-react-query](https://openapi-ts.dev/openapi-react-query/) (0.1.0's types plus a Query layer) | Types only plus a small runtime; one `$api` object whose [`queryOptions`](https://openapi-ts.dev/openapi-react-query/query-options) take method and path strings; no generated names per operation | Medium: keys and infinite paging by hand | openapi-fetch 6.4 million weekly downloads, openapi-react-query 0.28 million | Low |
| [Orval](https://orval.dev/docs/guides/react-query) | A hook per operation, with query-option getters and key functions beside it | Low | 1.4 million weekly downloads | Medium |
| [Kubb](https://kubb.dev/plugins/plugin-react-query/) | `queryOptions` and `mutationOptions` factories with keys by default; hooks optional | Low | `@kubb/core` 0.2 million, its React Query plugin 0.06 million weekly downloads | Medium: smallest user base |

openapi-fetch is the most downloaded, but most of those installs use it without TanStack Query;
for this use, openapi-react-query is the comparable figure. Orval and Kubb generate similar
helpers. We chose hey-api because it generates exactly the query-options helpers the usage rule
above asks for, with the most users among the generators that do, and because FastAPI's guide
points to it.

</details>

### Components: shadcn/ui on Base UI, with Tailwind CSS

The interface is built from **[shadcn/ui](https://ui.shadcn.com/docs/installation/vite)**
components on **[Base UI](https://base-ui.com/react/overview/quick-start)** primitives, styled with
**[Tailwind CSS 4](https://tailwindcss.com/docs/installation/using-vite)** through its Vite plugin,
with the `nova` style, lucide icons and the Geist font. shadcn/ui is not a package of components: its
CLI copies the source of each component into `src/components/ui/`, where we own it. Base UI has been
[shadcn/ui's default since July 2026](https://ui.shadcn.com/docs/changelog/2026-07-base-ui-default);
Radix stays supported there.

The signed-in pages sit in an app shell: a sidebar with "Schedules" and, for admins, "Audit log";
a user menu with name, role, the theme and sign-out (still a native form post); and a top bar with
the sidebar toggle and the page heading. On small screens the sidebar opens as a sheet. The theme
is light, dark or system (the default), stored in `localStorage` and applied with a Tailwind
[`dark` variant](https://tailwindcss.com/docs/dark-mode) before the first render. No inline script
is allowed, so a very brief flash before the script runs is accepted. The visual design is
provisional; a later design spike replaces it.

**The CSP decides the primitives.** The production CSP allows no inline `<style>` or `<script>`
([MDN: `style-src`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/style-src)).
A library that injects one either breaks or needs a per-request nonce, which a static build served
by FastAPI does not have and which would mean changing the CSP. Tailwind writes one static
stylesheet at build time and injects nothing. We measured the component libraries in Chromium under
the production policy, counting `securitypolicyviolation` events:

| Component | Radix variant | Base UI variant |
|---|---|---|
| Dialog, sheet, popover, menu, tooltip | Violation: the scroll lock ([react-remove-scroll](https://github.com/theKashey/react-remove-scroll), through [react-style-singleton](https://github.com/theKashey/react-style-singleton)) injects a `<style>` | None |
| Select | Violation: it renders a `<style>` to hide the scrollbar (a `nonce` prop exists, but no nonce is available) | Violation only with `alignItemWithTrigger` (on by default); none with `CSPProvider` |
| Drawer | Violation: [vaul](https://github.com/emilkowalski/vaul) injects a `<style>` | Not used |
| Toast | Violation: [sonner](https://github.com/emilkowalski/sonner) injects its CSS as a `<style>`, with no nonce option | Same (sonner is not tied to either); Base UI's own Toast not measured |

Base UI documents its only two injecting parts, ScrollArea and Select, and a
[`CSPProvider`](https://base-ui.com/react/utils/csp-provider) whose `disableStyleElements` turns
them off. The app is wrapped in it, and the one rule those elements carried (hiding Select's
scrollbar, `.base-ui-disable-scrollbar`) is in the static stylesheet. With that, the browser tests
see no violation. **No toast library for now:** the screens report through inline status and alert
regions. When a screen needs toasts, the options are Base UI's own Toast, or loosening the CSP by
hash or nonce in a separate decision.

The generated folder (`src/components/ui/`, and `src/hooks/use-mobile.ts`) is excluded from Biome
and from coverage: it is the CLI's code, and rewriting it would make every `shadcn add` a merge.
Its built-in English texts (the screen-reader "Close", "Toggle Sidebar", the mobile sidebar's title
and description) are routed through i18next by hand under `ui.*` keys. That check, and a check for
injected `<style>`, must be repeated whenever `shadcn add` writes or overwrites a component; the
browser tests catch the second one. The CLI configuration (`components.json`) is written by hand,
because `shadcn init` does not detect a single `#/*` subpath import
([components.json](https://ui.shadcn.com/docs/components-json)).

**Cost:** we own the copied component code, including its fixes; upgrades come from re-running the
CLI and reviewing the diff. Base UI 1.x is younger than Radix. Tailwind is one more tool and a
utility-class style to learn.

<details><summary>Alternatives to shadcn/ui on Base UI</summary>

| Option | Fit | Effort | Handover | Risk |
|---|---|---|---|---|
| **shadcn/ui on Base UI** (chosen) | Accessible primitives, no injected styles with `CSPProvider`, the shadcn CLI for new components | Low | `@base-ui/react` 10.3 million, `shadcn` 7.1 million weekly downloads | Medium: Base UI 1.x is young; the copied code is ours |
| shadcn/ui on Radix | Same components | Low | Radix is the most installed: `@radix-ui/react-dialog` 46.0 million weekly downloads | High under our CSP: the scroll lock, Select and vaul inject styles (measured above) |
| [MUI](https://mui.com/material-ui/guides/content-security-policy/) | Complete library | Low | 5.5 million weekly downloads | High under our CSP: Emotion injects `<style>` tags that each need a nonce |
| [Mantine](https://mantine.dev/theming/mantine-provider/) | Complete library | Low | 1.6 million weekly downloads | High under our CSP: the provider renders its CSS variables in a `<style>` (nonce option only) |
| [React Aria Components](https://react-spectrum.adobe.com/react-aria/getting-started.html) | Accessible, unstyled primitives | Medium: every component styled by hand, no CLI | 2.7 million weekly downloads | Low |
| Plain HTML and our own CSS (0.1.0) | Works for forms and tables; dialogs, menus and a sidebar by hand | High | Our own code | Medium: accessibility of each widget is ours to get right |

React Aria is the strongest alternative on accessibility and has no CSP problem. We chose shadcn/ui
on Base UI because it gives ready, accessible parts through a CLI with little code of our own, and
because its default primitives pass our CSP as it is.

</details>

### Accessibility: contrast tokens and their guards

The interface must meet WCAG 2.1 AA ([X1](01_adr_baseline.md#x1)): text 4.5:1
([1.4.3](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html)), and 3:1 for the parts
of controls and focus indicators that people need to see
([1.4.11](https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html)). The default `nova`
theme failed both in the light theme:

| Token | Default (measured) | Adjusted |
|---|---|---|
| Destructive text, light (on its soft fill) | 4.0:1 | `oklch(0.5 0.2 27.325)`: 4.5:1 or better |
| Focus ring, light and dark | 1.6–2.6:1 | light `oklch(0.24 0.06 255)`, dark `oklch(0.8 0.08 255)`: 3:1 or better, also at the 50 % strength the components draw it with |
| Input and outline borders | 1.3–1.5:1 | light lightness 0.6, dark 0.55: 3:1 or better |
| Muted text, light | – | lightness 0.52: 4.5:1 or better |

Two guards keep them there:

- **Text contrast in the browser.** The browser tests run [axe](https://playwright.dev/docs/accessibility-testing)
  on every page in the light and the dark theme, with the WCAG 2.0 and 2.1 A and AA rules, which
  include `color-contrast`. jsdom has no layout, so the unit tests cannot check this; ADR 01 left it
  to a manual check.
- **Non-text contrast in a unit test.** axe has no rule for 1.4.11
  ([rule descriptions](https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md)).
  [`styles.test.ts`](../../frontend/src/styles.test.ts) reads the tokens from the stylesheet,
  converts them from OKLCH to sRGB, blends transparency, and checks the ratios above for both themes
  against the background, card, popover, sidebar and muted colours.

**Cost:** the tokens differ from the upstream theme, so a re-run of the shadcn theme setup can
undo them; the unit test catches that. The unit test checks tokens, not every place they are used.
An accessibility review stays part of going live ([X2](01_adr_baseline.md#x2)).

### Dev loop: Vite dev server and devtools

`make dev` runs two servers and stops both together: FastAPI on the profile's port (8000) with
`--reload`, and the **[Vite dev server](https://vite.dev/guide/features#hot-module-replacement)** on
5173, which the developer opens. Vite serves the sources without a build and
[proxies](https://vite.dev/config/server-options#server-proxy) `/api` to FastAPI, so the browser
sees one origin: the session cookie and the cross-site request check (`Sec-Fetch-Site:
same-origin`) work unchanged, and built-in sign-in works because its redirects are relative. OpenID
Connect through the proxy is not supported; it needs `make up`. The watch build is gone. The image
and `make up` still serve the production build from FastAPI. A saved frontend file reloads the page;
React Fast Refresh would need `@vitejs/plugin-react`, which we did not add.

The **[TanStack devtools](https://tanstack.com/devtools/latest/docs/overview)** shell, with the
[Router](https://tanstack.com/router/latest/docs/framework/react/devtools) and
[Query](https://tanstack.com/query/latest/docs/framework/react/devtools) panels, renders in the root
route in development only. Its panels inject `<style>` elements, which the production CSP would
block; the dev server sends no CSP. [`@tanstack/devtools-vite`](https://tanstack.com/devtools/latest/docs/vite-plugin)
is locked down in [`vite.config.ts`](../../frontend/vite.config.ts):

| Option | Setting | Why |
|---|---|---|
| `removeDevtoolsOnBuild` | on | The devtools shell does not strip itself from a build; the plugin removes it from every build. Checked: no devtools code is in `dist/`, and the main chunk is the same as without devtools |
| `injectSource` | on | "Go to source" from the page, in development only |
| `consolePiping` | off | Its endpoint answers any origin (`Access-Control-Allow-Origin: *`) |
| `enhancedLogs` | off | Not needed: it adds source locations to every `console` call |
| Marketplace | its server-side sub-plugin is filtered out | It installs packages and edits source files from the panel; version 0.8.5 has no option to turn it off, and dependencies here are added by hand at exact versions |

The production build is also configured to contain no inline script (Vite's
[module-preload polyfill](https://vite.dev/config/build-options#build-modulepreload) is off).

**Cost:** two servers instead of one, and development no longer runs the production build, so
problems that only the build has (the CSP above all) show up only in the browser tests. That is
one reason the browser tests run against the build.

<details><summary>Alternatives for the dev loop</summary>

| Option | Fit | Effort | Handover | Risk |
|---|---|---|---|---|
| **Vite dev server with a proxy** (chosen) | Changes show at once; same origin, so sign-in and cookies work unchanged | Low | Vite's documented setup | Low; OIDC needs `make up` |
| A watch build served by FastAPI (0.1.0) | Production-like, CSP included | Low | Simple | Every change rebuilds the bundle; no devtools, since the CSP blocks their styles |
| Vite on its own origin with CORS on the API | Changes show at once | Medium | Vite's setup plus CORS settings in the backend | High: cross-origin cookies and CORS would change the backend's sign-in and CSRF rules, which stay as ADR 01 defines them |

</details>

### Testing: two seams

Tests use the interface the way a person does, as ADR 01 asked
([Testing Library's guiding principles](https://testing-library.com/docs/guiding-principles)):
they start from a URL, find elements by role and name, type and click, and assert on what is shown
and announced and on the requests the API received (method, path, `If-Match`,
`Idempotency-Key`). They never mock the generated client, the query helpers or the router.

**Seam 1: the whole app at a URL, with a fake `fetch`** (Vitest, Testing Library, axe-core).
`renderApp(url)` in [`src/test/render.tsx`](../../frontend/src/test/render.tsx) renders the real
router on a memory history, with a fresh query client (retries off), the real interceptors and
the translations. The existing fetch fake answers by `METHOD /path` and fails a test on any request
it does not expect. This covers the guards and redirects, admin and viewer, a 401 in the middle of
a session, each screen's behaviour, the theme, and axe on every rendered state.
`query-client.test.ts` tests the retry rules and the deadline with fake timers. The flaky "run
now" test is rewritten with [Vitest's fake timers](https://vitest.dev/guide/mocking/timers) and
passed 20 runs in a row.

**Seam 2: a real browser against the production build** (Playwright, `make e2e`). Playwright's
[web server](https://playwright.dev/docs/test-webserver) builds the frontend and starts
`infrasales web` with a test profile: built-in sign-in with alice (admin) and vera (viewer), a
throwaway SQLite database, migrations applied, and the build directory. A setup project signs each
role in once through the real form and saves the session
([authentication](https://playwright.dev/docs/auth)). Every spec runs in the light and the dark
theme, and a fixture fails it on:

- any [`securitypolicyviolation`](https://developer.mozilla.org/en-US/docs/Web/API/Element/securitypolicyviolation_event)
  event;
- any console error or page error;
- any 5xx answer;
- any axe finding (WCAG 2.0 and 2.1, A and AA) on any page it shows, and any page it leaves
  without scanning it.

Coverage in the browser is thin on purpose: sign-in and sign-out through the form, one path per
page and role, a viewer sent away from `/audit`, the shell on a small screen, and one save and one
run. Spec files end in `.e2e.ts`, so Vitest never picks them up. `make e2e` is kept out of
`make test`, and CI runs it in its own Chromium-only job.

**Cost:** the browser tests need a build and a running backend, so they take minutes rather than
seconds, and they add a pinned Playwright browser to install. Two seams mean two places a behaviour
could be tested; the rule is that behaviour belongs in seam 1, and seam 2 only checks what needs a
real browser.

<details><summary>Alternatives for testing</summary>

| Option | Fit | Effort | Handover | Risk |
|---|---|---|---|---|
| **Playwright** (chosen) for the browser seam | Real Chromium against the build; CSP events, console, network and axe in one test | Low | `@playwright/test` 45.4 million, `@axe-core/playwright` 8.7 million weekly downloads | Low |
| [Cypress](https://docs.cypress.io/app/get-started/why-cypress) | Real browser | Low | 3.2 million weekly downloads | Low |
| [Vitest browser mode](https://vitest.dev/guide/browser/) | Real browser for component tests, but without FastAPI's headers, cookie and sign-in | Medium | Same tool as the unit tests | Medium: does not test the production build |
| Browser tests against the Vite dev server | Faster | Low | Same tool | High: the dev server sends no CSP, so the main reason for the tests is lost |
| [MSW](https://mswjs.io/docs/) in place of the fetch fake | Request handlers by URL | Low | Well known | Low; not needed, since the fake already answers by method and path and fails on surprises |

</details>

## What this supersedes in ADR 01

ADR 01 stays unchanged as the record of the 0.1.0 baseline. These of its statements no longer
describe the interface; this ADR replaces them:

| ADR 01 says | Section | Now |
|---|---|---|
| "The interface's API types are generated from the backend's OpenAPI contract." Likewise: "from which the interface's types are generated", "the interface's lint fails when its generated types are [out of date]", and "generated types" in the table of guarantees | [Frontend: React](01_adr_baseline.md#frontend-react), [Backend](01_adr_baseline.md#backend-fastapi-authlib-and-sqlmodel), [Internal architecture](01_adr_baseline.md#internal-architecture), [Guarantees](01_adr_baseline.md#guarantees-and-their-limits) | A whole client is generated (types, SDK, query helpers) by hey-api; the lint checks all of it. openapi-typescript and openapi-fetch are removed |
| The development loop: `make dev` built the interface, then rebuilt it on every change (a watch build) for FastAPI to serve; "the static interface is served from `/`" was true in development too | [Internal architecture](01_adr_baseline.md#internal-architecture) (the `make dev` target of 0.1.0) | The Vite dev server with an API proxy in development; FastAPI serves the build only in the image, `make up` and the browser tests |
| "Colour contrast needs a real layout and is checked by hand", and frontend testing with Vitest and Testing Library only, without tests in a real browser | [Frontend: React](01_adr_baseline.md#frontend-react), [Requirements related to testing](01_adr_baseline.md#requirements-related-to-testing--ensuring-correctness) | Playwright against the production build with axe in both themes, CSP and console guards, and a unit test for non-text contrast. The accessibility review before going live stays |

Everything else in ADR 01 stays, in particular React with TypeScript and Vite, i18next for every
text, sign-in, sessions, cookies and the CSP.

## What this changes in ADR 03: a Feeds page

[ADR 03 §9](03_adr_scraper_sink.md#9-managing-feeds) left Feeds to the API for now, with no
interface. The interface now has a Feeds page for admins (`/feeds`, BIG-45). It reads the same
`GET /api/feeds` without changes and lists every Feed with its kind, address, state, the reason it
fails and when it was last read. Viewers neither see the link nor can open the page. The reason
for the change: Source Collection now reads many Feeds every few hours. A Feed that keeps failing
raises no alert as long as other Feeds still work, and a blocked one alerts only once, when it
becomes blocked (ADR 03 §6). Admins need to see which Feeds need attention without calling the API
by hand. The page explains a blocked Feed the way §6 decides it: a person decides what to do, and
nobody works around a bot wall. Adding a Feed from the interface (BIG-49) uses the existing add and
suggest endpoints in the same way. Editing, disabling and deleting Feeds still have no endpoints, so
the interface does not offer them.

## References

All sources were accessed on 2026-10-16. Download figures are npm's weekly downloads for
9–15 October 2026, from `https://api.npmjs.org/downloads/point/2026-10-09:2026-10-15/<package>`.

**Standards and platform**

- W3C, Understanding WCAG 2.1: [1.4.3 Contrast (Minimum)](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html),
  [1.4.11 Non-text Contrast](https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html)
- MDN: [CSP `style-src`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/style-src),
  [`securitypolicyviolation` event](https://developer.mozilla.org/en-US/docs/Web/API/Element/securitypolicyviolation_event)
- Node.js, [subpath imports](https://nodejs.org/api/packages.html#subpath-imports)
- npm, [download counts API](https://github.com/npm/registry/blob/main/docs/download-counts.md)

**React, routing and server data**

- React, [Build a React app from scratch](https://react.dev/learn/build-a-react-app-from-scratch)
- TanStack Router: [file-based routing](https://tanstack.com/router/latest/docs/framework/react/routing/file-based-routing),
  [type safety](https://tanstack.com/router/latest/docs/framework/react/guide/type-safety),
  [search params](https://tanstack.com/router/latest/docs/framework/react/guide/search-params),
  [router context](https://tanstack.com/router/latest/docs/framework/react/guide/router-context),
  [external data loading](https://tanstack.com/router/latest/docs/framework/react/guide/external-data-loading),
  [automatic code splitting](https://tanstack.com/router/latest/docs/framework/react/guide/automatic-code-splitting),
  [comparison](https://tanstack.com/router/latest/docs/framework/react/comparison),
  [devtools](https://tanstack.com/router/latest/docs/framework/react/devtools)
- React Router, [modes](https://reactrouter.com/start/modes); [wouter](https://github.com/molefrog/wouter)
- TanStack Query: [query options](https://tanstack.com/query/latest/docs/framework/react/guides/query-options),
  [retries](https://tanstack.com/query/latest/docs/framework/react/guides/query-retries),
  [infinite queries](https://tanstack.com/query/latest/docs/framework/react/guides/infinite-queries),
  [devtools](https://tanstack.com/query/latest/docs/framework/react/devtools)
- Dominik Dorfmeister (TanStack Query maintainer): [The Query Options API](https://tkdodo.eu/blog/the-query-options-api),
  [Creating Query Abstractions](https://tkdodo.eu/blog/creating-query-abstractions)
- [SWR](https://swr.vercel.app/), [RTK Query](https://redux-toolkit.js.org/rtk-query/overview)

**API client**

- hey-api: [get started](https://heyapi.dev/openapi-ts/get-started),
  [output configuration](https://heyapi.dev/openapi-ts/configuration/output),
  [Fetch client](https://heyapi.dev/openapi-ts/clients/fetch),
  [TanStack Query plugin](https://heyapi.dev/openapi-ts/plugins/tanstack-query)
- FastAPI, [Generating SDKs](https://fastapi.tiangolo.com/advanced/generate-clients/)
- Microsoft, [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
- Alternatives: [openapi-fetch](https://openapi-ts.dev/openapi-fetch/),
  [openapi-react-query](https://openapi-ts.dev/openapi-react-query/) and its
  [queryOptions](https://openapi-ts.dev/openapi-react-query/query-options),
  [Orval with React Query](https://orval.dev/docs/guides/react-query),
  [Kubb React Query plugin](https://kubb.dev/plugins/plugin-react-query/)

**Components and styling**

- shadcn/ui: [Vite installation](https://ui.shadcn.com/docs/installation/vite),
  [components.json](https://ui.shadcn.com/docs/components-json),
  [theming](https://ui.shadcn.com/docs/theming),
  [July 2026: Base UI as the default](https://ui.shadcn.com/docs/changelog/2026-07-base-ui-default)
- Base UI: [quick start](https://base-ui.com/react/overview/quick-start),
  [CSP Provider](https://base-ui.com/react/utils/csp-provider)
- Tailwind CSS: [installation with Vite](https://tailwindcss.com/docs/installation/using-vite),
  [dark mode](https://tailwindcss.com/docs/dark-mode)
- Radix: [Primitives](https://www.radix-ui.com/primitives/docs/overview/introduction),
  [Select](https://www.radix-ui.com/primitives/docs/components/select);
  [react-remove-scroll](https://github.com/theKashey/react-remove-scroll),
  [react-style-singleton](https://github.com/theKashey/react-style-singleton),
  [vaul](https://github.com/emilkowalski/vaul), [sonner](https://github.com/emilkowalski/sonner)
- Alternatives: [MUI and CSP](https://mui.com/material-ui/guides/content-security-policy/),
  [Mantine provider](https://mantine.dev/theming/mantine-provider/),
  [React Aria Components](https://react-spectrum.adobe.com/react-aria/getting-started.html)

**Dev loop and testing**

- Vite: [features (HMR)](https://vite.dev/guide/features#hot-module-replacement),
  [server proxy](https://vite.dev/config/server-options#server-proxy),
  [module preload](https://vite.dev/config/build-options#build-modulepreload)
- TanStack Devtools: [overview](https://tanstack.com/devtools/latest/docs/overview),
  [Vite plugin](https://tanstack.com/devtools/latest/docs/vite-plugin)
- Testing Library, [guiding principles](https://testing-library.com/docs/guiding-principles);
  Vitest, [fake timers](https://vitest.dev/guide/mocking/timers),
  [browser mode](https://vitest.dev/guide/browser/)
- Playwright: [web server](https://playwright.dev/docs/test-webserver),
  [authentication](https://playwright.dev/docs/auth),
  [accessibility testing](https://playwright.dev/docs/accessibility-testing)
- axe-core, [rule descriptions](https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md)
- Alternatives: [Cypress](https://docs.cypress.io/app/get-started/why-cypress), [MSW](https://mswjs.io/docs/)
