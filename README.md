# Homebrew Claude skills

Homebrew Claude skills, mostly for Web Analytics purposes.

## gtm-tag-audit

Audits tag management containers (**Google Tag Manager**, **Matomo Tag Manager**, **Tag Commander**) and produces an Excel workbook: for each tag, where the data goes, which data exactly, under which conditions, and what the consent mechanism is.

Two modes:

- **Pre-audit**: from the client-side code of a site (`gtm.js`, `container_<ID>.js`, `tc_*.js`), with no access to the container.
- **Full audit**: from a container export (tag, trigger and variable names available).

Several tag managers can be audited side by side in one workbook, with duplicates and inconsistencies flagged.

### Usage

Attach the container **as a file** (pasted text or a URL is not enough: the content may be truncated), then ask, for example:

> Here are the gtm.js and the Matomo container code of this site, do a pre-audit.

To find the file: open the browser DevTools Network tab, reload the page and filter on `gtm.js`, `container_` or `tc_`.

### Output

A three-sheet workbook (**Summary**, **Tags**, **Consent & Findings**) and a short summary in the chat. Both follow the language of your conversation.

⚠️ This is a static reading: confirm findings in each tool's Preview/Debug mode on the live site. Consent is often handled by the cookie banner rather than the tag manager, hence the asterisks in the workbook.

### Checks made for you

- A tag gated on consent but only evaluated at page load (page view, DOM ready...) is flagged: on the page where the visitor first accepts, it does not fire, so the first page view and the origin of the visit are lost.
- A blocker that contradicts its own trigger, duplicates across tools, leftovers.
- Server-side tagging: are hits sent to a server endpoint, and which events and parameters (extra **Server-side** sheet). What the server then relays is not visible from the web container.
- User-provided data: enhanced conversions, advanced matching, with the fields sent and where they are read.
- Vendor consent modes besides Google's: Microsoft UET, Meta, Piano Analytics (hybrid measurement), TikTok, Pinterest.

### Tests

```
python -m unittest discover tests
```

The tests run both scripts on the anonymised example containers (`gtm-tag-audit/references/examples/`). Run them after any change to a script.

## matomo-mcp

Guides Claude when it queries Matomo through the official [MCP Server plugin](https://plugins.matomo.org/McpServer) (matomo-org/plugin-McpServer). **Read-only**: it never creates or changes anything in Matomo, even when write tools are exposed.

What it enforces:

- **Account and site first.** With several Matomo connectors, Claude asks which account to use; within an account, it never guesses the site (one account holds several sites, one site can cover several domains).
- **No silent guesses.** "Leads" or "conversions" are mapped to a goal only after you confirm it; an "X by Y" request is answered with a real cross, or Claude stops and says what is missing (saved segment, custom report).
- **Saved segments only**, passed exactly as stored; Claude never creates segments nor triggers archiving.
- **Reading the figures right**: segments select visits (not rows), goal counting per hit or per visit, last non-direct attribution, unique visitors only for some periods, the "Others" row and incomplete page reports, consent gating and double tagging.
- **Visitor log**: never queried. If you ask for visit-level data, Claude checks without reading any visit whether the connector exposes it, and tells you what to report to the administrator.

### Usage

Install the skill, connect a Matomo instance through the MCP Server plugin, then ask in plain language, for example:

> How many quote requests on the member site last month, by device?

Expect a few questions before the first figure (account, site, which goal): they are grouped in one message.

### Tested against

A Matomo Cloud instance with MCP Server 5.1.2 (November 2026), read-only raw API access.
