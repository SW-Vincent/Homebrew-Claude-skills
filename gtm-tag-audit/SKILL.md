---
name: gtm-tag-audit
description: Audits tag management containers (Google Tag Manager, Matomo Tag Manager, Tag Commander/Commanders Act) into a structured Excel workbook, from client-side code found on a site (gtm.js, container_XXX.js, tc_*.js, i.e. pre-audit without container access) or from an interface/API export (full audit). Lists each tag with vendor, exact event and data sent, trigger, blocker, Tag Commander scope (périmètre), status and consent mechanism; several tools on one site go in one workbook. Use whenever the user shares or mentions a tag manager container, export or container code (`var data = {"resource"`, `MatomoTagManager.addContainer`, `tagContainer Generator`, `tC.launchTag`, a GTM-XXXXXXX ID), or asks for a tracking audit, pre-audit, full audit, "what does this site send to Meta/GA", "list the tags with their triggers", or in French "audit de tracking", "pré-audit", "audit complet", "liste-moi les tags avec leurs déclencheurs", even without naming the tool.
---

# Tag management container audit (GTM, Matomo Tag Manager, Tag Commander)

## What this skill does

A tag container is unreadable as is: numeric indexes, trigger logic scattered across structures,
third-party templates whose name says nothing about the vendor. This skill turns it into a usable
audit: an Excel workbook that says, for each tag, **where the data goes, which data exactly, under
which conditions (trigger, blocker, scope) and under which consent**, plus a reading of the
sensitive points that an account manager or a DPO can read without opening the tool.

It is a static reading: conclusions are ideally checked in the Preview/Debug mode of each tool on
the live site. Say so in the answer.

Write the workbook and the chat answer **in the user's language** (`lang` in the spec, `en` or
`fr`). This skill is written in English, the deliverable is not.

## Step 0. Frame the audit: mode and platforms

Two modes, which can coexist from one platform to another on the same site:

| Mode | Situation | Source | What the source does not show |
|---|---|---|---|
| **Pre-audit** | no access to the client's or prospect's container | client code: the file loaded by the page | tag names (GTM, MTM), trigger names (GTM, MTM), infrastructure tags, drafts, Tag Commander consent |
| **Full audit** | access to the container | interface or API export | nothing major (except Tag Commander: export format not documented) |

Recognise the platform and the kind of source from these signatures:

| Signature | Platform | Source | Reference |
|---|---|---|---|
| `var data = {"resource": {"macros"...` | GTM | client code | `references/gtm.md` |
| `exportFormatVersion` + `containerVersion` | GTM | export | `references/gtm.md` |
| `window.MatomoTagManager.addContainer(` | MTM | client code | `references/matomo_tag_manager.md` |
| JSON with `idcontainer` + `tags[].fire_trigger_ids` | MTM | export | `references/matomo_tag_manager.md` |
| header `tagContainer Generator`, `tC.launchTag(` | Tag Commander | client code | `references/tag_commander.md` |
| Tag Commander interface export | Tag Commander | export | format not documented, see the reference |

If the user does not state the mode, infer it from the files provided. Ask only if a single file
does not tell you whether a pre-audit or a full audit is expected. Several tools on one site go in
**one workbook**, with the `Platform` column.

## Step 1. Get the sources

**Always get the container as an attached file.** Why: these files weigh 250 to 500 KB, which is
hundreds of thousands of tokens of minified code. Anything that enters the conversation as text
(pasted in chat, or read from a URL by a web reading tool) goes through the context window: it can
be truncated without warning, it uses up most of the window, and the script cannot process it. An
attached file is stored on disk: `extract_container.py` reads it in full from there and only its
short summary reaches the context. Work from the file on disk (`/mnt/user-data/uploads/`), even
if the platform also displays part of its text inline, and never rely on that inline text.

Where to find the files:

| | Pre-audit (client code) | Full audit (export) |
|---|---|---|
| **GTM** | file `gtm.js?id=GTM-XXXXXXX` (Network tab) | JSON export from the GTM admin, or version export through the GTM API |
| **MTM** | file `container_<ID>.js` loaded by the page | JSON export of the version from the Matomo interface (or the API, untested) |
| **Tag Commander** | file `tc_*.js` from the Commanders Act CDN (Network tab) | ask the user: format not documented |

**If the user only gives a site URL or a container ID**, do not try to read the container through a
URL yourself: your job is to get the user to attach the file. IDs and URLs are of no use to you on
their own (you cannot fetch the container reliably, see above). Their only purpose is to let the
**user** open the file in their browser, save it (`.js` or `.txt`) and attach it. Do this:
1. If you have a page URL, open the page and list the containers it loads: GTM IDs
   (`GTM-XXXXXXX`), `gtm.js` URLs, `container_<ID>.js` (Matomo), `tc_*.js` (Tag Commander), with the
   exact URL of each file. This tells you which files to ask for. A page reader may return only
   the visible text without the script tags (not verified).
2. Tell the user which files to attach, with the link to open. For GTM an ID is enough: the file is
   at `https://www.googletagmanager.com/gtm.js?id=GTM-XXXXXXX` (give them the link with their ID).
   For MTM and Tag Commander the file URL cannot be derived from an ID.
3. If you cannot see the URLs (no script tags in what you read, or an ID only for MTM or Tag
   Commander), **help the user find them themselves**: in the page source (view-source), search
   for `googletagmanager.com/gtm.js`, `container_` or `tc_`; or in the browser DevTools Network
   tab, reload the page and filter on `gtm.js`, `container_` or `tc_`. If a container does not
   appear, it may only load after the cookie choice: accept the banner and reload. Then they open
   the URL, save the file and attach it.
4. Only if that is impossible, and as a last resort, work from text read through a URL the user
   gave: check that it is complete (balanced braces, proper end of file) and state in the source
   limits that it was read that way and may be partial.

When several sources describe the same container (client code + export), first check that the
version is identical (`resource.version` / `containerVersionId` for GTM, `revision` for MTM).

## Step 2. Extract with the script, then read the platform reference

```
python scripts/extract_container.py <file> --table              # one line per tag
python scripts/extract_container.py <file> --out /tmp/view.json # full view
python scripts/extract_container.py <file> --all                # includes GTM infrastructure tags
```

The script recognises the format, mechanically resolves what causes errors (GTM macro and rule
indexes, trigger references, Tag Commander scopes and polarities, wrongly encoded names) and prints
the **source limits** (`Note`): carry them over into the workbook. It does not judge: vendor,
category, data sent and anomalies remain your job.

Then read the platform reference (`references/`). If the script does not recognise the format,
say so and ask for the right file instead of guessing.

**Join key**: `Platform` + `Tag ID`. IDs are identical between client code and export (GTM `tag_id`
= `tagId`, MTM `id` = `idtag`, Tag Commander ID of the `executeTag`). A full audit that follows a
pre-audit reuses the same rows: replace the "(unnamed)" names with the real ones and add what the
client code did not show (paused tags, native consent).

## Step 3. Decode each tag

- **Inventory**: exclude GTM infrastructure tags (`__tg`, `__hl`, `__lcl`, `__cl`...), they do not
  exist in the export and would skew the total. Mention their number in the limits.
- **Name**: the tool's own name when available. Otherwise (GTM and MTM client code) write
  `(unnamed) ` followed by a functional description deduced from what the tag does ("Matomo,
  purchase event"; in a French workbook `(sans nom) `). Never an invented name that looks real.
- **Vendor and category**: from the tag type, then the identifier (prefix `G-`, `AW-`), the domains
  called, the parameters (`pixelId`, `partnerId`). For a GTM custom template, follow the method in
  `references/gtm.md` section 6. If the vendor stays uncertain, write "vendor to confirm, domain
  X": a wrong attribution is worse than a "to check" cell.
- **Data sent**: resolve each reference to what it really reads (dataLayer variable, cookie, URL),
  not "macro 24". Note the event (standard or custom) and the key variables passed. Flag email or
  phone sent in clear to an advertising vendor.
- **Technical type**: GTM the function (`awct`, `cvt_...`), MTM the type (`Matomo (event)`,
  `CustomHtml`), Tag Commander the template (`Template 2652`) with its nature if you know it.

## Step 4. Trigger, blocker, scope, status

The workbook separates four notions. Render them in plain language, one sentence per notion.

| Notion | GTM | MTM | Tag Commander |
|---|---|---|---|
| **Trigger** (when) | `firingTriggerId` / `add` rules | `fire_trigger_ids` | listener or custom event (`launchTag`) |
| **Blocker** (unless) | `blockingTriggerId` / `block` rules | `block_trigger_ids` | no separate structure seen in the client code: exclusions appear in the scope |
| **Scope** (where / for which values) | not applicable | not applicable | conditions compiled in front of the tag: URL, path, variable, consent levels (see `references/tag_commander.md`) |
| **Status** | `paused` / `__paused` | `status`, `start_date`, `end_date` | tag defined but never launched |

The **scope is specific to Tag Commander**: do not merge it into "Trigger". For the other
platforms the column stays empty.

Fixed vocabulary of the `Status` column: `Active`, `Active (scheduled)`, `Inactive (paused)`,
`Inactive (expired)`, `Inactive (never launched)` (French workbook: `Actif`, `Actif (planifié)`,
`Inactif (pausé)`, `Inactif (expiré)`, `Inactif (jamais lancé)`). Compare MTM dates with the audit date.

**Systematic check**: a tag can be added by one trigger and blocked by another, and **blocking
always wins**. Spot tags whose blocker overlaps their own trigger: in practice they never fire.
Also spot tags that fire specifically in the absence of consent.

## Step 5. Consent, platform by platform

The mechanism differs from one tool to another: describe it **per platform**, do not merge.

**Rule of caution.** Consent (and Google Consent Mode) is very often handled by the cookie banner
(CMP), upstream of or next to the tag manager. What the container does not show therefore does not
prove that it does not exist. Any verdict that rests on the absence of a mechanism in the container
carries an **asterisk (`*`)** and the alert "to confirm with a real test": without a test (network
requests before and after the choice in the banner), the possible scenarios cannot be told apart.
Never write "not implemented" on that basis alone.

- **GTM**: two cases, detailed in `references/gtm.md` section 7.
  - Consent Mode signals present in the container: verdict Basic, Advanced or Mixed, with proof.
  - No signal (Consent Mode probably handled by the CMP): two scenarios to state, with asterisk.
    Google tags not subject to consent: consent management defect OR Consent Mode Basic. Google
    tags subject to consent: consent handled the old way OR Consent Mode Advanced.
  - Server-side detected: not determinable from the client container*.
- **MTM**: read the `MatomoConfiguration` variable (`requireConsent`, `requireCookieConsent`,
  `setConsentGiven`, `rememberConsentGiven`) and the tags that drive it. A configuration without a
  consent requirement does not prove there is no management: the CMP may block the container from
  loading (asterisk). See `references/matomo_tag_manager.md` section 6.
- **Tag Commander**: per-tag consent is not in the client code. Write "not determinable from the
  client code*" and say how to settle it. See `references/tag_commander.md` section 6.

State for each platform whether blocking goes through a native setting of the tool or through home-made
logic re-reading the CMP cookie (more fragile, to flag).

## Step 6. Cross-cutting points of attention

- **Real GA4 or imitated payload.** A real GA4 is a Google tag whose measurement ID starts with
  `G-`. A payload "in GA4 format" sent by an HTML tag or a server to a domain that is neither
  `google-analytics.com`, nor `analytics.google.com`, nor a server container of the client, is not
  GA4. Always settle it, even to conclude "no GA4 in this container".
- **Server.** Distinguish a GTM server container (first-party collection domain) from a
  self-hosted analytics server (Matomo, Piwik PRO...): two different things.
- **Leftovers**: `__gas` variable without `__ua` tag, paused tags whose trigger still exists, expired
  MTM tags, never-launched Tag Commander tags.
- **Anomalies to hunt actively**: blocker that contradicts the trigger, identical tags fired by the
  same trigger, several pixel IDs of the same vendor, preproduction URLs in a production scope.
- **Across platforms** (the value of a multi-tool audit): the same pixel or the same `matomoUrl` +
  `idSite` loaded by two tools (double counting), consent honoured in one tool and not in the other
  for the same vendor, several tools sending the same event.

## Step 7. Excel deliverable

Excel by default (tabular inventory), unless asked otherwise. Before writing code, read
`/mnt/skills/public/xlsx/SKILL.md` (mandatory recalculation as soon as there are formulas).

Use `scripts/build_audit_xlsx.py` (spec schema at the top of the script, full example in
`references/example_spec.json`). Three sheets:

1. **Summary**: "Scope of the analysis and source limits" table (one row per container: platform,
   identifier, version, source, date, limits), key figures (four automatic ones, then yours),
   breakdown by platform and by category, all by formula.
2. **Tags**: fixed columns, in this order (French workbook: same order, French headers, see the
   script):
   `Platform | Tag ID | Tag name / Destination | Category | Technical type | Event / Data sent | Trigger | Blocker(s) / Exceptions | Scope (Tag Commander) | Status | Notes`
3. **Consent & Findings**: one row per consent mechanism and per platform, then one finding per
   block (bold title, one or two sentences).

Consent values ending with `*` (Consent sheet columns, key figures) automatically display the
asterisk legend in the workbook (Summary and Consent sheet). A custom text is possible with the
`consent_asterisk_note` key of the spec.

If several containers of the same platform are audited, suffix the `Platform` value (`GTM #2`) and
add one source row per container.

After generation: `python /mnt/skills/public/xlsx/scripts/recalc.py <file.xlsx>`, with
`status: success` and `total_errors: 0` before delivering.

## Step 8. Answer in the chat

Never drop the file alone. Open with the 2 to 4 most important findings in prose (real presence of
GA4, where the data goes, consent state per tool, anomalies, duplicates across tools). Add one or
two sentences on **the mode and the source limits** (for example "pre-audit on client code: tag
names not available, Tag Commander consent not determinable"). Carry the consent asterisk into the
answer: say that the verdict needs a real test and which one (network requests before and after the
choice in the banner). It is what a client reads before opening the file.

## Skill files

- `references/gtm.md`: GTM, client code and export, correspondence, functions, vendor, Consent Mode.
- `references/matomo_tag_manager.md`: MTM, client code and export, correspondence, consent.
- `references/tag_commander.md`: Tag Commander, client code, scope and polarities, limits.
- `references/example_spec.json`: example spec (3 platforms, sources of different kinds).
- `references/examples/`: anonymised example containers, one file per format.
- `scripts/extract_container.py`: format detection and resolved extraction.
- `scripts/build_audit_xlsx.py`: Excel generator (3 sheets, formulas, formatting, `en`/`fr`).
