# Matomo Tag Manager (MTM): client code and version export

Contents: 1. Recognise the source, 2. Client code, 3. Version export, 4. Correspondence between the
two, 5. Types met, 6. Consent, 7. Server, 8. MTM-specific points of attention.

Anonymised examples (same container, two forms): `examples/mtm_client_code_example.js` and
`examples/mtm_interface_export_example.json`.

## 1. Recognise the source

| What you are looking at | Source |
|---|---|
| JS with the `Matomo Tag Manager` header and the call `window.MatomoTagManager.addContainer({...}, Templates)` | client code (file `container_<ID>.js`) |
| JSON with `idcontainer`, `idsite`, `revision`, and `tags` carrying `fire_trigger_ids` | version export (interface or API) |

The container identifier (8 characters) is `id` in the client code and `idcontainer` in the
export. The revision number is `revision` in both: check that it is identical before comparing the
two sources.

Where to find the client code: file `container_<ID>.js` loaded by the site's pages (browser
Network tab, or in the page source to find its URL). Where to find the export: Matomo interface,
Tag Manager section, container version, export action. An export method also exists in the Matomo
API (Tag Manager module): it was not tested for this skill, to confirm on the instance before
relying on it.

## 2. Client code

The file first contains the Matomo Tag Manager runtime library (over 200 KB, of no interest for
the audit), then definitions `Templates['CustomJsFunctionVariable<hash>'] = ...` (the JS code of
"Custom JavaScript" variables), then:

```js
window.MatomoTagManager.addContainer({
  "id": "AbCdEfGh", "idsite": 1, "versionName": "...", "revision": 7, "environment": "live",
  "tags": [...], "triggers": [...], "variables": [...]
}, Templates);
```

The line just before the call gives `ignoreGtmDataLayer` and `activelySyncGtmDataLayer`: if the site
also hosts GTM, these settings say whether MTM reads GTM's dataLayer.

**What is lost compared to the interface**:
- **The tag name is replaced by its MD5 hash**: `name = md5(name typed in the interface)`.
  Verified byte for byte on a real container (22 tags out of 22). It is impossible to recover a
  name from the hash, but possible to **validate a candidate name**: `md5(candidate_name)` must
  give the value in the file.
- Triggers and variables carry the name of their **type** (for example a trigger named `DomReady`
  whatever its real name).
- Variable references `{{Name}}` are replaced by the inlined variable object: a composed text
  becomes `{"joinedVariable": ["text ", {variable}, " rest"]}`.
- A single environment is visible (`environment`, usually `live`): no draft, no other version.

**What is kept**: the IDs of tags, triggers and variables (identical to the interface), the full
tag parameters, the trigger conditions, the Matomo configuration (`MatomoConfiguration`, with the
server URL), the schedule dates (`startDate`, `endDate`), `fireLimit`, `fireDelay`,
`blockTriggerIds`, `fireTriggerIds`.

**Paused tags**: in the published client code they do not seem to be present (no real example of a
paused tag could be checked). Never conclude "no paused tag" from the client code alone.

## 3. Version export

```
{ "idcontainer", "idsite", "context", "name", "revision", "version": {...},
  "ignoreGtmDataLayer", "activelySyncGtmDataLayer",
  "tags": [...], "triggers": [...], "variables": [...] }
```

- **Tag**: `idtag`, `name`, `type` (`Matomo`, `CustomHtml`), `status` (`active` or paused),
  `parameters{}`, `fire_trigger_ids[]`, `block_trigger_ids[]`, `fire_limit`, `fire_delay`,
  `priority`, `start_date`, `end_date`, creation and update dates.
- **Trigger**: `idtrigger`, `name`, `type`, `parameters`, `conditions[]` with `comparison`,
  `actual` (the **name** of the variable tested, a string) and `expected`.
- **Variable**: `idvariable`, `name`, `type`, `parameters`, `lookup_table[]`, `default_value`.
  Tags reference them as `{{Name}}`.

## 4. Correspondence client code / export

| Version export | Client code |
|---|---|
| `idtag`, `idtrigger`, `idvariable` | `id` (identical) |
| `name` of the tag | `md5(name)` |
| `name` of the trigger, variable | name of the type |
| `fire_trigger_ids`, `block_trigger_ids` | `fireTriggerIds`, `blockTriggerIds` |
| `fire_limit`, `fire_delay` | `fireLimit`, `fireDelay` |
| `start_date`, `end_date` | `startDate`, `endDate` |
| `{{configMtm}}` in a parameter | inlined `MatomoConfiguration` object |
| condition `actual: "PageUrl"` (name) | condition `actual: {inlined variable}` |
| `status` | absent (only active tags are published) |
| `idcontainer` | `id` |

## 5. Types met

- Tags: `Matomo` (with `parameters.trackingType` = `pageview` or `event`, and for an event
  `eventCategory`, `eventAction`, `eventName`, `eventValue`) and `CustomHtml` (`customHtml`,
  `htmlPosition`). Other tag types exist: note the type as is.
- Triggers: `PageView`, `DomReady`, `CustomEvent` (`parameters.eventName`), `AllLinksClick`,
  `AllElementsClick`, `AllDownloadsClick`, `HistoryChange`, `ElementVisibility`.
- Condition comparisons: `equals`, `not_equals`, `contains`, `starts_with`, `regexp`, `not_regexp`,
  `match_css_selector`.
- Variables: `DataLayer`, `CustomJsFunction`, `JavaScript`, `DomElement`, `ClickHtmlAttribute`,
  `MatomoConfiguration`, plus predefined variables (`PageUrl`, `PagePath`, `FirstDirectory`,
  `ClickDestinationUrl`, `ClickClasses`, `ClickButton`...).
- `fire_limit` observed: `unlimited`. Other limits exist: note the value.

## 6. Consent

There is no tag-level consent setting in the containers analysed. Consent is read in the
**`MatomoConfiguration` variable** (in the client code it is inlined in every `Matomo` tag) and in
the tags or triggers that drive it:

| Setting (`MatomoConfiguration`) | Effect |
|---|---|
| `requireConsent` = true | no measurement request is sent until consent is given |
| `requireCookieConsent` = true | measurement works without cookies until cookie consent is given |
| `setConsentGiven`, `rememberConsentGiven` (+ duration in hours), `forgetConsentGiven` | consent given, remembered, withdrawn through the configuration |
| `enableDoNotTrack` | honours the Do Not Track header |
| `disableCookies` | measurement without cookies |

Also look for a `CustomHtml` tag that calls `_paq.push(['setConsentGiven'])` (or `requireConsent`,
`rememberConsentGiven`) fired by a CMP event, and for triggers or blockers that read the CMP state
(a `CustomJsFunction` variable on a cookie, a `CustomEvent` event).

Verdict to write in the report: "consent required by the configuration: yes/no, granted by tag X on
event Y".

**Asterisk.** If `requireConsent` and `requireCookieConsent` are both false and no tag drives
consent, do not write "Matomo measures without consent": the CMP may block the MTM container (or
the Matomo script) from loading until consent is given, which the container does not show. Write
"no consent mechanism in the container*" and ask for a real test (requests to the Matomo host before
and after the choice in the banner).

## 7. Server

`MatomoConfiguration.matomoUrl` gives the collection host. A `matomo.cloud` host indicates Matomo
Cloud, another domain generally indicates a self-hosted instance. Also note `idSite`,
`cookieDomain`, `cookieNamePrefix` and the custom endpoints (`jsEndpoint`, `trackingEndpoint`).
Distinguish "self-hosted Matomo" from a GTM server container in the report: they are not the same
thing.

## 8. MTM-specific points of attention

- **Schedule**: `start_date` / `end_date` filled in. An "active" tag whose end date has passed no
  longer sends anything: status `Inactive (expired)`. A future start date: `Active (scheduled)`.
- **Duplicates** with another tool: the same `matomoUrl` + `idSite` fed by MTM and by an HTML tag of
  another container (GTM, Tag Commander) sends every page view twice.
- **`CustomHtml` tags**: may call other trackers or push into `_paq`: read the HTML, note the
  domains called.
- **`CustomJsFunction` variables** used in conditions: read their code, this is where home-made
  consent logic hides.
- **Blocking**: a tag is blocked as soon as one of its `block_trigger_ids` is true. Apply the same
  check as in GTM: a blocker whose condition overlaps that of the trigger makes the tag
  ineffective.
