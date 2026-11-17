# Matomo MCP — Interpretation, biases and data limits

This file complements `prompt-patterns.md`. The patterns say HOW to fetch data; this file
says HOW to read it without going wrong. Consult it whenever an answer involves
interpretation (comparing periods, reading conversions, traffic sources, bounce rate,
unique visitors) and before presenting any figure as fact.

## Table of contents
1. Data availability and history
2. Segment semantics (segments are not filters)
3. Goals and conversions
4. Custom reports
5. Measurement architecture: one idSite is not one real site
6. Inspecting the Tag Manager
7. Reading reports: flat vs cascade, and the "Others" row
8. Unique visitors and recurrence
9. Traffic sources and attribution bias
10. Metric synonyms
11. Metric definitions to know
12. GDPR compliance
13. Versioning and changelog
14. Questioning data validity
15. What to say when uncertain

---

## 1. Data availability and history

- For Cloud accounts, segments and custom reports natively aggregate data over **13 months**
  (adjustable for on-premise accounts). Beyond that, data can be aggregated manually, or the
  support team can extend the period, provided the **raw data** is still available.
- Consequence: over a long period, data can be **incomplete**. To detect this, fetch the
  data on the first day of the target period before fetching the whole period; this reveals
  gaps.
- It is also useful to **check data day by day** over an extended period: gaps or spikes
  often point to singularities worth investigating (lost tagging, a deployment, a one-off
  campaign, a bot).

## 2. Segment semantics (segments are not filters)

A segment **is not a filter**. It selects whole **visits**; the report then aggregates
everything that happened in those visits, not only the rows that match the segment.

Concrete example: apply a page-URL segment (`pageUrl=@/example`) to the pages report. You do
not get only `/example`; you get every page seen during the visits that included `/example`.
Likewise, a segment on a specific event returns, in the events report, all the other events
fired in those same visits. To count one specific action or event, do not use a visit
segment: query the report **dimension** (e.g. the page or event-name report filtered on the
label).

**When this matters in practice.** The surprise is real mainly when an **action-scope**
segment (page URL, event) is applied to a report whose dimension is the **same** as the
segment's (page-URL segment on the pages report, event segment on the events report): the
overlap makes the result counterintuitive, so explain it. When the segment is on a
**visit-level** dimension (traffic source, device, country) and the report is a *different*
dimension (e.g. a source segment on the pages report), there is no overlap and no surprise —
mentioning the visit-level mechanics is then optional. When in doubt, a brief note never
hurts.

The operating rules (only saved, archived segments can be queried; what to do when a segment
is missing or looks under-aggregated; never create one or trigger archiving) are in
`SKILL.md`, "Segments": they are stated once, there.

## 3. Goals and conversions

- Goals are aggregated in **every report except custom reports**. This makes them flexible,
  but their reading depends on their configuration.
- A goal either allows **several conversions per visit** (hit-level counting) or **at most
  one per visit** (visit-level). This changes how many conversions are counted. Check the
  goal's "allow multiple conversions per visit" setting with `matomo_goal_get` before
  interpreting.
- **Default conversion attribution is to the last non-direct channel.** Matomo credits a
  conversion to the last referrer that was not a direct entry: a final direct visit does not
  take the conversion away from the campaign, search engine or site that brought the visitor
  earlier. Compared with ad platforms and their wider windows, this still favours
  bottom-of-funnel sources. The mode is configurable (first vs last referrer), and it relies
  on recognising the returning visitor (cookie): treat attribution as an interpretation
  caveat, not a tagging detail.
- When a question involves conversions, **do not query directly**: the term is too broad.
  Ask the user to describe the conversion **functionally** — what action does the user
  take, on which page or via which interaction — then map it to one of:
  - a **Matomo goal** (check `matomo_goal_list`, then `matomo_goal_get` for scope and
    trigger type),
  - a **tracked event** (query via `Events.getCategory/Action/Name`),
  - a **specific page** (query via `Actions.getPageUrls` with a filter).
  The same user behaviour (e.g. a form submission) can yield different figures depending
  on the path chosen: a goal allowing multiple conversions counts every matching hit, a
  once-per-visit goal counts one per visit, and a raw event count may differ from both if the
  tag fires multiple times per interaction.
- If `nb_conversions = 0` over a recent range, check the goal definition (trigger type,
  URL or event pattern, regex) before concluding there were no conversions. A goal is
  **not retroactive**: it only credits conversions after its creation/edit.

## 4. Custom reports

- Not every dimension + metric combination is **meaningful**. Check business coherence
  before presenting a cross-tab.
- Custom reports do not aggregate goals (see §3) and follow the 13-month limit (see §1).

## 5. Measurement architecture: one idSite is not one real site

- A Matomo "site" (idSite) can track **several real sites**: cross-domain tracking,
  consolidated tracking across subdomains, etc. Do not assume a 1:1 mapping between idSite
  and domain name.
- **Roll-Up Reporting** is the named Matomo mechanism for this: a special site that
  aggregates the data of several other sites into one consolidated view. Its presence
  explains figures that look too large for a single domain.
- **Pageviews can be tagged artificially**: fictitious URLs, or firing outside a real page
  load (single-page applications, virtual events). This distorts page reports if ignored.
- To clear up doubt, inspect the Tag Manager (§6).

**A single Matomo "site" (one idSite) does not necessarily map to a single real site.** One
idSite can aggregate several domains/subdomains/environments (e.g. a public site and a member
area tracked together, or staging hits mixed with production). The reverse also happens: one
real site split across several idSites. Crucially, neither the `name` nor the `main_url`
returned by `matomo_site_list` is reliable for telling which case you are in: `main_url` is
only the *primary declared* URL (a site may have several declared, only one shows), and the
name is free text that can understate or contradict the real perimeter (e.g. a site named
"Site & Member Area" whose `main_url` points to only one of the two). So picking an idSite
from the list does not, by itself, pin down what population the figures will cover.

**You do not hold the site's configuration in memory, and some of it materially changes how a
figure must be read.** In particular: whether tracking is gated behind consent (which can make
traffic and conversions undercounted relative to reality; see §12 and §14), the full set of declared/tracked
hostnames, ecommerce on/off, custom-dimension and goal setup. You can verify some of these on request
(`matomo_site_get` returns `ecommerce`; the perimeter is covered below), but you cannot assume
them. Before the user commits to a query, it is usually
worth making sure *they* have a clear enough picture of the relevant settings to choose
soundly, rather than silently querying an idSite whose perimeter or consent regime you have not
established. When confidence on perimeter or consent matters for the figure, say so explicitly.

**Checking the declared perimeter.** When the user wants more detail (or when name +
`main_url` look ambiguous or self-contradictory), the **recommended verification is `SitesManager.getSiteUrlsFromId`** (raw API, Layer 2) to list
every *declared* URL for an idSite, not just the primary one. State plainly that this requires
raw API access to be enabled; if it is not exposed, say so rather than guessing. Be clear about
its limit too: declared URLs describe configuration, not what is *actually* tracked. The page
URLs report does **not** resolve this either, because Matomo strips the hostname and keeps only
the path (unless a virtual-directory convention was baked in via `setCustomUrl`). The only
ground truth for actually-tracked hostnames is the raw visit log, which this skill does not
query (SKILL.md, "Visitor log"): say that the perimeter cannot be confirmed from here and that the
user or an administrator has to confirm it.

## 6. Inspecting the Tag Manager

Possible only if the MCP exposes the raw API. The actual execution goes through
`matomo_api_call_read` (the `matomo_api_get` method only returns a method's signature, it
does not execute it). See the dedicated pattern in `prompt-patterns.md`.

Unless the user explicitly asks for full detail, look first at:
- The **configuration variable** ("Matomo Configuration" template): it tells you about
  **multi-site tracking** (`domains`, `idSite`) and the **custom dimensions** injected.
- The **tags using the "Matomo > Pageview" template**: they tell you about **artificial
  pageviews** and **custom URLs** (triggers outside DOM-ready, forced titles or paths).

## 7. Reading reports: flat vs cascade, and the "Others" row

- Choose deliberately between a **flat** read (`flat=1`) and a **cascade** (tree) read,
  especially for page reports. The tree shows only the first level by default (folders like
  `/blog`); flattening gives the real list of URLs. A "top 5" read in cascade can therefore
  be misleading.
- **"Others" row**: beyond a certain number of rows at a given level, Matomo aggregates
  the least significant rows into an "Others" row. This row almost never appears in a
  Top N ranking — it is by construction a sum of the smallest values. When presenting a
  Top N, the "Others" row can be appended **outside the count** (e.g. "Top 5 pages +
  Others") to signal the share of undetailed traffic, especially when its volume is
  disproportionately large relative to total traffic.
- **"Others" as a GDPR signal**: a disproportionately large "Others" row in page or event
  reports is often a sign that URLs or event names contain identifiers, session tokens, or
  campaign parameters that fragment data into many unique values. Flag this to the user as
  a potential anonymisation issue and cross-reference with §12 (GDPR).
- On very large sites, a **global limit** can be hit even when the per-level limit is not.
- Indicative default limits (confirm per version):
  - Page reports: 500 rows for the first directory, then 100 per subtable, plus a high
    global limit rarely reached.
  - Event reports: 500 rows for the first dimension, then 500 per subtable.
  - Custom reports: 500 rows for the first dimension, then 100 per subtable.
- To retrieve all rows, page through them: through the MCP, `filter_limit` defaults to 50
  and is capped at 250 per call; use `filter_offset` and read `pagination.has_more` /
  `total_rows`. Keep the performance impact on large sites in mind.

## 8. Unique visitors and recurrence

- Which periods carry a unique-visitor figure **depends on the instance configuration**. By
  default on-premise, unique visitors are processed for day, week and month, not for year or
  custom ranges. On a Matomo Cloud account checked in November 2026, they were returned for
  **day and week only** (absent for month, year and range). Do not assume: check whether
  `nb_uniq_visitors` is in the returned **`columns` / `reportData`** for the period asked.
  Its presence in `metricTypes` proves nothing (it is listed there for every period). Say so
  when it is absent rather than leaving the figure out silently.
- Never sum daily (or weekly) uniques to get a figure for a longer period: the same visitor
  would be counted several times.
- The **cohorts** report informs recurrence, but recurrence is often **underestimated**
  because it relies on cookies whose lifetime is limited by browsers (ITP-style policies).
  A visitor returning after the cookie expires is counted as new.

## 9. Traffic sources and attribution bias

- Traffic sources can be **biased**, often by misused UTM / campaign parameters that pollute
  organic attribution (a mis-tagged internal link or email pushes visits into "campaign").
- Combined with last-visit attribution (§3), this can overstate some bottom-of-funnel
  sources. Cross-check with business sense before concluding.

## 10. Metric synonyms

Account for synonyms when understanding the request and phrasing the answer:
- visits = sessions
- pageviews = page views
- bounce rate = taux de rebond
- unique visitors = visiteurs uniques
- entrances = entries (entry pages = landing pages)
- exits = sorties

## 11. Metric definitions to know

Paraphrased from Matomo's "Key concepts in Analytics" guide
(https://matomo.org/subcategory/key-concepts-in-analytics/). Keep the link as the
authoritative source; the summaries below make the skill self-contained.

- **Visit (session)**: a sequence of actions by one visitor. By default a visit ends after
  **30 minutes of inactivity** (configurable). Activity after that timeout starts a new
  visit.
- **Unique visitor**: a distinct visitor over a period, de-duplicated with a
  config-dependent method (a visitor ID stored in a first-party cookie, or a
  privacy-preserving heuristic when cookies are off). Reliable by day and week; longer
  aggregation is config-dependent (see §8).
- **Hit**: a single tracking request received by Matomo (a pageview, an event, a download,
  an outlink, a content interaction, a ping, etc.). The most granular logged unit.
- **Action**: the subset of hits that count toward the "Actions" metric — pageviews,
  downloads, outlinks, site searches, and events. Some hits (heartbeat pings, ecommerce
  updates) are not actions.
- **Hit vs Action**: every action is a hit, but not every hit is an action. Useful when
  reconciling the "actions" total with raw request volume.
- **Entry page**: the first page viewed in a visit.
- **Exit page**: the last page viewed in a visit.
- **Movers & shakers** (increasers / decreasers): a report surfacing the rows with the
  biggest increases or decreases versus a previous period.
- **Funnel**: a defined sequence of steps toward a goal, used to measure drop-off at each
  step (premium/plugin feature).
- **Roll-Up Reporting**: a special site that aggregates several other sites into one
  consolidated view (see §5).
- **Bounce rate**: the share of visits with a single interaction. Critical point: in Matomo,
  **events count as interactions**. Tagging the mere visibility of an element (or any event
  fired on load) turns a would-be bounce into a non-bounce and can therefore **artificially
  lower the bounce rate**. It is also a signal of double tagging (see §14).

## 12. GDPR compliance

In some use cases you can check compliance signals:
- **personal data in URLs** (email, identifiers, tokens);
- personal data in **event names or values**;
- tracking firing **before consent** (not directly verifiable through the connector, see §14).

## 13. Versioning and changelog

- The Matomo changelog (https://matomo.org/changelog/) can explain certain changes. Example:
  in **5.5.0**, the "AI assistant" channel was added as a traffic source, which affects any
  comparison with earlier data.
- Caution: rollout of new versions to Cloud accounts can lag the changelog dates, and an
  on-premise account must have been updated for a change to apply.
- Only check the changelog **when you suspect a versioning issue** (a break in a series, a
  dimension appearing or disappearing, a definition change).

## 14. Questioning data validity

The connector cannot directly verify some factors that affect the data, notably:
- **consent gating** (a cookie banner may condition tagging);
- **double tagging** (two tags or two containers send the same hits).

Lacking a direct check, question the **coherence** of the data. Useful tell: with double
tagging, the **bounce rate should be abnormally low** (each page generates two hits, so
almost no visit looks single-interaction). A near-zero bounce rate is a red flag to raise
with the user.

**Consent gating also affects completeness, not just validity.** When tagging fires only
after consent, every visit that refuses or never answers the banner is not tracked at all, so
traffic and conversions can **systematically undercount** reality, by a margin that varies with
the banner and the audience. You cannot read the consent regime from the connector, and you do
not hold it in memory. Therefore, whenever a figure's usefulness depends on completeness (any
absolute count, including "leads"), do not present it as the real total: flag that it reflects
consented tracking only, and confirm the consent regime with the user. This is the same caveat
the site-selection gate raises (see `SKILL.md`, "Site-selection gate"); keep the two consistent.

## 15. What to say when uncertain

Use these when confidence is low:

- *(period possibly not fully aggregated)* "These figures come from pre-aggregated data. The
  numbers look low for the period — to check whether archiving has fully run, I can re-query
  just the first day of the period; if it comes back empty where we'd expect traffic, it's
  likely an aggregation gap and worth raising with an administrator. Want me to run that
  check?"
- "I retrieved this figure using the `[report name]` report. If this seems off, it's
  worth cross-checking directly in the Matomo UI."
- *(segment not defined)* "This segment doesn't exist as a saved segment in this account, so
  I can't query it. You'd need to create it (Administration → Segments) or ask an
  administrator to — it's not something I can set up myself, partly because segments can be
  capped by the plan."
- "A near-zero bounce rate here may indicate double tagging rather than genuine engagement;
  worth verifying the tracking setup."
