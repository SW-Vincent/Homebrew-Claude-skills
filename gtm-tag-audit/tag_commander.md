# Tag Commander (Commanders Act): client code and scope

Contents: 1. State of the documentation, 2. Recognise the source, 3. Anatomy of the client code,
4. Triggers, 5. The scope, 6. Consent, 7. Identify the vendor, 8. Points of attention, 9. Encoding.

Anonymised example: `examples/tagcommander_client_code_example.js` (13 tags, 4 listeners,
2 custom events, two forms of scope, one orphan tag, one badly encoded name).

## 1. State of the documentation

| Source | State |
|---|---|
| Client code (container file served to the browser) | **documented and tested** on a real container (generator v98.0, version 183.01, 154 tags) |
| Interface export | **not documented**: no sample was available when this was written |

For a full Tag Commander audit, ask the user for an interface export **before guessing a format**.
As soon as a sample is provided, add its structure here and the correspondence with the client
code (as for GTM and MTM), and extend `scripts/extract_container.py`. Until then, a Tag Commander
audit is a pre-audit: say so in the source limits.

## 2. Recognise the source

File header:

```
/*
 * tagContainer Generator v98.0
 * Copyright Commanders Act
 * Generated: 2026-01-15 09:00:00 Europe/Paris
 * Version : 12.03      <- container version
 * IDTC    : 5          <- container identifier
 * IDS     : 1234       <- site identifier
 */
```

Then the minified code (`/*!compressed by terser*/`) and names such as `tC.container_<IDS>_<IDTC>`,
`executeTag<ID>_<IDS>_<IDTC>`, `executeListener<ID>_<IDS>_<IDTC>`.

## 3. Anatomy of the client code

1. **`tC` library** (about 100 KB minified): of no interest for the audit.
2. **`/*VARIABLES_BLOCK*/`**: container variables, `tC.internalvars_<IDS>.initiators.var<N>`,
   numbered. Their interface name is not in the code, their body is readable.
3. **`/*CUSTOM_JS_BLOCK1*/` and `2`**: custom JavaScript of the container. To read: this is where
   data fixes and sometimes consent logic are found.
4. **Tag definitions**: `tC.extend({executeTag<ID>_<IDS>_<IDTC>:function(el,p){...}})`. The body is
   the code actually executed: script URLs, pixel identifiers, data sent. The tag name is **not**
   here but in the `launchTag` call (section 4).
5. **Triggers**: listeners and custom events (section 4).
6. **End of file**: `tC.onDomReady(function(){... tC.executeListener<ID>...})` which activates the
   listeners on load.

## 4. Triggers

Each trigger chains, for each linked tag, three calls:

```js
tC.executeTag100_1234_5(t),
tC.eventTarget.dispatchEvent("tag_trigger_dom_ready", {...}),
tC.launchTag(100, "Tag name in the interface", 1375, 1234, 5, 20)
//            ID   name                         template IDS IDTC trigger ID
```

`launchTag(ID, name, templateId, IDS, IDTC, triggerId)` gives the **tag name**, the identifier of
the tag **template** (the template name is not in the code, several tags share the same template)
and the ID of the trigger.

**Two families of triggers**:

| Family | Marker in the code | Readable name? |
|---|---|---|
| Listener | `executeListener<ID>_...:function(t){window.top.postMessage('TC.EX.TRIGGER.FIRED:{"id":20,"name":"DOM ready","idcat":1,"cat":"DOM Ready"}',"*"), ...}` | **yes**: name typed in the interface and category (`DOM Ready`, `Clicks`, `Form submission` observed) |
| Custom event | `tC.event.<name>ListFunctions.push((function(t,e){ ... tC.launchTag(..., <triggerId>) }))`; the function `tC.event.<name>(...)` is called by the site's code | **no**: identified by the event name `tC.event.<name>` and the trigger ID |

The same tag can be launched by several triggers (for example a quality-control tag launched on
many events): **a single inventory row**, with all its triggers.

Special case: `tC.launchTag('eclick','QA','-1','1234','5')` (string arguments, template `-1`) is
not a tag but the emission of a data event in an event handler: do not inventory it as a tag.

## 5. The scope

The **scope** (périmètre) is a third filter, specific to Tag Commander, added to the trigger: it
restricts a tag to specific pages or variable values (and, according to the definition retained
for this skill, to consent levels, see section 6). It is neither the trigger (when) nor a blocker
(unless). It has its own column in the workbook: `Scope (Tag Commander)`.

In the client code, the scope is **compiled into a JavaScript condition placed right in front of the
tag call**. Four kinds of conditions have been met:

| Compiled code | Reading |
|---|---|
| `"https://www.example.com/promo/"==document.location.toString()` | URL = https://www.example.com/promo/ |
| `-1!=document.location.toString().toLowerCase().indexOf("/cart".toLowerCase())` | URL contains /cart |
| `tC.internalvars.tc_pathname.toString().toLowerCase().match(new RegExp("^/checkout(/?)$".replace(...),"gi"))` | path matches the regex ^/checkout(/?)$ (case-insensitive) |
| `"trial"==tc_vars.offer_type` (or `tC.internalvars.<name>`) | variable offer_type = trial |

Conditions are joined with `&&` (AND).

### The two polarities (reading trap)

```js
COND&&(tC.executeTag..., tC.launchTag(...))     // direct form: the tag runs IF COND is true
COND||(tC.executeTag..., tC.launchTag(...))     // inverted form: the tag runs IF COND is FALSE
```

The inverted form is used to express an **inclusion of several values** with "different from"
tests. You must apply De Morgan's law to read it:

```js
"free"!=tc_vars.offer_type&&"trial"!=tc_vars.offer_type||(TAG)
```
The tag runs when `(offer_type != free AND offer_type != trial)` is FALSE, that is when
`offer_type = free OR offer_type = trial`.

```js
-1==document.location.toString().toLowerCase().indexOf("/cart".toLowerCase())&&-1==...indexOf("/account"...)||(TAG)
```
The tag runs when the URL contains `/cart` OR contains `/account`.

Never copy the raw condition into the workbook: write the reading the right way round
("offer_type = free OR offer_type = trial"). `scripts/extract_container.py` already does it (field
`scope`, with `scope_mode` = `run_if_true` or `run_if_false` and the raw code in `scope_raw`). Check
it on ambiguous cases.

No condition in front of the tag = no scope restriction: write "No condition (all pages)". Note: for
a tag launched by a click or event trigger, the trigger already limits the cases, "all pages" means
"on all the pages where the trigger occurs".

## 6. Consent

**In the client code, no consent category appears in front of the tags.** Consent is handled by a
separate module (`tC.privacy`, `TC_PRIVACY` cookie, Commanders Act consent server) loaded
independently of this file. The container code only calls `tC.privacy.init()` and reads the state
(`getOptinCategories`, `checkOptoutAllVendors`).

Consequence for the report: for Tag Commander, consent is **"not determinable from the client code
alone*"** (asterisk: to confirm with a real test, as for the other platforms). Do state, however, if
the page loads a CMP (Didomi, OneTrust, etc.), which event it emits, and whether a `tC.event.<cmp>`
handler exists in the container (an empty handler attaches no tag). To settle it: interface export
(the scope there carries, according to the definition retained, the consent levels; format to be
documented as soon as a sample exists) or the Tag Commander debug mode on the site.

## 7. Identify the vendor

The tag name is free (a team convention): it helps but proves nothing. Check in the **body of
`executeTag<ID>`**: script URLs (`connect.facebook.net`, `googletagmanager.com`, `snap.licdn.com`,
ad networks, DMPs), pixel or account identifiers, image-pixel domains. `extract_container.py`
surfaces the domains found in the `hosts` field of each tag. A tag named "Facebook" whose body loads
another domain is an anomaly to flag.

## 8. Tag Commander-specific points of attention

- **Tag defined but never launched**: present as `executeTag<ID>` but absent from every
  `launchTag` (orphan tag). Status `Inactive (never launched)`. Write "(unnamed)": the name is only
  known through `launchTag`.
- **Preproduction or test URLs in scopes** (`preprod.`, `test.`, staging domains): the production
  container contains rules for other environments.
- **Same pixel in several tools**: compare the pixel identifiers with those of the GTM and MTM
  containers of the same site.
- **Custom JavaScript** (`CUSTOM_JS_BLOCK`): read it, it sometimes modifies variables before sending
  (cleaning, character replacement).
- **Two triggers for the same tag**: compare the scopes on the same tag, they can differ from one
  trigger to the other. One row per tag, scopes listed per trigger.

## 9. Encoding

The file may contain UTF-8 text read twice as latin-1: `téléphone` appears as `tÃ©lÃ©phone`.
Marker: presence of `Ã©`, `Ã¨`, `Ã `. Repair: `text.encode('latin-1').decode('utf-8')`.
`extract_container.py` does it on tag and trigger names. Apostrophes in names are escaped (`\'`) in
the code. The example file keeps one French trigger name on purpose, to demonstrate this defect.
