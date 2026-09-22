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
