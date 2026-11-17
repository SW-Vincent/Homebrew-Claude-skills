# Matomo MCP — Reference prompt patterns

This file contains typical call sequences for common use cases. Read it when the user asks
an analytics question matching one of the scenarios below.

Every pattern starts **after** the account gate and the site-selection gate of `SKILL.md`:
`idSite=X` always stands for a site the user named or picked. All calls are read-only.

---

## 1. Traffic summary (visits, pageviews, bounce rate)

**Typical question**: "How many visits on site X last week?"

```
1. matomo_site_list          → confirm idSite
2. matomo_report_metadata    → module=VisitsSummary, action=get
                               → available metrics: nb_visits, nb_pageviews,
                                 bounce_rate, avg_time_on_site, nb_uniq_visitors
                                 (nb_uniq_visitors only for some periods:
                                 interpretation-and-limits.md §8)
3. matomo_report_processed   → idSite=X, period=week, date=previous1,
                               apiModule=VisitsSummary, apiAction=get
```

**Common date parameters**:

`lastX` includes today; `previousX` excludes the current period (i.e. the X periods *before* today).

| Intent | `date` | `period` |
|---|---|---|
| Last 7 days including today, day by day | `last7` | `day` |
| Last 7 complete days (excluding today) | `previous7` | `day` |
| Current calendar week (Mon–today) | `last1` | `week` |
| Previous complete calendar week | `previous1` or `lastWeek` | `week` |
| Current month (1st–today) | `last1` | `month` |
| Previous complete month | `previous1` or `lastMonth` | `month` |
| Last 4 complete weeks (before this week) | `previous4` | `week` |
| Last 12 complete months (before this month) | `previous12` | `month` |
| Arbitrary range, aggregated as one block | `2025-01-01,2025-03-31` | `range` |
| Arbitrary range, month by month | `2025-01-01,2025-03-31` | `month` |
| A calendar quarter (e.g. Q1 2025) | `2025-01-01,2025-03-31` | `range` (one block) or `month` (three rows) |

There is no quarter keyword. "This quarter" / "last quarter" must be turned into explicit
dates as above. `last3` with `period=month` is something else: the current month and the two
before it (three rolling months, the current one incomplete). If the user says "quarter"
without saying calendar or rolling, ask.

⚠️ `last1` means the **current** period (e.g. current week Mon–today), not the previous one.
Use `previous1` (or magic keyword `lastWeek`/`lastMonth`/`lastYear`) to get the last *completed* period.
Magic keywords (`today`, `yesterday`, `lastWeek`, `lastMonth`, `lastYear`) are relative to the site's timezone.

---

## 2. Top pages

**Typical question**: "Which pages are most visited this month?"

```
1. matomo_report_metadata    → module=Actions, action=getPageUrls
                               → metrics: nb_visits, nb_pageviews, bounce_rate,
                                 avg_time_on_page, exit_rate
2. matomo_report_processed   → idSite=X, period=month, date=last1,
                               apiModule=Actions, apiAction=getPageUrls,
                               filter_limit=20
```

Variants:
- Page titles: `apiAction=getPageTitles`
- Entry pages: `apiAction=getEntryPageUrls`
- Exit pages: `apiAction=getExitPageUrls`

The page report is hierarchical by default. Use `flat=1` to get the real list of URLs
rather than first-level folders. See `interpretation-and-limits.md` §7.

---

## 3. Traffic sources / channels

**Typical question**: "Where did traffic come from over the last three months?"

**Default meaning of "traffic source" = the channel TYPE**, not the individual referrer.
Lead with `Referrers.getReferrerType`, which returns the channels: Direct, Search engines,
Websites, Social networks, AI assistants, Campaigns.

```
1. matomo_report_metadata    → module=Referrers, action=getReferrerType
2. matomo_report_processed   → idSite=X, period=month, date=last3,
                               apiModule=Referrers, apiAction=getReferrerType
```

Only drill into the **detail** of referrers when the user explicitly asks (e.g. "which
sites", "which search keywords", "which social networks"):
- `apiAction=getAll` → combined tree of referrers (type + detail underneath)
- `apiAction=getWebsites` → referring websites
- `apiAction=getSearchEngines` → search engines
- `apiAction=getSocials` → social networks
- `apiAction=getCampaigns` → UTM campaigns (requires the MarketingCampaignsReporting
  plugin for pk_* / mtm_*)

To split any report **by traffic source** (an "X by Y" cross), use the channel TYPE as Y:
`getReferrerType` gives the values, then segment the X report with
`referrerType==search|direct|website|social|ai|campaign` (saved segments). See the
cross-dimension gate in SKILL.md, and `interpretation-and-limits.md` §2 (segment semantics)
and §9 (attribution biases).

---

## 4. Campaign performance with conversion rate

**Question**: "Which campaigns drove the most conversions in March?"

```
1. matomo_goal_list          → idSite=X → list goals, note idGoal
2. matomo_report_metadata    → module=Goals, action=getConversionsOverview
                               OR module=Referrers, action=getCampaigns
                               → confirm goal metrics are present
3. matomo_report_processed   → idSite=X, period=month, date=2025-03-01,
                               apiModule=Referrers, apiAction=getCampaigns,
                               idGoal=Y
```

⚠️ If `nb_conversions = 0` for a recent range: first confirm the goal is active, that its
URL/event pattern actually matches tracked pages, and that the goal is not newer than the
data (goals are not retroactive). See `interpretation-and-limits.md` §3.

---

## 5. Segment comparison

**Question**: "Compare mobile vs desktop visits this month."

```
1. matomo_segment_list       → idSite=X → list the saved segments and confirm the exact
                               definitions exist (only archived segments are queryable)
2. matomo_report_processed   × 2 calls:
   - segment=<saved Mobile segment definition>
     idSite=X, period=month, date=last1, apiModule=VisitsSummary, apiAction=get
   - segment=<saved Desktop segment definition>
     same parameters
```

Pass the exact stored definition returned by `matomo_segment_get`; never an expression you
write yourself. Missing or under-aggregated segment: see SKILL.md → Segments.

Operators, to **read** a saved definition (not to build one):
- `==` equals, `!=` not equals, `>` `<` `>=` `<=` for numeric
- `=@` contains, `!@` does not contain
- `;` AND, `,` OR

---

## 6. Custom dimension breakdown

**Question**: "What is the visit breakdown by user type (custom dimension)?"

```
1. matomo_dimension_list     → idSite=X → find the dimension: idDimension, scope
                               (visit/action), active
2. matomo_dimension_get      → idSite=X, idDimension=Y → confirm name and slot
3. matomo_report_metadata    → module=CustomDimensions, action=getCustomDimension
4. matomo_report_processed   → idSite=X, period=month, date=last1,
                               apiModule=CustomDimensions, apiAction=getCustomDimension,
                               idDimension=Y
```

⚠️ An inactive dimension (`active=0`) returns empty data or an error — always check the
`active` flag before querying.

---

## 7. Page technical performance (load time)

**Question**: "Which pages have the longest load time?"

```
1. matomo_report_metadata    → module=PagePerformance, action=get
                               → metrics: avg_time_dom_processing, avg_time_on_load,
                                 avg_time_network, avg_time_server, avg_time_transfer
   OR module=Actions, action=getPageUrls with avg_page_load_time
2. matomo_report_processed   → idSite=X, period=week, date=last1,
                               filter_sort_column=avg_time_on_load,
                               filter_sort_order=desc, filter_limit=20
```

⚠️ The PagePerformance plugin must be installed and active. If the module is absent from
`matomo_report_list`, tell the user.

---

## 8. Tracking verification (missing data)

**Question**: "Are pages X and Y still sending data?"

```
1. matomo_report_processed   → apiModule=Actions, apiAction=getPageUrls,
                               period=day, date=today, filter_pattern=<URL fragment>
```

If the result is empty:
- Check that `date=today` is not just incomplete intraday data (try `date=yesterday`)
- Suggest checking the tracking tag in the Tag Manager (see pattern 9)
- Consider checking data day by day over a longer period to spot gaps or spikes

---

## 9. Tag Manager inspection (what is actually tagged)

**Question**: "What is tracked / tagged on the site?" or a tagging audit.

Requires raw API access (Layer 2). Execution goes through `matomo_api_call_read`;
`matomo_api_get` only returns a method's signature.

```
1. matomo_api_call_read → method=TagManager.getContainers, parameters={idSite: X}
                          → note idContainer and the active version
                            (releases → idcontainerversion)
2. matomo_api_call_read → method=TagManager.getContainerTags
                          parameters={idSite: X, idContainer: "...", idContainerVersion: N}
3. matomo_api_call_read → method=TagManager.getContainerTriggers (same parameters)
4. matomo_api_call_read → method=TagManager.getContainerVariables (same parameters)
```

Cross-reference each tag's `fire_trigger_ids` / `block_trigger_ids` with the triggers to
reconstruct the firing logic. Unless the user asks for everything, look first at (see
`interpretation-and-limits.md` §6):
- the configuration variable ("Matomo Configuration" template): multi-site tracking
  (`domains`, `idSite`) and injected custom dimensions;
- the tags using the "Matomo > Pageview" template: artificial pageviews and custom URLs.

⚠️ `getContainerTags/Variables` responses can be large: extract the useful fields (name,
type, conditions) rather than loading everything.

---

## Cross-cutting notes

**Selecting the report**: `matomo_report_processed` accepts `reportUniqueId` in the
underscore form returned by `matomo_report_list` (e.g. `VisitsSummary_get`), or
`apiModule` + `apiAction` as in the patterns above. Prefer `reportUniqueId` when you have it.

**Pagination**: through the MCP, `filter_limit` defaults to **50** rows and is capped at
**250** per call; `-1` is not accepted. To fetch everything, page with `filter_offset` until
`pagination.has_more` is false; `pagination.total_rows` gives the total up front.

**flat=1**: flattens the URL/page hierarchy to get every row without the folder tree. Pass it
inside `apiParameters` (`{"flat": 1}`), like other report-specific parameters (`idSubtable`,
`idGoal` and `idDimension` have their own fields). Useful for exports and for reading the true
top-N. See `interpretation-and-limits.md` §7.

**Dates through the MCP**: with `period=range`, `lastN` / `previousN` count **days** and give
one aggregate (`range` + `last7` = one total over 7 days). With `period=day/week/month/year`,
`lastN` counts **periods** and returns one entry per period. For a single block, prefer one
date or keyword (`lastMonth`, `2026-10-01`) with the matching period.

**format**: the MCP usually returns JSON. Do not set `format` in MCP calls — the plugin
handles it.

**Enumerating a dimension's value set**: see `crosses-and-completeness.md` §1. Open
dimensions (page URL, country, keyword) are data-driven and capped: they cannot be enumerated
in full.

**Supported periods**: `day`, `week`, `month`, `year`, `range` (range = a span with two
dates separated by a comma).
