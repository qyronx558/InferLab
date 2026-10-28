# InferLab dashboard design system

This is the frontend-only design-system preview with Prompt 04 typed mock queries.
Primary fixtures live in `contracts/fixtures/demo.json`, are validated by Pydantic,
and are emitted to the frontend as generated typed data. `apps/web/src/data/demo.ts`
adapts them for presentation; summary cards and hardware
context are also illustrative page content. All values, dates and lifecycle
statuses are synthetic, not measurements or live device state. A persistent
DEMO DATA badge and notice appear on every route.

## Tokens and foundations

React/TypeScript, Tailwind CSS 4 via its Vite plugin, and source-owned shadcn/ui
New York primitives form the UI foundation. `src/styles.css` defines semantic
tokens shared by Tailwind utilities and workspace styles:

| Token | Value | Use |
| --- | --- | --- |
| Background | `#f7f9fc` | Light slate workspace |
| Card | `#ffffff` | Tables and metric surfaces |
| Foreground | `#17243b` | Primary text |
| Muted foreground | `#59677c` | Secondary text |
| Primary | `#2b55ac` | Actions and links |
| Sidebar | `#101e34` | Navy navigation |
| Border | `#e0e6ef` | Quiet surface separation |
| Ring | `#3563c9` | Keyboard focus |

Use system fonts, monospace for identifiers/metrics, 8-12 px control corners and
compact table rows. Status badges combine text, icons and semantic colors; color
alone never carries state. Chart bars have a text equivalent. Motion respects
`prefers-reduced-motion`; no remote fonts or imagery are requested.

## Components and routes

- `AppShell`: persistent demo notice, skip link, landmarks, page footer and responsive layout.
- `Sidebar`: active route indication and main navigation; fixed on desktop.
- `Header`: current page, DEMO DATA badge and preview-state selector.
- `StatusBadge`: completed/running/queued/failed synthetic states.
- `MetricCard`: label, fixture value, optional unit and context.
- `EmptyState`, `ErrorState`, `Skeleton`: explicit feedback with recovery controls or loading labels.
- `ExperimentTable`: semantic headers/caption, dense rows, scrollable on small screens.
- `PlotlyChart`: lazily loaded Plotly renderer with an accessible text fallback.
- `ComparisonChart`, `ComparisonContext`, `ComparisonMetricTable`, `ComparisonNotice`:
  six metric views with revision, quantization, prompt, sample and hardware context;
  unavailable values are never plotted as zero and uncontrolled comparisons carry a
  no-causation notice.

The source-owned shadcn primitives (Button, Badge, Card, Table, Skeleton, Sheet)
live under `src/components/ui`; their attribution is in `THIRD_PARTY_NOTICES.md`.
`components.json` and the `@` alias support future component additions.

Routes: `/` (Overview), `/experiments`, `/compare`, `/compare/report`, `/models`,
`/reports`, and `/methodology`; unknown paths show a recovery link. Experiment
search/status filters, model selection, report expansion, comparison exports and the
printable report work locally. The public mock adapter makes no HTTP requests; the
authenticated admin console under `/admin` uses a separate typed HTTP client.

The header/mobile preview selector or `?state=empty`, `?state=error`, and
`?state=loading` lets reviewers inspect reusable feedback states. Those states are
intentional fixtures; no network failure or indefinite backend wait is implied.

## Accessibility and verification

Below 1024 px navigation becomes a shadcn/Radix modal Sheet with focus trapping,
Escape dismissal and focus restoration. Native links, form controls and report
details support keyboard operation. Page changes update the document title; the
desktop heading receives focus on navigation. Wide tables scroll within their
own focusable regions rather than widening the page.

```powershell
npm.cmd run dev:web
npm.cmd test
npm.cmd run build
# Optional local CPU browser checks (browser download required once):
npm.cmd exec --workspace @inferlab/web -- playwright install chromium
npm.cmd run test:e2e
```

Vitest checks navigation/disclosures, filters, comparison changes and context,
CSV/JSON exports, feedback recovery and printable report availability. Playwright
checks all seven routes on desktop and mobile, keyboard skip navigation, mobile focus
containment/restoration, comparison/report download labeling, page overflow and
automated WCAG A/AA checks using axe. It also checks that public routes make no backend
requests. Automated checks complement manual layout and keyboard review; they are not
a full accessibility certification. Browser artifacts stay under ignored `.cache/`;
hosted CI continues to run CPU unit tests/build without downloading models or browsers.
