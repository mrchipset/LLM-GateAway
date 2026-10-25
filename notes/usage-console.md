# Usage console panel

Status: implemented in `ui/src/components/{Workspace,UsagePanel,UsageChart,UsageStats,UsageByKeyTable}.tsx`
and `ui/src/hooks/useUsage.ts`.

## Problem and constraints

Operators need to see consumption per tenant, over time, and per key without
leaving the console. The existing UI is a single screen with a connection panel
and a model list; it deliberately has no router, no chart library, and no
browser storage for the master key. The new panel must fit that design and use
the reporting endpoints that already exist.

## Assumptions

- Usage is read-only. Editing tenant limits stays in the API; the panel only
  displays the selected tenant's limits.
- Daily granularity is enough for the console. Hourly buckets remain available
  in the API for other clients.
- A rolling range measured from "now" is the useful default; calendar-month
  boundaries belong to quota logic, not to this chart.
- The series endpoint is dense and UTC-aligned, so the chart can trust array
  positions and never invents gaps.
- `cached_tokens` is a subset of `prompt_tokens`; the UI labels it as such and
  never adds it to the total.

## Options considered

**A separate route/page vs tabs.** A router would add a dependency and history
semantics for two views. Tabs keep health and the connection panel visible,
preserve the single-screen character, and need no new dependency.

**A chart library vs a hand-rolled SVG.** The chart is one bar series; a library
would add weight and fight the design system. A small SVG component gives exact
control over labels, keyboard access, reduced motion, and empty ranges.

**Compute aggregates client-side vs use the reporting endpoints.** Client-side
aggregation would fetch raw usage and duplicate the backend's half-open and
timezone rules. The endpoints already return dense points and per-key totals, so
the console stays a presentation layer.

**Mount queries only on the Usage tab vs in the workspace.** Mounting them in the
workspace means a newly connected key loads usage immediately and switching tabs
never refetches. The cost is background requests while Models is visible, which
is acceptable at this scale.

## Chosen approach

- A `Models | Usage` tablist with arrow/Home/End keyboard navigation; hidden
  panels stay mounted so their data survives tab switches.
- Tenant selector with `All tenants` as the default; selecting a tenant filters
  all three usage queries and shows its limits as read-only facts
  (`100,000 tokens/month`, `60 req/min`, or "No limits").
- Range presets 7/30/90 days; the client floors the anchor to UTC midnight and
  computes a rolling `since` from it, omitting `until` so the server uses its
  own clock. Refresh recomputes the anchor (a same-day refresh explicitly
  refetches because the query key does not change). Bucket is fixed to `day`,
  so the final bar covers "today so far".
- Totals cards: requests, input, output, cached (labeled "subset of input"),
  total. Cached counts are rendered as reported; the client only enforces
  non-negative integers, so one odd provider aggregate cannot blank the whole
  panel. Exact values live in `title`/`sr-only` text.
- Daily total-token SVG bars: one bar per dense point including zero-token days,
  first/middle/last UTC labels, peak annotation, per-bar `<title>` and
  `aria-label`, reduced-motion support, and a single-point-safe layout.
- Per-key table with name/prefix/short-id fallback, requests, input, output,
  cached, and total; cards below `md`. The server order (total desc) is kept and
  the request is limited to 100 keys.
- Loading skeletons, empty states ("No usage in this range"), and error states
  with HTTP status, message, code, request id, and retry, matching the model
  panel.
- The master key remains in React state only; usage query keys contain tenant,
  range, and limit but never the key; disconnect removes model, tenant, and usage
  queries.
- A polite, visually hidden status announces "Usage updated at ... UTC for the
  last N days" when all three usage queries settle successfully.
- When the tenant list exceeds the fetched page, the selector shows
  "Showing N of M tenants" instead of silently hiding the remainder.

## Trade-offs and risks

- `since` comes from the client clock (floored to UTC midnight); a skewed
  browser shifts the window. The server still enforces its own validation and
  defaults.
- The final bucket is partial by definition; the chart labels it rather than
  pretending the day is complete.
- Tenant and per-key lists are capped at 100; both surface a truncation note,
  but neither paginates in the console.
- No hour bucket in the UI even though the API supports it; a 7-day hourly view
  would need a new control and point-cap messaging.
- The 90-day view produces up to 91 bars; labels are intentionally sparse.
- Only the first 100 keys are shown; the table has no pagination. A tenant with
  more keys needs the API with an explicit limit.
- Limits are display-only; changing a quota still requires
  `PATCH /api/v1/tenants/{id}`.
- No cost conversion, per-model chart, or CSV export.
- Reloading the page requires re-entering the master key (by design).

## References

- `ui/src/components/UsagePanel.tsx`, `UsageChart.tsx`, `UsageByKeyTable.tsx`
- `ui/src/hooks/useUsage.ts`, `useTenants.ts`
- `src/llm_gateway/api/admin/usage.py`, `schemas/usage.py`
- `notes/usage-accounting.md`, `notes/quotas-and-rate-limits.md`
