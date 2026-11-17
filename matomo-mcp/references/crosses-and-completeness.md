# Matomo MCP — Crosses and completeness

Detail for checks that SKILL.md only summarises. Read §0 when looking for a native cross, §1
when building an "X by Y" cross with one segment per value, §2 before presenting a count from
the page URLs report as complete.

## 0. Finding a native cross

Context: SKILL.md, "Cross-dimension requests", Step 1.

Use `matomo_report_list` + `matomo_report_metadata` to check, in this order:
- a **subtable cross** — some two-dimension crosses exist as built-in subtables (the
  `...FromXId` reports, e.g. Keyword × Search engine, Event category × Event action). Check
  `actionToLoadSubTables` / the related `*FromId` reports.
- a **goal cross** — if Y is a conversion, a report's metadata exposes `metricsGoal`; pass
  `idGoal` to that report to get goal metrics per row (e.g. conversions per page).
- an **existing custom report** — scan the `CustomReports` module entries in
  `matomo_report_list`; one may already combine the two dimensions you need.

If a native cross exists, use it.

## 1. Enumerating the values of a dimension

Context: SKILL.md, "Cross-dimension requests", Step 2 (granular × limited).

- **Enumerate Y's values reliably. Two cases, depending on what you need:**
  - *Values that matter for a period-bounded cross* = the values that had traffic in the
    analysed period. Get them by running Y's own report **for that same period** (e.g.
    `Referrers.getReferrerType` for May 2026). Each returned row carries its segment
    expression in `reportMetadata` (e.g. `referrerType==search`, `deviceType==desktop`) —
    use that directly. Zero-traffic values are dropped, but they contribute nothing to the
    cross, so this is complete for the period. Do not enumerate from a *different* period
    (e.g. yesterday) than the one you will report.
  - *The full theoretical domain* (including values with zero traffic — needed to
    pre-validate segment coverage): use `API.getSuggestedValuesForSegment(segmentName,
    idSite)` (raw API). For closed dimensions it returns the complete list (verified:
    `referrerType` → 6, `deviceType` → 14). **Raw API may be disabled** (super-admin
    controlled); if so, fall back to the known fixed enums:
    `referrerType` = direct, search, website, campaign, social, ai;
    `deviceType` = desktop, smartphone, tablet, phablet, console, tv, car browser,
    smart display, camera, portable media player, feature phone, smart speaker, wearable,
    peripheral.
  - **Do NOT expect the report to list the full domain.** Verified on this MCP: both
    `Referrers.getReferrerType` (despite `constantRowsCount: true`) and
    `DevicesDetection.getType` (despite its documentation saying it shows all types even
    with no visits) return ONLY rows with traffic in the period. The "shows all values" is
    a UI behaviour, not reflected in the processed output. So a report extract can never be
    trusted to enumerate the complete domain.

What "verified" means here: observed in read-only use on Matomo Cloud accounts. Another
instance or a later plugin version may behave differently: if a report does return
zero-traffic rows, use them, but never rely on it without checking.

## 2. Completeness and the "Others" / "Autres" row

Context: SKILL.md, "Completeness and the Others row".

A count or sum built from the page URLs report is only complete if no relevant "Others"
(localised "Autres") aggregation row sits between the level you start from and your target
rows. Matomo caps the number of rows stored per subtable at archiving time
(`datatable_archiving_maximum_rows_actions`, default 500) and collapses the remaining tail
of each directory into an "Others" row. Because URL query-parameter variants are distinct
pages (`/x/offer` and `/x/offer?utm=...` are two rows), a directory with many
parameterised variants (campaign params, ids, filters, selectors) can push some of them into
its "Others" row.

**The flat-report trap.** `flat=1` combined with `filter_pattern` SILENTLY DROPS the "Others"
row: its label is "Others"/"Autres", which does not match a path-based pattern, so your filter
removes it. A clean flat result with `has_more=false` therefore proves only that N rows matched
the pattern — NOT that the data is complete. Never conclude completeness from a filtered flat
report alone.

**How to verify — walk the hierarchy non-flat** (omit `flat`, pass `idSubtable` to drill down)
and look for an "Others" row at the two levels that actually matter:
1. **The true root** (the top-level directory list, e.g. `/www`, `/member-area`, `/404`).
   An "Others" here — especially when there are few directories — means aggregation is
   happening very high up, so the data is likely incomplete at every level below it. Treat as
   a stop-and-flag condition.
2. **The directory that *directly* contains your target page** (`/abc/` when you want
   `/abc/leaf`; e.g. `/*/checkout/{product}/` for an `offer` leaf). An "Others"
   at this level means parameterised variants of your leaf may be hidden inside it.

An "Others" row at an **intermediate** level you are not targeting (e.g. on `/www/` when the
target is `/www/checkout/x/leaf`) is **irrelevant**: it aggregates only the tail of
pages sitting *directly* under that level, not your deeper leaves. It matters only if your
target *is* a page directly under that level (e.g. `/www/leaf`).

When an "Others" does appear at a relevant level, the hidden variants usually surface among the
least-viewed rows of that same directory (often 1–2 hits each); inspect those. Variants that
stay hidden could only be recovered from the raw visit log, which this skill does not query
(SKILL.md, "Visitor log"): state the remaining uncertainty instead.
