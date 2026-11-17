# Matomo MCP — Tool surface

What each tool returns, as seen in a live exploration of the plugin (version 5.1.2, November
2026; the plugin has separate releases for Matomo 5 and Matomo 6). The exact set **depends on
how the MCP is configured**, in particular whether raw API access is enabled and how it is
scoped. If the tools you see differ from this list, trust them and their descriptions.

## Layer 1 — High-level analytics tools (always enabled when MCP is on)

| Tool | What it returns |
|---|---|
| `matomo_site_list` | All sites the authenticated user can access (idSite, name, url) |
| `matomo_site_get` | Details for a specific site |
| `matomo_site_search` | Find a site by name or URL fragment |
| `matomo_report_list` | Catalogue of available reports for a site (uniqueId, module, action, name, category, subtable flags). Includes custom reports and subtable reports; does NOT include the dimension itself |
| `matomo_report_metadata` | Full metadata for one report: primary `dimension`, `metrics`, `metricsGoal` (whether goal metrics can be attached), `relatedReports`, subtable info |
| `matomo_report_processed` | Execute a report and return data (requires idSite, period, date, report ID) |
| `matomo_goal_list` | Goals defined for a site |
| `matomo_goal_get` | Details for a specific goal |
| `matomo_segment_list` | Saved segments for a site |
| `matomo_segment_get` | Details for a specific segment |
| `matomo_dimension_list` | Custom dimensions defined for a site |
| `matomo_dimension_get` | Details for a specific custom dimension |

## Layer 2 — Raw API tools (only present if enabled)

`matomo_api_list`, `matomo_api_get`, `matomo_api_call_read`, `matomo_api_call_create`,
`matomo_api_call_update`, `matomo_api_call_delete`, `matomo_api_call_full`

These expose the full Matomo Reporting API surface. **Only a super admin can enable and
configure them**, and the configuration is granular: access can be full or partial, and a
partial grant can itself be scoped method by method. So some raw tools may be present while
others (or specific methods) are blocked. Only use them if they are actually exposed.
**Of this layer, use only `matomo_api_list`, `matomo_api_get` and `matomo_api_call_read`.**
The create, update, delete and full tools can write data: never call them (SKILL.md, "Scope:
read-only"). The plugin can also expose tools that create or edit segments: same rule. A quick
way to see the grant: `matomo_api_list` with `category: create` returns nothing on a read-only
connector.

Use `matomo_api_call_read` to **inspect the Tag Manager** (containers, tags, triggers,
variables) — this is the only way to see what is actually tagged and to detect artificial
pageviews or multi-site tracking. Note `matomo_api_get` only returns a method's signature;
the execution is `matomo_api_call_read`. See the Tag Manager pattern in
`prompt-patterns.md` §9 and the inspection checklist in
`interpretation-and-limits.md` §6.
