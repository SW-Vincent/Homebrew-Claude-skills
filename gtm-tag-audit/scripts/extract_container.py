#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detects the format of a tag management container and turns it into a readable,
tag-by-tag view (triggers, blockers and scopes resolved).

Recognised formats (platform, source):
  GTM            client code (gtm.js)             "var data = {"resource": ...}"
  GTM            interface export / API           {"exportFormatVersion":..., "containerVersion": {...}}
  MTM            client code (container_XXX.js)   "window.MatomoTagManager.addContainer({...})"
  MTM            interface export / API           {"idcontainer":..., "tags":[... "fire_trigger_ids"]}
  Tag Commander  client code (tc_*.js)            header comment "tagContainer Generator"
  (Tag Commander interface export: format not documented, no sample available)

Usage:
  python extract_container.py FILE [--out view.json] [--raw raw.json] [--table] [--all]

  --out    write the resolved view (meta, tags, triggers, source limits)
  --raw    also write the raw extracted object (GTM/MTM) or the TC indexes
           (use it to read a custom HTML or a JS variable in full)
  --table  print one compact line per tag (for direct reading)
  --all    include GTM infrastructure tags (__tg, __hl, __lcl, __cl...); excluded
           by default because they do not exist in interface exports

Always run this on the file on disk (an attachment), never on text pasted in chat:
these files are 250-500 KB and would flood the context window.
"""
import argparse
import json
import re
import sys

GTM_INFRA = {"__tg", "__hl", "__lcl", "__cl", "__fsl", "__sdl", "__tl", "__evl", "__ytl",
             "__ecl", "__rep"}  # click listener per trigger; remote config loader of a destination (client code only)
HOST_RE = re.compile(r"(?:https?:)?//([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})(?=[/:?\"'\\)\s]|$)", re.I)


# ------------------------------------------------------------------- utilities
def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue


def balanced_json(text, start):
    """End index (exclusive) of the {...} object starting at text[start], ignoring strings."""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
    raise ValueError("unbalanced braces (file truncated?)")


def js_block_end(text, start):
    """Index of the '}' closing the block whose opening '{' is just before text[start].
    Skips '...' and "..." strings. Returns -1 if the block never closes."""
    depth, quote, esc = 1, None, False
    for i in range(start, len(text)):
        c = text[i]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def fix_mojibake(s):
    """Repairs UTF-8 text that was read twice as latin-1 (e.g. 'tÃ©lÃ©phone')."""
    if isinstance(s, str) and ("Ã" in s or "Â" in s):
        for enc in ("cp1252", "latin-1"):  # cp1252 first: 'É' read twice gives 'Ã‰', which latin-1 cannot encode
            try:
                return s.encode(enc).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    return s


def short(s, n=140):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def hosts_in(text, limit=8):
    seen = []
    for m in HOST_RE.finditer(text or ""):
        h = m.group(1).lower()
        if h not in seen:
            seen.append(h)
    return seen[:limit]


# ---------------------------------------------------------------------- signals
# Three cross-cutting questions, answered from the text of each tag (never from the tool's own
# runtime library, which contains every keyword): does it send hits to a server-side tagging
# endpoint, does it send user-provided data (enhanced conversions, advanced matching), and does
# it drive a vendor consent API other than a plain block. Each entry: (label, regex); a %s in the
# label receives the first captured group.
Q = r"""\\?['"]"""  # a quote, possibly escaped
SIGNAL_PATTERNS = {
    "server_side": [
        ("server_container_url = %s", r"server_container_url" + Q + r"?\s*[:,=]\s*" + Q + r"?([^'\"\\,}\s]+)"),
        ("transport_url = %s", r"transport_url" + Q + r"?\s*[:,=]\s*" + Q + r"?([^'\"\\,}\s]+)"),
        ("first_party_collection flag", r"first_party_collection"),
        ("Commanders Act event API cact('trigger', '%s') (server-side platform, to confirm)",
         r"cact\(\s*" + Q + r"trigger" + Q + r"\s*,\s*" + Q + r"([\w.-]+)"),
        ("Meta eventID present: deduplication with a server-side event (Conversions API) is probable",
         r"fbq\([^)]{0,300}\beventID\b"),
        ("Meta Conversions API parameter builder loaded (prepares fbc/fbp for server events): Conversions API "
         "probable, to confirm", r"meta-capi-param-builder|clientParamBuilder"),
    ],
    "user_data": [
        ("gtag user_data set in code", r"gtag\(\s*" + Q + r"set" + Q + r"\s*,\s*" + Q + r"user_data"),
        ("user_data parameter in code", r"[{,]\s*" + Q + r"?user_data" + Q + r"?\s*:"),
        ("enhanced_conversion_data variable", r"enhanced_conversion_data"),
        ("allow_enhanced_conversions flag", r"allow_enhanced_conversions"),
        ("Meta advanced matching: fbq init with user fields (%s)",
         r"fbq\(\s*" + Q + r"init" + Q + r"\s*,[^)]{0,80}[{,]\s*" + Q + r"?(em|ph|fn|ln|external_id)" + Q + r"?\s*:"),
        ("TikTok ttq.identify (user data)", r"ttq\.identify\("),
        ("Microsoft UET enhanced conversions: uetq set pid", r"uetq\.push\(\s*" + Q + r"set" + Q + r"\s*,\s*\{\s*" + Q + r"?pid"),
    ],
    "consent_api": [
        ("Google Consent Mode: gtag consent %s", r"gtag\(\s*" + Q + r"consent" + Q + r"\s*,\s*" + Q + r"(default|update)"),
        ("Microsoft UET consent mode: uetq consent %s",
         r"uetq\.push\(\s*" + Q + r"consent" + Q + r"\s*,\s*" + Q + r"(default|update)"),
        ("Meta consent API: fbq consent %s", r"fbq\(\s*" + Q + r"consent" + Q + r"\s*,\s*" + Q + r"(revoke|grant)"),
        ("Meta Limited Data Use: dataProcessingOptions", r"dataProcessingOptions"),
        ("Piano Analytics consent mode: pa.consent.setMode(%s)", r"pa\.consent\.setMode\(\s*" + Q + r"([\w-]+)"),
        ("Piano Analytics privacy mode (older API): pa.privacy.setMode(%s)", r"pa\.privacy\.setMode\(\s*" + Q + r"([\w-]+)"),
        ("Piano consent by purpose: %s", r"((?:pa|tp)\.consent\.setByPurpose)"),
        ("TikTok consent API: ttq.%sConsent", r"ttq\.(hold|grant|revoke)Consent"),
        ("Pinterest consent API: pintrk setconsent", r"pintrk\(\s*" + Q + r"setconsent"),
        ("Microsoft Clarity consent API", r"clarity\(\s*" + Q + r"consent"),
        ("Matomo consent API: %s",
         Q + r"(requireConsent|requireCookieConsent|setConsentGiven|setCookieConsentGiven|rememberConsentGiven|"
             r"rememberCookieConsentGiven|forgetConsentGiven|forgetCookieConsentGiven)" + Q),
    ],
}
SIGNAL_RE = {cat: [(label, re.compile(rx)) for label, rx in items] for cat, items in SIGNAL_PATTERNS.items()}
CONSENT_KEY_RE = re.compile(r"consent|ldu|dpo|_storage$|wait_for_update|url_?passthrough|ads_?data_?redaction", re.I)
MATCHING_KEY_RE = re.compile(r"advanced.?matching|edvanced.?matching|enhanced.?conversion", re.I)


# A value that looks like a regular expression (".*", "^...", "...$", "\\d", "(a|b)") under an operator that
# compares plain text: GTM compares it literally, so the condition (almost) never matches. Typical case: the
# "Use regex matching" box left unchecked on a custom event trigger whose event name is ".*".
REGEX_LIKE_RE = re.compile(r"\.\*|\.\+|^\^|[^\\]\$$|\\[dwsb.]|\([^)]*\|[^)]*\)")
PLAIN_OPS = {"_eq", "_cn", "_sw", "_ew", "EQUALS", "CONTAINS", "STARTS_WITH", "ENDS_WITH"}


def regex_under_plain_operator(op, value):
    return op in PLAIN_OPS and isinstance(value, str) and bool(REGEX_LIKE_RE.search(value))


def leaves(obj):
    """Every string found in a nested structure, one per line: the text signals are searched in."""
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            out.append(v)
    walk(obj)
    return "\n".join(out)


def scan_signals(text):
    """{category: [labels]} for the patterns found in a tag's own text."""
    found = {}
    for cat, items in SIGNAL_RE.items():
        for label, rx in items:
            for m in rx.finditer(text or ""):
                value = label % m.group(1) if "%s" in label else label
                if value not in found.setdefault(cat, []):
                    found[cat].append(value)
    return found


def add_signal(row, cat, label):
    sig = row.setdefault("signals", {})
    if label not in sig.setdefault(cat, []):
        sig[cat].append(label)


def merge_signals(row, found):
    for cat, labels in found.items():
        for label in labels:
            add_signal(row, cat, label)


def setting_signals(row, scalars):
    """Signals read from a tag's own settings (name -> scalar value), whatever the template."""
    consent = ["%s=%s" % (k, scalars[k]) for k in sorted(scalars) if CONSENT_KEY_RE.search(k)]
    if consent:
        add_signal(row, "consent_api", "consent-related settings of the tag: " + short(", ".join(consent), 260))
    for k in sorted(scalars):
        if MATCHING_KEY_RE.search(k) and str(scalars[k]).lower() == "true":
            add_signal(row, "user_data", "setting %s = true" % k)
        if re.search(r"param_?builder", k, re.I) and str(scalars[k]).lower() == "true":
            add_signal(row, "server_side", "setting %s = true: Meta Conversions API parameter builder (prepares fbc/fbp "
                       "for server events); a hint of a Conversions API setup, not a proof (on by default in some "
                       "templates)" % k)


def google_routing(rows, server_map):
    """Second pass on Google tags: which GA4 events inherit the server endpoint of their Google tag.
    rows: [(row, kind, measurement_id, endpoint or None, pairs, extras)]"""
    by_id = {}
    for row, kind, mid, endpoint, pairs, extras in rows:
        if kind == "googtag" and endpoint:
            by_id.setdefault(mid, (endpoint, row["id"]))
            entry = server_map.setdefault(endpoint, {"endpoint": endpoint, "declared_by": [], "measurement_ids": [],
                                                     "hits": []})
            entry["declared_by"].append(row["id"])
            if mid not in entry["measurement_ids"]:
                entry["measurement_ids"].append(mid)
            add_signal(row, "server_side", "Google tag sends its hits to the server endpoint %s" % endpoint)
            entry["hits"].append({"tag_id": row["id"], "event": "(Google tag: page_view and automatic events unless "
                                  "disabled)", "parameters": dict(pairs), **extras})
    for row, kind, mid, endpoint, pairs, extras in rows:
        if kind == "gaawe" and mid in by_id:
            endpoint, parent = by_id[mid]
            add_signal(row, "server_side", "GA4 event routed to the server endpoint %s (inherits from Google tag %s)"
                       % (endpoint, parent))
            server_map[endpoint]["hits"].append({"tag_id": row["id"], "event": extras.pop("event", None),
                                                 "parameters": dict(pairs), **extras})


# -------------------------------------------------------------------- detection
def detect(text):
    stripped = text.lstrip()
    if stripped[:1] in "{[":
        try:
            d = json.loads(text)
        except ValueError:
            d = None
        if isinstance(d, dict):
            if "containerVersion" in d or ("tag" in d and "trigger" in d):
                return ("GTM", "interface export"), d
            tags = d.get("tags")
            if "idcontainer" in d or (isinstance(tags, list) and any("fire_trigger_ids" in t for t in tags)):
                return ("MTM", "interface export"), d
    if "MatomoTagManager.addContainer(" in text:
        return ("MTM", "client code"), None
    if re.search(r'var data = \s*\{\s*"resource"', text):
        return ("GTM", "client code"), None
    if "tagContainer Generator" in text[:600] or re.search(r"tC\.container_\d+_\d+", text):
        return ("Tag Commander", "client code"), None
    return None, None


# -------------------------------------------------------------------------- GTM
GTM_OPS = {"_eq": "=", "_cn": "contains", "_sw": "starts with", "_ew": "ends with", "_re": "matches regex",
           "_lt": "<", "_le": "<=", "_gt": ">", "_ge": ">=", "_css": "CSS selector", "_um": "URL matches"}


def _gtm_pairs(v):
    """['list', ['map', 'key', K, 'value', V], ...] -> [(K, V), ...]"""
    out = []
    if isinstance(v, list) and v and v[0] == "list":
        for row in v[1:]:
            if isinstance(row, list) and row and row[0] == "map":
                d = dict(zip(row[1::2], row[2::2]))
                out.append((d.get("key"), d.get("value")))
    return out


def _gtm_macro_desc(m, macros=None, depth=0):
    f = m.get("function", "")
    sub = macros if depth < 3 else None  # nested variables, bounded to avoid cycles

    def r(v):
        return _gtm_render(v, sub, depth + 1)

    if f in ("__smm", "__remm"):
        kind = "lookup" if f == "__smm" else "regex-table"
        pairs = ", ".join("%s=>%s" % (r(k), r(v)) for k, v in _gtm_pairs(m.get("vtp_map")))
        default = " ; default=%s" % r(m.get("vtp_defaultValue")) if "vtp_defaultValue" in m else ""
        return short("%s(%s : %s%s)" % (kind, r(m.get("vtp_input")), pairs, default), 220)
    if f == "__j":
        return "JS variable:%s" % m.get("vtp_name")
    if f == "__d":
        attr = m.get("vtp_attributeName")
        return "DOM:%s%s" % (m.get("vtp_elementId") or m.get("vtp_elementSelector"),
                             " (attribute %s)" % attr if attr else " (text)")
    if f == "__gas":
        return "GA settings (Universal Analytics):%s" % r(m.get("vtp_trackingId"))
    if f == "__awec":
        fields = ", ".join("%s=%s" % (k[4:], r(v)) for k, v in sorted(m.items())
                           if k.startswith("vtp_") and k not in ("vtp_mode", "vtp_isAutoCollectPiiEnabledFlag"))
        return short("user-provided data (mode=%s%s%s)" % (
            m.get("vtp_mode"), ": " if fields else "", fields), 220)
    if f == "__v":
        return "dataLayer:%s" % m.get("vtp_name")
    if f == "__u":
        return "url.%s" % m.get("vtp_component", "URL")
    if f == "__e":
        return "event"
    if f == "__f":
        return "referrer.%s" % m.get("vtp_component", "URL")
    if f == "__c":
        return "constant:%s" % m.get("vtp_value")
    if f == "__k":
        return "cookie:%s" % m.get("vtp_name")
    if f == "__jsm":
        return "JS:" + short(r(m.get("vtp_javascript")), 70)
    if f == "__aev":
        return "auto-event:%s" % m.get("vtp_varType")
    if f.startswith("__cvt_"):
        return "template-variable"
    return f


def _gtm_render(v, macros, depth=0):
    if isinstance(v, list) and v:
        if v[0] == "macro" and len(v) > 1:
            if macros is not None and isinstance(v[1], int) and v[1] < len(macros):
                desc = _gtm_macro_desc(macros[v[1]], macros, depth)
                if macros[v[1]].get("function") == "__jsm":  # shortened: full code in the view (variables, m<index>)
                    desc += " [m%d]" % v[1]
                return "{{%s}}" % desc
            return "{{m%s}}" % v[1]
        if v[0] == "template":
            return "".join(_gtm_render(x, macros, depth) for x in v[1:])
        if v[0] == "escape":
            return _gtm_render(v[1], macros, depth)
        return "[" + ",".join(_gtm_render(x, macros, depth) for x in v) + "]"
    return str(v)


def _gtm_tag_refs(v, tags):
    """['list', ['tag', index, option], ...] -> tag_ids of the tags fired before / after."""
    out = []
    if isinstance(v, list):
        for x in v[1:] if v and v[0] == "list" else [v]:
            if isinstance(x, list) and len(x) > 1 and x[0] == "tag" and isinstance(x[1], int) and x[1] < len(tags):
                out.append(str(tags[x[1]].get("tag_id")))
    return out


def _gtm_param_pairs(v, macros, depth=0, seen=None):
    """Every (parameter, value) row of the settings tables found in a value, following the variables
    it references (a 'Google tag: configuration / event settings' variable holds such a table)."""
    out = []
    seen = set() if seen is None else seen
    if isinstance(v, dict):
        for x in v.values():
            out += _gtm_param_pairs(x, macros, depth, seen)
    elif isinstance(v, list) and v:
        if v[0] == "map":
            d = dict(zip(v[1::2], v[2::2]))
            name = d.get("parameter", d.get("name"))
            if isinstance(name, str) and ("parameterValue" in d or "value" in d):
                out.append((name, short(_gtm_render(d.get("parameterValue", d.get("value")), macros), 160)))
                return out
        if v[0] == "macro" and len(v) > 1 and isinstance(v[1], int) and v[1] < len(macros) and depth < 3:
            if v[1] not in seen:
                seen.add(v[1])
                out += _gtm_param_pairs(macros[v[1]], macros, depth + 1, seen)
            return out
        for x in v[1:]:
            out += _gtm_param_pairs(x, macros, depth, seen)
    return out


def _gtm_macro_closure(v, macros, acc, depth=0):
    """Indexes of the variables a value references, directly or through other variables."""
    if isinstance(v, dict):
        for x in v.values():
            _gtm_macro_closure(x, macros, acc, depth)
    elif isinstance(v, list) and v:
        if v[0] == "macro" and len(v) > 1 and isinstance(v[1], int) and v[1] < len(macros):
            if v[1] not in acc and depth < 4:
                acc.add(v[1])
                _gtm_macro_closure(macros[v[1]], macros, acc, depth + 1)
            return
        for x in v:
            _gtm_macro_closure(x, macros, acc, depth)


def _google_extras(get, pairs, user_data_desc):
    """Common description of what a Google tag carries besides its event parameters."""
    extras = {}
    if str(get("sendEcommerceData")).lower() == "true":
        extras["ecommerce"] = "ecommerce data sent (source: %s)" % (get("getEcommerceDataFrom") or "dataLayer")
    if "user_data" in dict(pairs):
        extras["user_data"] = user_data_desc or dict(pairs)["user_data"]
    return extras


# Google tag settings of the container (GTM "Google tag" settings since the move to destination tags):
# gtagConfig entries in the export, __ogt_* / __ccd_* entries in the client code's tag list (they are settings,
# not tags: the export has no tag for them). __ccd_* come from the destination's own settings (Google Ads side)
# and are only in the client code. Meanings marked "to confirm" were not checked against the GTM interface.
SETTING_LABELS = {
    "ogt_consent_defaults": "Consent Mode default",
    "ogt_dtc": "data transmission controls",
    "ogt_auto_events": "events collected automatically",
    "ogt_1p_data_v2": "user-provided data",
    "ogt_cross_domain": "cross-domain (domain linking)",
    "ogt_ads_datatos": "Google Ads customer data terms",
    "ccd_ads_conv_marking": "conversions defined in Google Ads from events or URLs",
    "ccd_em_page_view": "page view settings",
    "ccd_em_form": "form events settings",
    "ccd_add_1p_data": "user-provided data accepted on hits",
}
CCD_STEPS = {"ccd_ads_first", "ccd_ads_last", "ccd_enable_cm", "ccd_ga_first", "ccd_ga_last"}
DTC_LABELS = {"preventAnalytics": "behavioral analytics data blocked until consent",
              "restrictAdvertisingTransmission": "advertising data restricted when consent is denied",
              "preventAllConsent": "\"manage default consent settings for data collection\" (per a container owner)"}
# Operators of the matching rules (booleanExpressionValue.type), read in the evaluator of the client code.
RULE_OPS = {1: "OR", 2: "AND", 3: "NOT", 4: "matches regex", 5: "equals", 6: "starts with", 7: "ends with",
            8: "contains", 9: "<", 10: "<=", 11: ">", 12: ">=", 13: "in list"}


def render_rule(e):
    """Matching rule of a __ccd_* setting (JSON) as text, e.g. (a matches regex 'x' AND b equals 'y')."""
    if isinstance(e, str):
        try:
            e = json.loads(e)
        except ValueError:
            return e
    if "booleanExpressionValue" in e:
        e = e["booleanExpressionValue"]
    if "contextValue" in e:
        return ".".join(e["contextValue"].get("keyParts", []))
    for k in ("stringValue", "integerValue", "doubleValue", "booleanValue"):
        if k in e:
            return "'%s'" % e[k] if k == "stringValue" else str(e[k])
    op, args = RULE_OPS.get(e.get("type"), "op%s" % e.get("type")), e.get("args", [])
    if op in ("OR", "AND"):
        return "(" + (" %s " % op).join(render_rule(a) for a in args) + ")"
    if op == "NOT":
        return "NOT " + render_rule(args[0])
    parts = [render_rule(a) for a in args]
    if op == "equals" and parts and parts[0].startswith("'"):  # value first: put the field first
        parts = parts[::-1]
    return "%s %s %s" % (parts[0], op, " ".join(parts[1:]))


def _truthy(v):
    return str(v).lower() == "true"


def describe_setting(kind, p):
    """One plain-language line for a Google tag setting (kind without its __ prefix, p = its parameters)."""
    if kind == "ogt_consent_defaults":
        parts = []
        for key, what in (("adsToggle", "advertising"), ("analyticsToggle", "analytics")):
            mode = p.get(key.replace("Toggle", "TargetingMode"))
            region = "all regions" if mode == "ALL" else "regions: %s" % mode if mode else "regions not stated"
            parts.append("%s denied by default (%s)" % (what, region) if _truthy(p.get(key))
                         else "no denied default for %s" % what)
        return "; ".join(parts)
    if kind == "ogt_dtc":
        on = [DTC_LABELS.get(k, k) + (" (%s)" % p["level"] if k == "restrictAdvertisingTransmission" and p.get("level")
                                      else "") for k, v in p.items() if k != "level" and _truthy(v)]
        return ("on: " + "; ".join(on)) if on else "nothing restricted (%s all off)" % ", ".join(sorted(p))
    if kind == "ogt_auto_events":
        ev = {k[6:]: _truthy(v) for k, v in p.items() if k.startswith("enable") and not k.endswith("Hidden")}
        on, off = sorted(k for k, v in ev.items() if v), sorted(k for k, v in ev.items() if not v)
        return "on: %s | off: %s" % (", ".join(on) or "none", ", ".join(off) or "none")
    if kind == "ogt_1p_data_v2":
        return "collection %s; automatic detection %s; manual selectors %s" % tuple(
            "on" if _truthy(p.get(k)) else "off" for k in ("isEnabled", "isAutoEnabled", "isManualEnabled"))
    if kind == "ogt_cross_domain":
        return ("linker on domains: %s (forms decorated, incoming links accepted, parameter in the query); "
                "this is not URL passthrough" % ", ".join(p.get("rules")) if p.get("rules") else "no domain")
    if kind == "ogt_ads_datatos":
        return "accepted: sets ads_customer_data_terms for the destination"
    if kind == "ccd_ads_conv_marking":
        return "; ".join("label %s when %s" % (r.get("conversionLabel"), render_rule(r.get("matchingRules", "{}")))
                         for r in p.get("conversionRules") or []) or "no rule"
    if kind == "ccd_add_1p_data":
        return "sources accepted: %s; on hits where %s" % (
            ", ".join(k[6:] for k, v in sorted(p.items()) if k.startswith("accept") and _truthy(v)) or "none",
            render_rule(p["matchingRules"]) if p.get("matchingRules") else "not stated")
    return ", ".join("%s=%s" % (k, v) for k, v in sorted(p.items()) if k != "instanceDestinationId") or "no setting"


def _and_conditions(e):
    """Leaf conditions of a matching rule joined by AND only (None if the rule has an OR or a NOT)."""
    e = e.get("booleanExpressionValue", e)
    op = RULE_OPS.get(e.get("type"))
    if op == "AND":
        out = []
        for a in e.get("args", []):
            sub = _and_conditions(a)
            if sub is None:
                return None
            out += sub
        return out
    if op in ("OR", "NOT"):
        return None
    return [e]


def conversion_rule_checks(settings):
    """Conversions defined in Google Ads whose URL conditions cannot hold together. Google Ads adds a domain
    condition (^https?://<domain>) fixed when the conversion event is created; if the page the user entered is
    on another host, or the domain has a character a browser never sends (accented host: sent in punycode),
    the conversion never fires."""
    out = []
    for st in settings:
        if st["type"] != "ccd_ads_conv_marking":
            continue
        for r in st["params"].get("conversionRules") or []:
            try:
                conds = _and_conditions(json.loads(r.get("matchingRules", "{}")))
            except ValueError:
                continue
            if not conds:
                continue
            hosts, pages = [], []
            for c in conds:
                args = c.get("args", [])
                field = next((".".join(a["contextValue"].get("keyParts", [])) for a in args if "contextValue" in a), "")
                val = next((a["stringValue"] for a in args if "stringValue" in a), None)
                if field != "hitData.page_location" or val is None:
                    continue
                op = RULE_OPS.get(c.get("type"))
                m = re.match(r"\^https\?://(.+)$", val) if op == "matches regex" else None
                if m:
                    hosts.append(m.group(1).replace("\\.", ".").rstrip("/"))
                elif op in ("contains", "starts with", "equals"):
                    h = re.sub(r"^https?://", "", val).split("/")[0]
                    if "." in h:
                        pages.append(h)
            why = []
            for h in hosts:
                if any(ord(ch) > 127 for ch in h):
                    why.append("domain %s has a non-ASCII character, a browser sends such a host in punycode" % h)
                for pg in pages:
                    if not (pg == h or pg.endswith("." + h)):
                        why.append("domain %s and page %s are on different hosts" % (h, pg))
            if why:
                out.append("conversion defined in Google Ads that can never fire (label %s): %s. The domain is set "
                           "by Google Ads when the conversion event is created and cannot be changed afterwards: "
                           "create a new conversion with the right domain" % (r.get("conversionLabel"), "; ".join(why)))
    return out


def setting_row(sid, kind, p, source):
    dest = p.get("instanceDestinationId")
    return {"id": sid, "type": kind, "label": SETTING_LABELS.get(kind, "processing step" if kind in CCD_STEPS
                                                                 else "unknown setting"),
            "destination": dest, "source": source, "summary": describe_setting(kind, p),
            "params": {k: v for k, v in p.items()}}


def _client_setting_params(t, macros):
    p = {}
    for k, v in t.items():
        if not k.startswith("vtp_"):
            continue
        k = k[4:]
        if k == "rules" and isinstance(v, list):  # cross-domain: ["list", "regex", ...]
            p[k] = [x for x in v[1:] if isinstance(x, str)]
        elif k == "conversionRules" and isinstance(v, list):
            p[k] = [dict(zip(x[1::2], x[2::2])) for x in v[1:] if isinstance(x, list) and x and x[0] == "map"]
        else:
            p[k] = _gtm_render(v, macros) if isinstance(v, list) else v
    return p


def destination_info(dest_id):
    pre = (dest_id or "").split("-")[0] + "-" if dest_id and "-" in dest_id else ""
    return {"destination_id": dest_id, "product": {"AW-": "Google Ads", "G-": "Google Analytics 4",
                                                     "DC-": "Floodlight / Campaign Manager 360"}.get(pre, "to confirm")}


def gtm_client(text, include_infra):
    i = text.index("var data = ") + len("var data = ")
    while text[i] != "{":
        i += 1
    data = json.loads(text[i:balanced_json(text, i)])
    r = data["resource"]
    macros, tags, preds, rules = r.get("macros", []), r.get("tags", []), r.get("predicates", []), r.get("rules", [])

    def pred_text(k):
        p = preds[k]
        op = GTM_OPS.get(p.get("function"), p.get("function"))
        return "%s %s %s%s" % (_gtm_render(p.get("arg0"), macros), op, _gtm_render(p.get("arg1"), macros),
                               " (case-insensitive)" if p.get("ignore_case") else "")

    firing = {j: [] for j in range(len(tags))}
    blocking = {j: [] for j in range(len(tags))}
    suspect = {}  # predicate index -> {"fires": set of tag_ids, "blocks": set of tag_ids}
    for ru in rules:
        # a rule is a list of clauses: ["if", ...], ["unless", ...], ["add", ...], ["block", ...]
        clauses = {}
        for c in ru:
            clauses.setdefault(c[0], []).extend(c[1:])
        cond = {"if": [pred_text(k) for k in clauses.get("if", [])],
                "unless": [pred_text(k) for k in clauses.get("unless", [])]}
        for t in clauses.get("add", []):
            firing[t].append(cond)
        for t in clauses.get("block", []):
            blocking[t].append(cond)
        for k in clauses.get("if", []) + clauses.get("unless", []):
            if regex_under_plain_operator(preds[k].get("function"), preds[k].get("arg1")):
                u = suspect.setdefault(k, {"fires": set(), "blocks": set()})
                u["fires"].update(str(tags[t].get("tag_id")) for t in clauses.get("add", []))
                u["blocks"].update(str(tags[t].get("tag_id")) for t in clauses.get("block", []))

    out_tags, infra, google_rows, server_map, settings = [], 0, [], {}, []
    for j, t in enumerate(tags):
        f = t.get("function", "")
        if f.startswith(("__ogt_", "__ccd_")):
            settings.append(setting_row(str(t.get("tag_id")), f[2:], _client_setting_params(t, macros), "client code"))
            continue
        if f in GTM_INFRA:
            infra += 1
            if not include_infra:
                continue
        row = {"platform": "GTM", "id": str(t.get("tag_id")), "index": j, "name": None, "type": f,
               "infrastructure": f in GTM_INFRA,
               "status": "paused" if f == "__paused" else "active",
               "params": {k[4:]: short(_gtm_render(v, macros), 300) for k, v in t.items() if k.startswith("vtp_")},
               "firing": firing[j], "blocking": blocking[j],
               "once": "once_per_load" if t.get("once_per_load") else ("once_per_event" if t.get("once_per_event") else "unlimited"),
               # native per-tag consent ("Additional consent checks"): list of required consent types
               "consent_native": [x for x in t["consent"][1:]] if isinstance(t.get("consent"), list) else None,
               "setup_tags": _gtm_tag_refs(t.get("setup_tags"), tags),
               "teardown_tags": _gtm_tag_refs(t.get("teardown_tags"), tags),
               "priority": t.get("priority"),
               "other_keys": sorted(k for k in t if not k.startswith("vtp_")
                                    and k not in ("function", "tag_id", "once_per_load", "once_per_event", "metadata",
                                                  "consent", "setup_tags", "teardown_tags", "priority"))}
        if f == "__paused":
            row["original_type"] = t.get("vtp_originalTagType")
        if f == "__html":
            row["hosts"] = hosts_in(str(_gtm_render(t.get("vtp_html"), None)))
        # signals: searched in the tag's own text and in the variables it references
        refs = set()
        _gtm_macro_closure(t, macros, refs)
        merge_signals(row, scan_signals(leaves(t) + "\n" + leaves([macros[n] for n in sorted(refs)])))
        setting_signals(row, {k[4:]: v for k, v in t.items() if k.startswith("vtp_") and not isinstance(v, (list, dict))})
        pairs = _gtm_param_pairs({k: v for k, v in t.items() if k.startswith("vtp_")}, macros)
        row["event_parameters"] = dict(pairs)
        awec = [_gtm_macro_desc(macros[n], macros) for n in sorted(refs) if macros[n].get("function") == "__awec"]
        if awec:
            add_signal(row, "user_data", "sends %s" % "; ".join(awec))
        if f == "__awud":
            add_signal(row, "user_data", "Google Ads user-provided data event (enhanced conversions for leads)")
        if f in ("__googtag", "__gaawc", "__gaawe"):
            get = lambda k: t.get("vtp_" + k)
            params = dict(pairs)
            endpoint = params.get("server_container_url") or params.get("transport_url")
            mid = _gtm_render(get("tagId") or get("measurementId") or get("measurementIdOverride"), macros)
            extras = _google_extras(get, pairs, "; ".join(awec))
            if f == "__gaawe":
                extras["event"] = _gtm_render(get("eventName"), macros)
            google_rows.append((row, "gaawe" if f == "__gaawe" else "googtag", mid, endpoint, pairs, extras))
        elif str(t.get("vtp_enableTransportUrl")).lower() == "true" and t.get("vtp_transportUrl"):
            endpoint = _gtm_render(t.get("vtp_transportUrl"), macros)
            add_signal(row, "server_side", "tag sends its hits to the server endpoint %s" % endpoint)
            server_map.setdefault(endpoint, {"endpoint": endpoint, "declared_by": [], "measurement_ids": [],
                                             "hits": []})["hits"].append(
                {"tag_id": row["id"], "event": f, "parameters": dict(pairs)})
        out_tags.append(row)
    google_routing(google_rows, server_map)

    perms = data.get("permissions", {})
    for row in out_tags:
        p = perms.get(row["type"])
        if p:
            row["permissions"] = {"inject_script": (p.get("inject_script") or {}).get("urls")}
    notes = ["Client code: tag, trigger and variable names are not in the file. The tag_id is the ID shown in the GTM interface.",
             "%d GTM infrastructure tags (listeners, trigger groups) %s." %
             (infra, "included" if include_infra else "excluded from the view")]
    for row in out_tags:
        if row["type"].startswith("__dest_"):
            row["destination"] = destination_info(row["params"].get("destinationId"))
    if settings:
        notes.append("%d Google tag settings (__ogt_*, __ccd_*) are listed under google_tag_settings, not as tags; "
                     "__ccd_* come from the destination's own settings (Google Ads side) and are not in the export."
                     % len(settings))
    checks = ["regex pattern under a plain-text operator, never matches as intended (regex box unchecked?): "
              "%s%s%s" % (pred_text(k), "; fires tags " + ", ".join(sorted(u["fires"])) if u["fires"] else "",
                          "; blocks tags " + ", ".join(sorted(u["blocks"])) if u["blocks"] else "")
              for k, u in sorted(suspect.items())]
    checks += conversion_rule_checks(settings)
    variables = [{"id": "m%d" % i, "type": m.get("function"), "reads": _gtm_macro_desc(m, macros),
                  **({"code": _gtm_render(m.get("vtp_javascript"), macros)} if m.get("function") == "__jsm" else {})}
                 for i, m in enumerate(macros)]
    meta = {"container_version": r.get("version"), "tags_total": len(tags), "tags_infrastructure": infra,
            "macros": len(macros), "predicates": len(preds), "rules": len(rules),
            "_server_side": list(server_map.values()), "_checks": checks, "_variables": variables,
            "_settings": settings}
    notes.append("What each {{variable}} reads is in the 'variables' list of the view (--out); a JS variable shown "
                 "shortened carries its index [mN], its full code is in that list.")
    return meta, out_tags, [], notes, data


def _gtm_params(lst):
    out = {}
    for p in lst or []:
        k, t = p.get("key"), p.get("type")
        if t in ("TEMPLATE", "BOOLEAN", "INTEGER"):
            out[k] = p.get("value")
        else:
            out[k] = short(json.dumps(p.get("list") or p.get("map") or p, ensure_ascii=False), 300)
    return out


def _gtm_filter_text(f):
    args = {p["key"]: p.get("value") for p in f.get("parameter", [])}
    neg = str(args.get("negate", "")).lower() == "true"
    return "%s%s %s %s" % ("NOT " if neg else "", args.get("arg0"), f.get("type"), args.get("arg1"))


def _export_pairs(params, variables, depth=0, seen=None):
    """Same as _gtm_param_pairs for an interface export: rows of the settings tables, following
    the {{Variable}} references."""
    out = []
    seen = set() if seen is None else seen
    for p in params or []:
        if p.get("type") == "MAP":
            d = {x.get("key"): x.get("value") for x in p.get("map", [])}
            name = d.get("parameter", d.get("name"))
            if name is not None and ("parameterValue" in d or "value" in d):
                out.append((name, d.get("parameterValue", d.get("value"))))
                continue
        out += _export_pairs(p.get("list"), variables, depth, seen)
        out += _export_pairs(p.get("map"), variables, depth, seen)
        m = re.match(r"^\{\{(.+)\}\}$", str(p.get("value", "")))
        if m and m.group(1) in variables and m.group(1) not in seen and depth < 3:
            seen.add(m.group(1))
            out += _export_pairs(variables[m.group(1)].get("parameter"), variables, depth + 1, seen)
    return out


def _export_refs(obj, variables, acc, depth=0):
    for name in re.findall(r"\{\{([^{}]+)\}\}", leaves(obj)):
        if name in variables and name not in acc and depth < 4:
            acc.add(name)
            _export_refs(variables[name], variables, acc, depth + 1)


def gtm_export(d, include_infra):
    cv = d.get("containerVersion", d)
    trig = {t["triggerId"]: t for t in cv.get("trigger", [])}
    variables = {v.get("name"): v for v in cv.get("variable", [])}
    google_rows, server_map = [], {}

    def trig_view(tid):
        t = trig.get(tid, {"name": "?", "type": "?"})
        conds = [_gtm_filter_text(f) for k in ("customEventFilter", "filter") for f in t.get(k, [])]
        row = {"id": tid, "name": t.get("name"), "type": t.get("type"), "conditions": conds}
        if t.get("type") == "TRIGGER_GROUP":
            row["group_of"] = [x["value"] for p in t.get("parameter", []) for x in p.get("list", [])]
        return row

    tags = []
    for t in cv.get("tag", []):
        cs = t.get("consentSettings", {}) or {}
        params = _gtm_params(t.get("parameter"))
        row = {"platform": "GTM", "id": str(t.get("tagId")), "name": t.get("name"), "type": t.get("type"),
                     "status": "paused" if t.get("paused") else "active",
                     "params": params,
                     "firing": [trig_view(x) for x in t.get("firingTriggerId", [])],
                     "blocking": [trig_view(x) for x in t.get("blockingTriggerId", [])],
                     "once": t.get("tagFiringOption"), "priority": (t.get("priority") or {}).get("value"),
                     "consent_native": cs.get("consentStatus"),
                     "consent_types": [x.get("value") for x in (cs.get("consentType") or {}).get("list", [])],
                     "setup_tags": [x.get("tagName") for x in t.get("setupTag", [])],
                     "teardown_tags": [x.get("tagName") for x in t.get("teardownTag", [])],
                     "hosts": hosts_in(str(params.get("html", ""))) if t.get("type") == "html" else []}
        refs = set()
        _export_refs(t.get("parameter"), variables, refs)
        merge_signals(row, scan_signals(leaves(t.get("parameter")) + "\n"
                                        + leaves([variables[n].get("parameter") for n in sorted(refs)])))
        scalars = {p.get("key"): p.get("value") for p in t.get("parameter", []) if "value" in p}
        setting_signals(row, scalars)
        pairs = _export_pairs(t.get("parameter"), variables)
        row["event_parameters"] = dict(pairs)
        awec = ["%s (%s)" % (n, short(json.dumps(_gtm_params(variables[n].get("parameter")), ensure_ascii=False), 160))
                for n in sorted(refs) if variables[n].get("type") == "awec"]
        if awec:
            add_signal(row, "user_data", "sends user-provided data variable " + "; ".join(awec))
        typ = t.get("type")
        if typ == "awud":
            add_signal(row, "user_data", "Google Ads user-provided data event (enhanced conversions for leads)")
        if typ in ("googtag", "gaawc", "gaawe") and not t.get("paused"):
            get = scalars.get
            pd = dict(pairs)
            endpoint = pd.get("server_container_url") or pd.get("transport_url")
            mid = get("tagId") or get("measurementId") or get("measurementIdOverride")
            m = re.match(r"^\{\{(.+)\}\}$", str(mid))
            if m and m.group(1) in variables:  # a constant variable holding the measurement ID
                mid = _gtm_params(variables[m.group(1)].get("parameter")).get("value", mid)
            extras = _google_extras(get, pairs, "; ".join(awec))
            if typ == "gaawe":
                extras["event"] = get("eventName")
            google_rows.append((row, "gaawe" if typ == "gaawe" else "googtag", mid, endpoint, pairs, extras))
        elif str(scalars.get("enableTransportUrl")).lower() == "true" and scalars.get("transportUrl"):
            endpoint = scalars["transportUrl"]
            add_signal(row, "server_side", "tag sends its hits to the server endpoint %s" % endpoint)
            server_map.setdefault(endpoint, {"endpoint": endpoint, "declared_by": [], "measurement_ids": [],
                                             "hits": []})["hits"].append(
                {"tag_id": row["id"], "event": typ, "parameters": dict(pairs)})
        tags.append(row)
    google_routing(google_rows, server_map)
    templates = [{"id": "cvt_" + str(c.get("templateId")), "name": c.get("name"),
                  "gallery": (c.get("galleryReference") or {}).get("repository")} for c in cv.get("customTemplate", [])]
    tviews = [trig_view(k) for k in trig]
    use = {}
    for t in cv.get("tag", []):
        for key, verb in (("firingTriggerId", "fires"), ("blockingTriggerId", "blocks")):
            for tid in t.get(key, []) or []:
                use.setdefault(tid, {"fires": [], "blocks": []})[verb].append(str(t.get("tagId")))
    checks = []
    for tid, t in trig.items():
        for f in [f for k in ("customEventFilter", "filter", "autoEventFilter") for f in t.get(k, []) or []]:
            args = {p["key"]: p.get("value") for p in f.get("parameter", [])}
            if regex_under_plain_operator(f.get("type"), args.get("arg1")):
                u = use.get(tid, {"fires": [], "blocks": []})
                checks.append("regex pattern under a plain-text operator, never matches as intended (regex box "
                              "unchecked?): trigger %s#%s: %s%s%s" % (
                                  t.get("name"), tid, _gtm_filter_text(f),
                                  "; fires tags " + ", ".join(u["fires"]) if u["fires"] else "",
                                  "; blocks tags " + ", ".join(u["blocks"]) if u["blocks"] else
                                  ("" if u["fires"] else "; used by no tag")))
    settings = []
    for g in cv.get("gtagConfig", []) or []:
        p = {}
        for prm in g.get("parameter", []) or []:
            if prm.get("key") == "rules" and prm.get("type") == "LIST":  # cross-domain rules
                p["rules"] = ["%s %s" % ({x["key"]: x.get("value") for x in m.get("map", [])}.get("matchType"),
                                         {x["key"]: x.get("value") for x in m.get("map", [])}.get("matchValue"))
                              for m in prm.get("list", [])]
            else:
                p[prm.get("key")] = prm.get("value") if prm.get("type") in ("TEMPLATE", "BOOLEAN", "INTEGER") \
                    else _gtm_params([prm]).get(prm.get("key"))
        settings.append(setting_row(str(g.get("gtagConfigId")), g.get("type"), p, "export"))
    for row in tags:
        if str(row["type"]).startswith("dest_"):
            row["destination"] = destination_info(row["params"].get("destinationId"))
    c = cv.get("container", {})
    meta = {"container_public_id": c.get("publicId"), "container_name": c.get("name"),
            "version_id": cv.get("containerVersionId"), "version_name": cv.get("name"),
            "tags_total": len(tags), "triggers": len(trig), "variables": len(cv.get("variable", [])),
            "custom_templates": templates, "_server_side": list(server_map.values()), "_checks": checks,
            "_settings": settings,
            "_variables": [{"id": v.get("variableId"), "name": v.get("name"), "type": v.get("type"),
                            "params": _gtm_params(v.get("parameter"))} for v in cv.get("variable", [])]}
    notes = ["Interface export: names, triggers, blockers and native consent settings are available.",
             "What each {{Variable}} reads is in the 'variables' list of the view (--out).",
             "Infrastructure tags (listeners) do not exist in an export: the tag count differs from the client code."]
    return meta, tags, tviews, notes, cv


# -------------------------------------------------------------------------- MTM
def _mtm_var_desc(v):
    if isinstance(v, dict) and "type" in v:
        t, p = v["type"], v.get("parameters") or {}
        if t == "DataLayer":
            return "dataLayer:%s" % p.get("dataLayerName")
        if t == "MatomoConfiguration":
            return "MatomoConfig(url=%s, idSite=%s, requireConsent=%s, requireCookieConsent=%s)" % (
                p.get("matomoUrl"), p.get("idSite"), p.get("requireConsent"), p.get("requireCookieConsent"))
        if t == "CustomJsFunction":
            return "JS:" + short(p.get("jsFunction", ""), 70)
        if t == "JavaScript":
            return "JS:%s" % p.get("variableName")
        if t == "Constant":
            return "constant:%s" % p.get("constantValue")
        if t == "Cookie":
            return "cookie:%s" % p.get("cookieName")
        if t == "DomElement":
            return "DOM:%s" % (p.get("cssSelector") or p.get("elementId"))
        return t
    return str(v)


def _mtm_render(v):
    if isinstance(v, dict):
        if "joinedVariable" in v:
            return "".join(x if isinstance(x, str) else "{{%s}}" % _mtm_var_desc(x) for x in v["joinedVariable"])
        if "type" in v and "parameters" in v:
            return "{{%s}}" % _mtm_var_desc(v)
        return {k: _mtm_render(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_mtm_render(x) for x in v]
    return v


def _mtm_tag_row(t, name, trig_view):
    p = _mtm_render(t.get("parameters", {}))
    typ = t.get("type")
    row = {"platform": "MTM", "id": str(t.get("id", t.get("idtag"))), "name": name, "type": typ,
           "params": {}, "firing": [], "blocking": [], "fire_limit": t.get("fireLimit", t.get("fire_limit")),
           "fire_delay": t.get("fireDelay", t.get("fire_delay")), "priority": t.get("priority"),
           "start_date": t.get("startDate", t.get("start_date")), "end_date": t.get("endDate", t.get("end_date"))}
    if typ == "Matomo":
        keep = ("matomoConfig", "trackingType", "eventCategory", "eventAction", "eventName", "eventValue", "idGoal",
                "customUrl", "documentTitle", "isEcommerceView", "customDimensions")
        row["params"] = {k: short(p.get(k), 200) for k in keep if p.get(k) not in (None, "", [], False)}
    elif typ == "CustomHtml":
        html = p.get("customHtml", "")
        row["params"] = {"htmlPosition": p.get("htmlPosition"), "html": short(html, 300)}
        row["hosts"] = hosts_in(str(html))
    else:
        row["params"] = {k: short(v, 200) for k, v in p.items()}
    merge_signals(row, scan_signals(leaves(t.get("parameters")) if typ != "Matomo" else
                                    leaves({k: v for k, v in (t.get("parameters") or {}).items() if k != "matomoConfig"})))
    row["firing"] = [trig_view(i) for i in t.get("fireTriggerIds", t.get("fire_trigger_ids", []))]
    row["blocking"] = [trig_view(i) for i in t.get("blockTriggerIds", t.get("block_trigger_ids", []))]
    return row


def _mtm_status(row, native_status):
    row["status"] = "active" if native_status in (None, "active") else "paused"
    if row.get("start_date") or row.get("end_date"):
        row["schedule"] = "%s -> %s" % (row.get("start_date"), row.get("end_date"))


def mtm_client(text, include_infra):
    i = text.index("MatomoTagManager.addContainer(") + len("MatomoTagManager.addContainer(")
    d = json.loads(text[i:balanced_json(text, i)])
    trig = {t["id"]: t for t in d.get("triggers", [])}

    def cond_text(c):
        return "%s %s %s" % (_mtm_var_desc(c.get("actual")), c.get("comparison"), c.get("expected"))

    def trig_view(tid):
        t = trig.get(tid, {"type": "?", "parameters": {}, "conditions": []})
        return {"id": tid, "name": None, "type": t.get("type"), "params": t.get("parameters") or {},
                "conditions": [cond_text(c) for c in t.get("conditions", [])]}

    tags = []
    for t in d.get("tags", []):
        row = _mtm_tag_row(t, None, trig_view)
        row["name_md5"] = t.get("name")
        _mtm_status(row, "active")
        tags.append(row)
    tviews = [trig_view(k) for k in trig]
    m = re.search(r"var ignoreGtmDataLayer = (\w+); var activelySyncGtmDataLayer = (\w+)", text[:2000])
    meta = {"container_id": d.get("id"), "idsite": d.get("idsite"), "version_name": d.get("versionName"),
            "revision": d.get("revision"), "environment": d.get("environment"), "tags_total": len(tags),
            "triggers": len(trig), "variables": len(d.get("variables", [])),
            "ignoreGtmDataLayer": m.group(1) if m else None}
    notes = ["Client code: tag names are replaced by their MD5 hash (name_md5); triggers and variables carry the name of "
             "their type. Tag and trigger IDs are identical to the interface.",
             "Only the published environment (%s) is visible: no drafts, no other versions." % d.get("environment"),
             "Paused tags are not in the published client code: confirm with an export."]
    return meta, tags, tviews, notes, d


def mtm_export(d, include_infra):
    trig = {t["idtrigger"]: t for t in d.get("triggers", [])}
    variables = {v["name"]: v for v in d.get("variables", [])}

    def cond_text(c):
        a = c.get("actual")
        v = variables.get(a)
        return "%s%s %s %s" % (a, " (%s)" % v["type"] if v else "", c.get("comparison"), c.get("expected"))

    def trig_view(tid):
        t = trig.get(tid, {"name": "?", "type": "?", "parameters": {}, "conditions": []})
        return {"id": tid, "name": t.get("name"), "type": t.get("type"), "params": t.get("parameters") or {},
                "conditions": [cond_text(c) for c in t.get("conditions", [])]}

    tags = []
    for t in d.get("tags", []):
        row = _mtm_tag_row(t, t.get("name"), trig_view)
        _mtm_status(row, t.get("status"))
        tags.append(row)
    cfg = [v for v in d.get("variables", []) if v.get("type") == "MatomoConfiguration"]
    meta = {"container_id": d.get("idcontainer"), "idsite": d.get("idsite"), "container_name": d.get("name"),
            "revision": d.get("revision"), "version": d.get("version"), "tags_total": len(tags),
            "triggers": len(trig), "variables": len(variables),
            "matomo_configs": [{"name": c["name"], "matomoUrl": c["parameters"].get("matomoUrl"),
                                "requireConsent": c["parameters"].get("requireConsent"),
                                "requireCookieConsent": c["parameters"].get("requireCookieConsent"),
                                "setConsentGiven": c["parameters"].get("setConsentGiven")} for c in cfg],
            "_variables": [{"id": v.get("idvariable"), "name": v.get("name"), "type": v.get("type"),
                            "params": {k: short(x, 300) for k, x in (v.get("parameters") or {}).items()},
                            "lookup_table": v.get("lookup_table") or [], "default_value": v.get("default_value")}
                           for v in d.get("variables", [])]}
    notes = ["Version export: names, status, schedule dates and trigger references are available.",
             "What each {{Variable}} reads is in the 'variables' list of the view (--out)."]
    return meta, tags, [trig_view(k) for k in trig], notes, d


# ---------------------------------------------------------------- Tag Commander
def _tc_atoms(raw):
    """Splits an 'a&&b&&c' expression into interpreted atoms."""
    atoms = []
    for a in [x for x in raw.split("&&") if x.strip()]:
        a = a.strip()
        m = re.match(r'^-1(!?)=+document\.location\.toString\(\)\.toLowerCase\(\)\.indexOf\("(.*?)"\.toLowerCase\(\)\)$', a)
        if m:
            atoms.append({"k": "url_contains", "v": m.group(2), "neg": m.group(1) == ""})
            continue
        m = re.match(r'^"(.*?)"(!?)=+document\.location\.toString\(\)$', a)
        if m:
            atoms.append({"k": "url_equals", "v": m.group(1), "neg": m.group(2) == "!"})
            continue
        m = re.match(r'^tC\.internalvars\.tc_pathname\.toString\(\)\.toLowerCase\(\)\.match\(new RegExp\("(.*?)"\.replace', a)
        if m:
            atoms.append({"k": "path_regex", "v": m.group(1), "neg": False})
            continue
        m = re.match(r'^"(.*?)"(!?)=+(tc_vars\.\w+|tc_vars\["\w+"\]|tC\.internalvars\.\w+)$', a)
        if m:
            atoms.append({"k": "variable_equals", "var": m.group(3), "v": m.group(1), "neg": m.group(2) == "!"})
            continue
        atoms.append({"k": "raw", "v": a, "neg": False})
    return atoms


def _tc_atom_text(a, negate):
    neg = a["neg"] != negate
    k = a["k"]
    if k == "url_contains":
        return 'URL %s "%s"' % ("does not contain" if neg else "contains", a["v"])
    if k == "url_equals":
        return 'URL %s "%s"' % ("!=" if neg else "=", a["v"])
    if k == "path_regex":
        return "%spath ~ /%s/i" % ("NOT " if neg else "", a["v"])
    if k == "variable_equals":
        return '%s %s "%s"' % (a["var"], "!=" if neg else "=", a["v"])
    return "%s(%s)" % ("NOT " if neg else "", a["v"])


def explain_scope(raw, mode):
    """mode 'run_if_true': the tag runs when the expression is true;
    'run_if_false': compiled form 'expr||(tag)', the tag runs when the expression is false."""
    if not raw:
        return ""
    atoms = _tc_atoms(raw)
    if mode == "run_if_true":
        return " AND ".join(_tc_atom_text(a, False) for a in atoms)
    return " OR ".join(_tc_atom_text(a, True) for a in atoms)


def tc_client(text, include_infra):
    head = text[:800]

    def g(pat):
        m = re.search(pat, head)
        return m.group(1).strip() if m else None

    meta = {"generator": g(r"tagContainer Generator v([\d.]+)"), "generated": g(r"Generated:\s*([^\r\n]+)"),
            "container_version": g(r"Version\s*:\s*([\d.]+)"), "idtc": g(r"IDTC\s*:\s*(\d+)"), "ids": g(r"IDS\s*:\s*(\d+)")}

    # listener triggers (name and category are exposed in the code)
    trig = {}
    lis = list(re.finditer(
        r'executeListener(\d+)_\d+_\d+:function\(t\)\{window\.top\.postMessage\(\'TC\.EX\.TRIGGER\.FIRED:\{\\?"id\\?":(\d+),'
        r'\\?"name\\?":\\?"(.*?)\\?",\\?"idcat\\?":(\d+),\\?"cat\\?":\\?"(.*?)\\?"\}', text))
    for m in lis:
        trig[int(m.group(2))] = {"id": int(m.group(2)), "kind": "listener",
                                 "name": fix_mojibake(m.group(3).replace("\\'", "'")),
                                 "category": fix_mojibake(m.group(5))}
    # the name is in double quotes, or in single quotes when it contains a double quote
    launch_re = re.compile(r"""tC\.launchTag\((\d+),(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'),"""
                           r"""(-?\d+),(\d+),(\d+),(\d+)\)""")

    def tag_name(m):
        raw_name = m.group(2) if m.group(2) is not None else m.group(3)
        return fix_mojibake(raw_name.replace("\\'", "'").replace('\\"', '"'))

    def scan(body):
        rows, prev = [], 0
        for m in launch_re.finditer(body):
            tid = m.group(1)
            pos = body.rfind("tC.executeTag%s_" % tid, 0, m.start())
            prefix = body[prev:pos] if pos >= 0 else ""
            prev = m.end()
            if "postMessage" in prefix:
                prefix = prefix.split('"*"),')[-1]
            # residue of the previous statement: ')' closing its conditional group, then ','
            prefix = re.sub(r"^[),\s]+", "", prefix).strip()
            raw, mode = "", ""
            if prefix.endswith("&&("):
                raw, mode = prefix[:-3], "run_if_true"
            elif prefix.endswith("||("):
                raw, mode = prefix[:-3], "run_if_false"
            elif prefix:
                raw, mode = prefix, "raw"
            scope = explain_scope(raw, mode) if mode in ("run_if_true", "run_if_false") else short(raw, 200)
            rows.append({"tag_id": int(tid), "name": tag_name(m),
                         "template_id": int(m.group(4)), "trigger_id": int(m.group(7)),
                         "scope_raw": raw, "scope_mode": mode,
                         # readable form repaired; scope_raw keeps the value exactly as compiled
                         "scope": fix_mojibake(scope), "scope_encoding_suspect": fix_mojibake(scope) != scope})
        return rows

    launches = []
    starts = [m.start() for m in lis]
    ev_pos = text.find("tC.event=tC.event||{}", starts[-1]) if starts else -1
    for n, s0 in enumerate(starts):
        e0 = starts[n + 1] if n + 1 < len(starts) else (ev_pos if ev_pos > 0 else s0 + 20000)
        launches.extend(scan(text[s0:e0]))
    handlers = list(re.finditer(r"tC\.event\.(\w+?)ListFunctions\.push\(\(function\(t,e\)\{", text))
    for n, m in enumerate(handlers):
        end = js_block_end(text, m.end())  # not the first "}))": a handler may contain nested callbacks
        if end < 0:
            end = text.find("}))", m.end())
        if n + 1 < len(handlers):  # never read into the next handler
            end = min(end, handlers[n + 1].start())
        for row in scan(text[m.end():end]):
            row["event"] = m.group(1)
            launches.append(row)
            trig.setdefault(row["trigger_id"], {"id": row["trigger_id"], "kind": "custom event",
                                               "name": None, "category": "tC.event.%s" % m.group(1)})

    # tag definitions (body of the executed code)
    defs, bodies = {}, {}
    dpos = [(int(m.group(1)), m.start()) for m in re.finditer(r"executeTag(\d+)_\d+_\d+:function\(el,p\)\{", text)]
    for n, (tid, p0) in enumerate(dpos):
        p1 = dpos[n + 1][1] if n + 1 < len(dpos) else len(text)
        defs[tid] = hosts_in(text[p0:p1])
        bodies[tid] = scan_signals(text[p0:p1])

    by_tag = {}
    for r in launches:
        by_tag.setdefault(r["tag_id"], []).append(r)
    tags = []
    for tid in sorted(defs):
        ls = by_tag.get(tid, [])
        tags.append({"platform": "Tag Commander", "id": str(tid), "name": ls[0]["name"] if ls else None,
                     "type": ("template %s" % ls[0]["template_id"]) if ls else None,
                     "status": "active" if ls else "defined but never launched in this file",
                     "hosts": defs[tid], "signals": bodies.get(tid, {}),
                     "launches": [{"trigger_id": r["trigger_id"],
                                   "trigger": (trig.get(r["trigger_id"], {}).get("name")
                                               or trig.get(r["trigger_id"], {}).get("category")),
                                   "trigger_kind": trig.get(r["trigger_id"], {}).get("kind"),
                                   "scope": r["scope"], "scope_raw": short(r["scope_raw"], 400),
                                   "scope_mode": r["scope_mode"],
                                   "scope_encoding_suspect": r["scope_encoding_suspect"]} for r in ls]})
    meta.update({"tags_defined": len(defs), "tags_launched": len(by_tag),
                 "listeners": len([t for t in trig.values() if t["kind"] == "listener"]),
                 "custom_event_triggers": len([t for t in trig.values() if t["kind"] != "listener"]),
                 "internal_vars": len(set(re.findall(r"initiators\.var(\d+)=function", text)))})
    notes = ["Client code: the scope is compiled into JS conditions placed in front of each tag; the URLs and variables "
             "tested are readable (field scope).",
             "Inverted form: 'expr||(tag)' means the tag runs when expr is FALSE (scope_mode = run_if_false). "
             "The scope field is already turned the right way round (De Morgan).",
             "Per-tag consent categories are NOT visible in this file: they belong to the separate privacy module "
             "(tC.privacy, TC_PRIVACY cookie). Treat consent as not determinable from the client code alone*.",
             "Tag names and listener trigger names are the ones typed in the interface; custom-event triggers have no "
             "name in the code (identified by the tC.event.<name> event).",
             "A text containing 'Ã©' is UTF-8 read twice: repaired automatically at extraction."]
    suspect = sorted({r["tag_id"] for r in launches if r["scope_encoding_suspect"]})
    if suspect:
        notes.append("Scope values wrongly encoded (e.g. 'Ã©' for 'é') on tags %s: shown repaired in scope, kept as "
                     "compiled in scope_raw. If the served file really holds this value, the condition may never "
                     "match the site's variable: check on the live site, or whether the file was re-encoded when saved."
                     % ", ".join(str(x) for x in suspect))
    tviews = sorted(trig.values(), key=lambda x: x["id"])
    return meta, tags, tviews, notes, {"launches": launches, "defs": {str(k): v for k, v in defs.items()}}


# ---------------------------------------------------------------------- output
def cut(s, n):
    return s if len(s) <= n else s[: n - 1] + "…(cut, see --out)"


def one_line(t):
    def cond(c):
        if isinstance(c, dict) and "if" in c:
            s = " & ".join(c["if"])
            if c.get("unless"):
                s += " UNLESS " + " | ".join(c["unless"])
            return s
        if isinstance(c, dict):
            ev = (c.get("params") or {}).get("eventName") if isinstance(c.get("params"), dict) else None
            return "%s#%s%s %s" % (c.get("name") or c.get("type"), c.get("id"), " [event=%s]" % ev if ev else "",
                                   " & ".join(c.get("conditions", [])))
        return str(c)
    if t["platform"] == "Tag Commander":
        ls = t.get("launches", [])
        return "%s | %s | %s | %s | %s" % (t["id"], t.get("name"), t.get("type"),
                                          cut("; ".join(sorted({str(l["trigger"]) for l in ls})), 70),
                                          cut("; ".join(sorted({l["scope"] for l in ls if l["scope"]})), 110))
    return "%s | %s | %s | F: %s | B: %s" % (t["id"], t.get("name") or t.get("name_md5") or "-", t.get("type"),
                                            cut(" || ".join(cond(c) for c in t.get("firing", [])), 110),
                                            cut(" || ".join(cond(c) for c in t.get("blocking", [])), 110))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--out")
    ap.add_argument("--raw")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    text = read_text(a.file)
    kind, parsed = detect(text)
    if not kind:
        sys.exit("Format not recognised. Expected: gtm.js, GTM export (JSON), MTM container code, MTM export (JSON) or "
                 "Tag Commander container code. For a Tag Commander interface export, see references/tag_commander.md. "
                 "If the file was truncated (unbalanced braces), ask for the complete file as an attachment.")
    plat, src = kind
    fn = {("GTM", "client code"): gtm_client, ("MTM", "client code"): mtm_client,
          ("Tag Commander", "client code"): tc_client}.get(kind)
    try:
        if fn:
            meta, tags, trigs, notes, raw = fn(text, a.all)
        elif kind == ("GTM", "interface export"):
            meta, tags, trigs, notes, raw = gtm_export(parsed, a.all)
        else:
            meta, tags, trigs, notes, raw = mtm_export(parsed, a.all)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        sys.exit("Recognised as %s (%s) but could not be read: %s. The file is probably truncated or incomplete: "
                 "ask for the complete file as an attachment." % (plat, src, e))

    variables = meta.pop("_variables", [])
    server_side = meta.pop("_server_side", [])
    checks = meta.pop("_checks", None)  # None: no mechanical check written for this platform yet
    settings = meta.pop("_settings", None)
    view = {"platform": plat, "source": src, "meta": meta, "notes": notes, "tags": tags, "triggers": trigs,
            "variables": variables, "server_side": server_side, "checks": checks}
    if settings is not None:
        view["google_tag_settings"] = settings
        dests = [t for t in tags if t.get("destination")]
        if dests:
            notes.append("Destination tags (%s): they do the conversion linking, so a paused or absent Conversion "
                         "Linker is not a gap." % ", ".join("%s %s" % (t["id"], t["destination"]["destination_id"])
                                                            for t in dests))
            for t in tags:
                if t["type"] in ("gclidw", "__gclidw") and t.get("status") == "paused" and \
                        _truthy(t["params"].get("enableUrlPassthrough")):
                    notes.append("The paused Conversion Linker %s had URL passthrough on, and no Google tag setting of "
                                 "this container sets it: URL passthrough is probably lost (to confirm in the "
                                 "interface, or set by the CMP)." % t["id"])
    print("Platform : %s | Source : %s" % (plat, src))
    print("Meta     :", json.dumps(meta, ensure_ascii=False)[:600])
    for n in notes:
        print("Note     :", n)
    print("Tags     : %d in the view | Triggers: %d" % (len(tags), len(trigs)))
    for cat, title in (("server_side", "Server   "), ("user_data", "User data"), ("consent_api", "Consent  ")):
        ids = [t["id"] for t in tags if (t.get("signals") or {}).get(cat)]
        print("%s: %s" % (title, ("tags " + ", ".join(ids)) if ids else "no signal in the tags"))
    print("Checks   : %s" % ("not available for %s yet" % plat if checks is None else
                               "%d to look at" % len(checks) if checks else "nothing found"))
    for c in checks or []:
        print("Check    :", c)
    if settings is not None:
        shown = [x for x in settings if x["label"] != "processing step"]
        print("Gtag set.: %s" % ("%d settings" % len(shown) if shown else
                                 "none (container without Google tag settings: not migrated to destination tags)"))
        for x in shown:
            print("Setting  : %s [%s %s%s]: %s" % (x["label"], x["type"], x["id"],
                                                   " " + x["destination"] if x["destination"] else "", x["summary"]))
    for e in server_side:
        print("Endpoint : %s <- declared by tag(s) %s, %d hit type(s) mapped (detail in --out, key server_side)"
              % (e["endpoint"], ", ".join(e["declared_by"]) or "-", len(e["hits"])))
    if a.table:
        print("-" * 60)
        for t in tags:
            print(one_line(t))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(view, f, ensure_ascii=False, indent=1)
        print("View written ->", a.out)
    if a.raw:
        with open(a.raw, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        print("Raw written  ->", a.raw)


if __name__ == "__main__":
    main()
