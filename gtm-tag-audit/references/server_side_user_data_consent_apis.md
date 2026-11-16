# Server-side tagging, user-provided data, vendor consent modes

Contents: 1. What the script gives you, 2. Server-side tagging, 3. User-provided data (enhanced
conversions, advanced matching), 4. Vendor consent modes other than Google's, 5. How this meets the
"first consented page view" check, 6. State of the verification.

These three questions cut across platforms: answer them for every container, in every mode.

## 1. What the script gives you

`extract_container.py` prints three summary lines (`Server`, `User data`, `Consent`) with the tag
IDs concerned, one `Endpoint` line per server endpoint, and writes in the view (`--out`):

- per tag, `signals`: `{"server_side": [...], "user_data": [...], "consent_api": [...]}`, short
  sentences saying what was found;
- per GTM tag, `event_parameters`: the rows of its settings tables (parameter name → what it reads);
- at the root, `server_side`: one entry per endpoint, with the tags that declare it and the list of
  hits routed to it (event name, parameters, user-provided data, ecommerce).

Signals are searched **in each tag's own text and in the variables it references**, never in the
tool's runtime library (which contains every keyword, `server_container_url` included). They are
pattern matches: a signal says "this is present in the tag", not "this works". No signal does not
mean absent: the logic may live in the page, in the CMP or in the server container.

## 2. Server-side tagging

**Signatures**

| Where | Signature | Meaning |
|---|---|---|
| GTM Google tag (`googtag`, older `gaawc`), configuration settings, directly or through a "Google tag: configuration settings" variable | `server_container_url` (current), `transport_url` (older) | all hits of this Google tag go to that endpoint instead of Google's collection domain |
| GTM GA4 event (`gaawe`) | same measurement ID as such a Google tag | the event inherits the endpoint: the script links it ("inherits from Google tag X") |
| GTM Google Ads tags | `enableTransportUrl` = true + `transportUrl` | conversion sent through the server container |
| Custom HTML, any platform | `gtag('config', ..., {server_container_url: ...})`, `transport_url`, `first_party_collection` | same thing, hand-written |
| Third-party templates (data tags of server-side hosting vendors, etc.) | a setting holding a URL on the client's own domain or a hosting vendor's domain | probable server endpoint: name the template (GTM `customTemplate`, `permissions`) and say "to confirm" |
| Meta pixel | `eventID` in `fbq('track', ...)` | deduplication key: the same event is probably also sent server to server (Conversions API). It does not say which server |
| Tag Commander | `cact('trigger', '<event>', ...)`, hosts on `commander1.com` | Commanders Act event API and collection domain: possible server-side destinations. Seen on one real container only, to confirm |

An endpoint is typically a subdomain of the site (`sgtm.`, `metrics.`, `data.`, or a random label
such as `k7m2.`) or a hosting vendor's domain. A first-party subdomain proves nothing about what is
behind it: say "server endpoint" and what the configuration calls it.

**Map what is sent.** For each endpoint, one row per hit in the `Server-side` sheet of the workbook
(`server_side` key of the spec): platform, endpoint, tag ID, event, parameters sent (name and what
each reads: dataLayer key, cookie, DOM, constant), user-provided data, notes. Start from the
script's `server_side` entry and complete it:

- the Google tag row stands for page_view and the automatic events (enhanced measurement), plus its
  shared event settings, which travel with **every** event of that measurement ID;
- each GA4 event row: its own parameters, its user properties, ecommerce data if enabled;
- parameters that carry a consent string or a CMP state are worth naming: they show how the server
  is told about consent.

**What the web container cannot show** (write it, with the asterisk): which vendors the server
forwards to, with which transformations, and whether it honours consent. A hit that reaches the
server can be relayed to an advertising vendor whatever the browser-side blocking suggests. To
settle it: export or preview of the server container, or the vendor-side reception. Also outside
the container: a custom domain used to **load** `gtm.js` itself (visible in the page, not in the
file) and server-to-server sends made by the site's back end.

**Verdict vocabulary**: "Server-side tagging: YES, endpoint X receives <which hits>*" / "No server
endpoint declared in the container*" (the page or another tool may still send to one). Add a key
figure and a finding. In GTM, the Consent Mode verdict then becomes "not determinable from the
client container, server implementation detected*" for what the server relays (SKILL.md, Step 5).

## 3. User-provided data (enhanced conversions, advanced matching)

**Signatures**

| Vendor | Signature | Notes |
|---|---|---|
| Google Ads, conversion tag (`awct`) | `enableEnhancedConversion` = true, a user-data variable in the tag | enhanced conversions for web |
| Google Ads, `awud` tag | "User-provided data event" | enhanced conversions for leads; carries a user-data variable |
| Google, user-data variable (`awec`) | `mode` (MANUAL, AUTO, CODE) and the mapped fields (`email`, `phoneNumber`, name, address) | the script renders it as `user-provided data (mode=..., email=...)` with the source of each field |
| GA4 event or Google tag | a `user_data` parameter | user-provided data sent with the event; if the tag is routed to a server endpoint, it goes to the server |
| Custom HTML | `gtag('set','user_data', ...)`, `enhanced_conversion_data`, `allow_enhanced_conversions` | hand-written |
| Meta | `fbq('init', id, {em: ..., ph: ...})`, template setting "advanced matching" = true | advanced matching |
| Microsoft UET | template setting "enhanced conversion" = true, `uetq.push('set', {pid: {...}})` | enhanced conversions |
| TikTok | `ttq.identify({...})` | advanced matching |

**What to write, per tag**: which fields (email, phone, name, address), **where each is read**
(dataLayer key, DOM field, JS variable), to which vendor, and through which route (browser to vendor,
or browser to server endpoint). Points of attention:

- a field read **from the DOM** (form input) is fragile (breaks when the form changes) and can be read
  before the form is validated: flag it;
- **AUTO** mode lets Google's code look for the data in the page: say so, the advertiser does not
  control what is picked up;
- hashing: Google's own tags hash the data before sending; a hand-written pixel sends what it is
  given. Email or phone passed in clear to an advertising vendor in custom code stays the anomaly
  described in SKILL.md, Step 3;
- consent: for Google, sending user data to advertising depends on the `ad_user_data` signal of
  Consent Mode. Check that the container or the CMP sets it (Step 5), and say it is not visible when
  it is not;
- a disabled setting is information too: "enhanced conversions not enabled on the 17 conversion tags"
  is a useful line for the account manager.

## 4. Vendor consent modes other than Google's

Several vendors have their own consent API: the tag is loaded and **the vendor adapts** according
to a state the site pushes, instead of the tag being blocked. Describe each one found, **per vendor
and per platform**, as one row of the Consent sheet: mechanism, where the state comes from, default
state, what updates it and on which trigger.

| Vendor | Signature | States | What to check |
|---|---|---|---|
| Google | `gtag('consent','default'/'update', ...)`, consent templates (settings `ad_storage`, `analytics_storage`, `ad_user_data`, `ad_personalization`, `wait_for_update`) | granted / denied per signal | SKILL.md Step 5 and `gtm.md` section 7 |
| Microsoft Advertising (UET) | `uetq.push('consent','default', {ad_storage: ...})` then `'update'`; in the GTM UET template, consent settings (seen on a real container: `c_consentInheritGtm`, `c_consentUpdates`, meaning inferred from their names: confirm in the interface) | single signal `ad_storage`, granted / denied | a default must be pushed: without one, UET assumes granted in most countries. Is there an update, and on what trigger? |
| Meta pixel | `fbq('consent','revoke')` before `init`, then `fbq('consent','grant')`; `dataProcessingOptions` (Limited Data Use); in pixel templates, settings such as `consent`, `enableConsentMode`, `dpoLDU` | revoke (pixel fires held) / grant | `revoke` must run before `init`, on every page. Which tag calls `grant`, on what trigger? |
| Piano Analytics | `pa.consent.setMode('opt-in' / 'essential' / 'opt-out')`; by purpose: `pa.consent.setByPurpose`, `tp.consent.setByPurpose`; older SDKs: `pa.privacy.setMode(...)` | opt-in (full), essential (exempt measurement, restricted data), opt-out | **hybrid measurement**: essential by default, opt-in after consent. It is not "measurement without consent": name the modes and what switches them. Check that an opt-out exists (required by the exemption) |
| TikTok pixel | `ttq.holdConsent()`, `ttq.grantConsent()`, `ttq.revokeConsent()` | held / granted / revoked | which tag grants, on what trigger |
| Pinterest tag | `pintrk('setconsent', true/false)` | boolean | same |
| Microsoft Clarity | `clarity('consent', ...)` | boolean or per signal | same |
| Matomo | `requireConsent`, `requireCookieConsent`, `setConsentGiven`... | see `matomo_tag_manager.md` section 6 | see there |

LinkedIn's Insight tag has no consent API of this kind: it can only be blocked.

**Verdict vocabulary**: "<Vendor> consent mode present: default <state> (tag X), update on <event>
(tag Y)" / "<Vendor> tag present, no vendor consent mode found in the container*: blocked by
<condition>" / "... not gated and no consent mode found*". The asterisk rule of Step 5 applies: the
CMP often pushes these states itself, outside the container.

A vendor consent mode and a home-made block on the same tag is worth flagging: the block prevents
the vendor from ever receiving the denied-state signals, so the consent mode brings nothing (the
equivalent of Consent Mode Basic).

## 5. How this meets the "first consented page view" check

Same reasoning as SKILL.md, Step 5, moved onto the **update call**:

- a tag left ungated because a vendor consent mode adapts it is outside the pattern;
- then look at the tag that pushes the granted state (`grant`, `update`, `setMode('opt-in')`,
  `grantConsent`): it must fire on the CMP's choice event. If it only fires at page load, with a
  consent condition, consent given on the first page changes nothing until the next page: the
  pattern applies to that tag, with the same consequences;
- hits routed to a server endpoint follow the rule of the web tag that sends them: a Google tag
  gated on consent and fired only at page load loses the first page view for every vendor the
  server would have relayed it to.

## 6. State of the verification

- Checked against vendor or CMP documentation (November 2026): Google `server_container_url`,
  Microsoft UET `consent default/update` and its granted default, Meta `fbq('consent', ...)`, Piano
  `pa.consent.setMode` and its three modes, TikTok and Pinterest consent calls.
- Checked on real containers: `server_container_url` in a Google tag with GA4 events inheriting it,
  `user_data` + `awec` variable (MANUAL mode), `awud` tags, the UET and Meta template settings named
  above, a consent template with per-signal defaults.
- From general knowledge, not re-checked: Google Ads `transportUrl` settings, `uetq` `pid`,
  `ttq.identify`, `pa.privacy.setMode`, Clarity, Commanders Act `cact`. Treat as hints and confirm.
- Never seen in a sample: a server-side declaration through a settings variable in a real export,
  third-party data-tag templates, any Tag Commander server-side configuration.
