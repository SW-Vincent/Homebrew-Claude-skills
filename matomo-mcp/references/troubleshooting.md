# Matomo MCP — Troubleshooting

Read this when a call fails, returns nothing, or returns a figure that looks implausible.
Before returning results as fact, evaluate the known limitations in §1; when a tool call
fails, go to §2; for the visitor log status, §3.

## 1. Data availability and common failure modes

Before returning results as fact, evaluate these known limitations:

| Situation | What to do |
|---|---|
| Report returns empty data | Check date range (is archiving done for that period?), check that the segment exists and is archived, check if the report module is enabled for this site |
| Metric value seems implausibly low/high | Note it to the user, suggest cross-checking with another period or metric |
| `period=range` with long date ranges | Matomo may time out or return partial data — prefer `period=month` + multiple calls if feasible |
| Today's data | Intraday data may be incomplete; flag this clearly |
| Ecommerce metrics (revenue, orders) | Only available if Ecommerce tracking is enabled on the site — check the site details (`matomo_site_get`) if they expose it, otherwise ask the user |
| Visitor Log data | Not queried by this skill — see "Visitor log" |

## 2. Error handling

When a tool call fails or returns unexpected output:

1. **Auth error (401/403)** — The token may lack permission for this site or the MCP is
   disabled. Tell the user clearly; do not retry blindly.
2. **Empty result set** — Do not interpret as "zero traffic". Enumerate possible causes
   (archiving not done, wrong idSite, segment issue, module disabled) and present them
   to the user.
3. **Unknown metric name in report_processed** — You likely guessed a field name. Go back
   to `matomo_report_metadata` and re-confirm the exact metric key.
4. **Timeout or slow response** — Suggest narrowing the date range or switching from
   `period=range` to `period=month`.
5. **Raw API tool not found or a method blocked** — Layer 2 is configuration-dependent.
   Only a **super admin** can enable raw API access, and the grant is granular (full or
   partial, and a partial grant can be scoped method by method). So a tool may be absent, or
   present but blocked for a specific method. Inform the user it must be enabled/scoped in
   the MCP settings rather than retrying.

## 3. Visitor log status (only when the user explicitly asks for visit-level data)

Context: SKILL.md, "Visitor log". The rule there stands: never read visits.

- `matomo_api_list` shows every read method the connector could route, **whatever Matomo's own
  privacy settings**. A `Live` method being listed does not mean it works. Observed on a live
  connector (November 2026): the `Live` methods were listed while the visitor profile was
  disabled.
- **The one safe status call is `Live.isVisitorProfileEnabled`** (returns true/false, no visit
  data). If it returns true, add to the alert that the visitor profile **is** enabled.
- There is **no equally safe probe for the visit log itself**. Do not call
  `Live.getLastVisitsDetails`, `Live.getVisitorProfile` or `Live.getMostRecentVisitorId` to
  find out. Do not treat `Live.getCounters` (aggregate real-time counts) as proof either way:
  it is not established that Matomo blocks it when the visit log is disabled.
- What settles it: the administrator checks the Matomo privacy setting that disables the visit
  log and visitor profile, and removes the `Live` methods from the connector's raw API scope
  (the second makes the first irrelevant for the connector).
