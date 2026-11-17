---
name: matomo-mcp
description: "Guide Claude when querying Matomo analytics data via the official MCP Server plugin (matomo-org/plugin-McpServer). ONLY activate if at least one Matomo MCP server is connected (its tools, e.g. matomo_site_list, are loaded or can be found by searching the available tools). Read-only: never creates or changes anything in Matomo. Use when the user asks about traffic, conversions, segments, goals, campaigns, page performance, GDPR compliance, or any Matomo report — including multi-account setups. Also trigger on \"ask Matomo\", \"query Matomo\", \"check stats in Matomo\", or any reference to a Matomo site ID, segment, goal, report, or Tag Manager. Do NOT activate without a connected Matomo MCP server.\n"
---

# Matomo MCP Skill

A guide for querying Matomo analytics data through the official MCP Server plugin: call the
right tools in the right order, handle multi-account setups, and know when to question the
data returned.

Work in this order: scope (read-only) → find the server → choose the account → choose the
site → clarify the request → choose the report path → discover, then query → qualify the
figures.

## Scope: read-only

This skill reads data. It never changes anything in Matomo.

- Use only tools that read: the Layer 1 tools and, when raw API access is exposed,
  `matomo_api_list`, `matomo_api_get` and `matomo_api_call_read`.
- **Never call** `matomo_api_call_create`, `matomo_api_call_update`, `matomo_api_call_delete`
  or `matomo_api_call_full`, nor any tool that creates or edits a segment, goal, dimension,
  report or site, **even if such a tool is exposed and even if the user asks**. If the user
  wants something created or changed, say that it is outside this skill, explain what needs to
  be created and by whom (the user in the Matomo UI, or an administrator), and stop there.
- Do not try to trigger archiving. Reading a report is allowed; forcing aggregation is not.

## Find the Matomo MCP server

- Look for tools whose name contains `matomo_` (e.g. `matomo_site_list`). Tool names carry the
  connector's name as a prefix: match on the `matomo_` part, not on the start of the name.
- **Tools may not be loaded yet.** If none is visible, search the available or deferred tools
  and connectors for "matomo" before concluding. Only when that search also finds nothing,
  tell the user: "No Matomo MCP server is connected. To use this skill, connect a Matomo
  instance via the MCP Server plugin (matomo-org/plugin-McpServer) and ensure its tools are
  active."
- **Layer 1** tools (sites, reports, goals, segments, dimensions) are always there when the
  MCP is on. **Layer 2** (raw API: `matomo_api_*`) exists only if a super admin enabled it,
  possibly scoped method by method. Of Layer 2, use only the three read tools above. Tool
  list, what each returns, Tag Manager inspection: `references/tool-surface.md`.
- The tool names here come from a live exploration of the plugin (5.1.2, November 2026). If
  the tool list you see differs, trust it and its descriptions.

---

## Account gate (critical when several MCPs are connected)

Each connected Matomo account is a **separate MCP server** with its own tools. Resolve the
account first, then the site — never the other way around.

**Step 1 — List the accounts (no API call).** Identify each one by its **connector name**
(e.g. "Matomo MCP - Acme"; the tool prefix is a mangled form of it). The instance domain
(e.g. `lorem.matomo.cloud`) is usually not visible: use it only when the name or URL shows it.
**Never invent or guess a domain**, and do not confuse the sites' own domains (`main_url`) with
the Matomo instance. Show opaque names (e.g. "Matomo 2") as they are and ask which instance it
is. Present the list and ask which account to query.

Skip this step ONLY if a single MCP is connected, or if the user explicitly designated the
account (by its MCP name or its domain). **A client/brand name in the request is NOT a
designation of the account**: that brand's data may live in another account, and a name match
may be coincidental. State which account you believe matches and why, and **ask the user to
confirm before any query. Then stop and wait.**

**Step 2 — List the chosen account's sites** (`matomo_site_list` on that MCP only) and apply the
site-selection gate. Resolving the account does NOT resolve the site.

**Step 3 — Scope all subsequent calls** to the confirmed MCP. Never call other MCPs
speculatively. Never mix data from different accounts in the same calculation.

**Step 4 — Always state the source**: name the account used (domain if visible, otherwise
connector name) — **even when only one MCP is connected**. One short clause, not a question.

---

## Site-selection gate (mandatory, independent of how many accounts exist)

This gate applies **even with a single connected account, and even when the user named the
client unambiguously**. Naming a client resolves the *account*, never the *site*: one account
routinely holds several sites (production, old site, intranet, landing pages, member area...),
and a metric like "leads" can live on any of them. One idSite can also cover several real sites,
and its `name` and `main_url` do not reliably tell you its perimeter; nor do you know its
consent regime, ecommerce setting or goal setup until you check. Detail, and how far
`SitesManager.getSiteUrlsFromId` can help: `references/interpretation-and-limits.md` §5.

**Rule:** before the first `matomo_report_processed` call, the target `idSite` must come from
ONE of these two sources only:
- the user gave an explicit site name or idSite, **or**
- the user picked one from a list you presented.

If neither holds, call `matomo_site_list`, present every site (idSite + name), and ask the user
to **pick one or more sites**, or to **ask you for more detail** about them. **Then stop and
wait. Do not query yet.** When name and `main_url` look ambiguous, offer
`SitesManager.getSiteUrlsFromId` (declared URLs only, raw API needed) and say that the tracked
perimeter itself can only be confirmed by the user or an administrator.

**You may NEVER infer the site from:**
- the client/account name,
- "the main site" / "the production site" / "the obvious one",
- which site happens to have a matching goal, segment, or report configured,
- the fact that other candidate sites returned empty.

Finding a plausibly-matching goal on one site is not permission to skip the question — it is
exactly the silent guess this gate exists to prevent. When the metric itself is ambiguous
("leads", "conversions"), confirm the site **and** the functional definition in the same
question. When perimeter or consent matters for a figure, say so explicitly.

---

## Discover, then query

Never guess report names, metric names, or segment definitions. Always discover before
querying.

```
0. [if multi-account] choose MCP from server list (no API call)
1. matomo_site_list          → if the user did not name a site/idSite, ASK which one and wait
2. matomo_report_list        → find the relevant report
3. matomo_report_metadata    → exact metric names, accepted parameters
4. matomo_report_processed   → execute with confirmed parameters
```

For goals and segments, insert the `*_list` → `*_get` steps before step 4.

**Shortcut**: skip steps 1–3 ONLY if the user gave an exact idSite AND a report you recognise
with certainty (e.g. `VisitsSummary.get`). Recognising the report never licenses skipping site
selection. Any doubt about a metric name or date format: go through metadata.

### Asking: group the questions, never drop one

The gates exist because a wrong guess costs more than a question. Keep every one of them, but
**ask them together**: when several points are open at the same moment (account, site, pages vs
entry pages, which goal), put them in **one message** and wait once. A gate that only opens
after an earlier answer (e.g. the goal list of the chosen site) is asked when it opens.

**If nobody is there to answer** (scheduled or unattended run): do not guess and do not query.
Report which points are open and what each one changes, and stop.

---

## Choosing the report path

Pick the starting point in this order (reliability and ease of reading, not quality):

1. **Standard reports** (`VisitsSummary`, `Actions`, `Referrers`, `Goals`...) — whenever the
   question fits a **single** module. A cross of two dimensions does not: go to
   "Cross-dimension requests".
2. **Goals within standard reports** for conversions (`matomo_goal_list` first).
3. **Saved segments on standard reports** for a sub-population (`matomo_segment_list` first;
   segments work at visit level).
4. **Custom reports** only when 1–3 cannot answer, or on explicit request: 13-month limit, no
   goal metrics, not every combination is meaningful.

This order is **mandatory**. Before saying the exact data is not available, you must have
checked all four levels — and even then, suggest what to create.

---

## Cross-dimension requests ("X by Y")

"Top pages **by** source", "conversions **par** appareil", "X ventilé / réparti par Y". The trap
is to recognise the cross and then fetch the two dimensions separately.

**Step 0 — Clarify first if ambiguous.** Do not extract anything until the request is clear:
- device terms are fuzzy ("phone" = smartphone only, or + phablet, + tablet?): map them to the
  real categories, ideally to the saved segments that exist;
- "pages" vs "entry pages": **mandatory clarification when pages are crossed with a traffic
  source**, since a source describes where a visit *started*. Ask; never pick silently.

**Step 1 — Look for a native cross. Inspect, do not assume**: a subtable report, a goal cross
(`metricsGoal` + `idGoal`), or an existing custom report. How to spot each:
`references/crosses-and-completeness.md` §0. If one exists, use it.

**Step 2 — Otherwise, choose by granularity:**
- **granular × limited** (pages × source, pages × device): run the X report once per value of
  Y, each time with **one saved segment** for that value. For traffic source, Y is the channel
  **type** (`referrerType`); for device, `deviceType`. Enumerate Y's values for the **same
  period** (method and fixed lists: `references/crosses-and-completeness.md` §1).
  - **Then verify segment coverage** in `matomo_segment_list`. **Incomplete coverage is a stop
    condition, not a footnote:** do NOT output the partial cross, even with a caveat. Tell the
    user which values are covered and which are missing, that the missing segments must be
    created by them or an administrator, and **ask whether to (a) proceed with the partial
    result, or (b) have the missing segments created first. Wait for an explicit choice.**
- **granular × granular** (pages × events): a **custom report** with both dimensions. Watch its
  "Others" row and any filters configured on it.
- Goals attach only to actions / pages / events: they cannot cross two visit properties.

**Step 3 — If what is needed does not exist** (segment, custom report, goal): stop and present,
as prose only (no data tables), what the standard reports *can* give separately, what the exact
answer would require, and what to create (and that an admin may be needed). Ask whether to
proceed with the approximation or set up the missing piece first, and wait.

**Never ship two side-by-side tables (top X, top Y) as the answer to an "X by Y" question.** A
footnote does not make it acceptable: produce the real cross, or stop and ask.

---

## Segments, goals, and custom dimensions

Their availability affects results silently.

### Segments
- **A segment is not a filter: it selects whole visits**, and the report aggregates everything
  in those visits. To count one action or event, filter the report dimension instead. When to
  explain this to the user: `references/interpretation-and-limits.md` §2.
- **Only saved, already archived segments can be queried.** Any other expression is rejected
  ("Segment is not allowed in this Matomo configuration: only existing pre-archived segments
  can be used") — that means "use a saved definition", not "no data".
- **Workflow:** find the matching segment in `matomo_segment_list`, get its stored definition
  with `matomo_segment_get`, and pass it **exactly as returned** (it is URL-encoded, often
  twice: never decode or re-type it). Never pass an expression you write yourself. A segment
  with `idsite: null` is shared across all sites. If two segments plausibly match, show their
  definitions and ask.
- **A — The segment does not exist** (absent from the list): suggest the user create it
  (Administration → Segments) or ask an administrator. **Never create it yourself** (plan
  limits apply; it is their decision).
- **B — The segment exists but the data looks suspiciously low**: it may not be archived over
  the whole period, which you cannot see directly. **With the user's agreement**, re-query just
  the first day of the period; empty where traffic is expected → probably an archiving gap, to
  raise with an administrator. **Never trigger archiving yourself.**

### Goals
- Goals may not exist on every site: `matomo_goal_list` first. They are aggregated in every
  report except custom reports, and only where the report metadata shows goal metrics.
- **Read `allow_multiple`** (in `matomo_goal_list` and `matomo_goal_get`): true = several
  conversions per visit (hit level), false = at most one per visit (visit level). It directly
  changes the count.
- "Conversion" is too broad to query: ask the user to describe it functionally, then map it to
  a goal, an event or a page (`references/interpretation-and-limits.md` §3).
- **Confirm the goal matches the request before outputting any figure.** Mapping "leads" to a
  goal is your hypothesis: goal names are ambiguous (a "devis" goal may be a request, a started
  funnel or a completed subscription). Present the goal(s) with name and definition
  (`match_attribute`, pattern, `allow_multiple`), say it is your interpretation, and **ask the
  user to confirm. Wait.** One plausible match is not a confirmation; several → ask which.
- `nb_conversions = 0` on a recent range: check the definition, and remember goals are not
  retroactive, before concluding there were none.

### Custom dimensions
- Site- and scope-specific (visit vs action). `matomo_dimension_list` before referencing one;
  check the `active` flag.

---

## Visitor log (visit-level data): not queried by default

The visitor log (`Live.*` methods returning visits or visitors, visitor profiles) is personal
data. In the setups this skill is written for, it is **meant to be disabled** for the MCP, and
using it through an AI connector is treated as **not permitted**.

- **Never call it on your own initiative**, not even to verify a perimeter or recover a URL.
  When only the visit log could settle a question, say so and leave it to the user or an
  administrator. **Never call a `Live` method that returns visits or visitors.**
- **Do not test whether it is enabled** unless the user explicitly asks for visit-level data.
- **If the user explicitly asks for it**: do not fetch it. Check what can be checked without
  reading any visit, then alert:
  - `matomo_api_list` (module `Live`) does not list the method, or no raw API tool exists →
    "This access is not permitted, and it is correctly disabled on this connector."
  - the method is listed → "This access is not permitted. The method is reachable through this
    connector; whether Matomo itself has the visit log disabled cannot be confirmed from here
    without reading visits. Ask the Matomo administrator to check the privacy setting and to
    remove the `Live` methods from the connector's raw API scope." Listing alone does not prove
    it works; how to check the visitor profile safely, and what not to use as a probe:
    `references/troubleshooting.md` §3.
- In all cases, offer the aggregated report that comes closest to the need.
- Same care with what reports return: a URL or event name containing an e-mail address, an
  identifier or a token is reported as a problem (`references/interpretation-and-limits.md`
  §12), without reproducing the value.

---

## Completeness and the "Others" / "Autres" row (read before counting page URLs)

A count built from the page URLs report is only complete if no relevant "Others" row sits
between the level you start from and your target rows (Matomo collapses each directory's tail
into it).

**The flat-report trap.** `flat=1` with `filter_pattern` SILENTLY DROPS the "Others" row. A clean
filtered flat result proves only that N rows matched — NOT that the data is complete. Before
presenting such a count as complete, walk the hierarchy non-flat:
`references/crosses-and-completeness.md` §2.

---

## When a call fails or the data looks wrong

An empty result is never "zero traffic", an unknown metric means a guessed name, and a missing
raw API tool is a configuration matter, not something to retry. Causes and what to tell the
user: `references/troubleshooting.md`, as soon as a call fails, returns nothing, or returns an
implausible figure.

---

## Reference files

- `references/tool-surface.md` — the tools of both layers, what each returns, Tag Manager
  inspection.
- `references/prompt-patterns.md` — call sequences for common questions, dates and periods,
  pagination and report parameters.
- `references/interpretation-and-limits.md` — read **before presenting any figure as fact**:
  history, segment semantics, goals and attribution, custom reports, site perimeter, Tag
  Manager checklist, flat vs cascade, unique visitors, source biases, metric definitions, GDPR,
  versioning, consent and double tagging, ready-made hedges.
- `references/crosses-and-completeness.md` — native crosses, enumerating a dimension's values,
  completeness against the "Others" row.
- `references/troubleshooting.md` — empty or implausible results, errors, missing raw API
  tools, visitor log status.

## What to say when uncertain

Don't present figures without qualification when confidence is low: use the hedges in
`references/interpretation-and-limits.md` §15. Never silently round, aggregate, or compare
figures across different idSites without saying so.
