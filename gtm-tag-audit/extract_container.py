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

GTM_INFRA = {"__tg", "__hl", "__lcl", "__cl", "__fsl", "__sdl", "__tl", "__evl", "__ytl"}
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


def fix_mojibake(s):
    """Repairs UTF-8 text that was read twice as latin-1 (e.g. 'tÃ©lÃ©phone')."""
    if isinstance(s, str) and ("Ã" in s or "Â" in s):
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
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
    if re.search(r'var data = \s*\{\s*"resource"', text) or "google_tag_manager" in text[:600]:
        return ("GTM", "client code"), None
    if "tagContainer Generator" in text[:600] or re.search(r"tC\.container_\d+_\d+", text):
        return ("Tag Commander", "client code"), None
    return None, None


# -------------------------------------------------------------------------- GTM
GTM_OPS = {"_eq": "=", "_cn": "contains", "_sw": "starts with", "_ew": "ends with", "_re": "matches regex",
           "_lt": "<", "_le": "<=", "_gt": ">", "_ge": ">=", "_css": "CSS selector", "_um": "URL matches"}


def _gtm_macro_desc(m):
    f = m.get("function", "")
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
        return "JS:" + short(_gtm_render(m.get("vtp_javascript"), None), 70)
    if f == "__aev":
        return "auto-event:%s" % m.get("vtp_varType")
    if f.startswith("__cvt_"):
        return "template-variable"
    return f


def _gtm_render(v, macros):
    if isinstance(v, list) and v:
        if v[0] == "macro" and len(v) > 1:
            if macros is not None and isinstance(v[1], int) and v[1] < len(macros):
                return "{{%s}}" % _gtm_macro_desc(macros[v[1]])
            return "{{m%s}}" % v[1]
        if v[0] == "template":
            return "".join(_gtm_render(x, macros) for x in v[1:])
        if v[0] == "escape":
            return _gtm_render(v[1], macros)
        return "[" + ",".join(_gtm_render(x, macros) for x in v) + "]"
    return str(v)


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
        return "%s %s %s" % (_gtm_render(p.get("arg0"), macros), op, _gtm_render(p.get("arg1"), macros))

    firing = {j: [] for j in range(len(tags))}
    blocking = {j: [] for j in range(len(tags))}
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

    out_tags, infra = [], 0
    for j, t in enumerate(tags):
        f = t.get("function", "")
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
               "other_keys": sorted(k for k in t if not k.startswith("vtp_")
                                    and k not in ("function", "tag_id", "once_per_load", "once_per_event", "metadata"))}
        if f == "__paused":
            row["original_type"] = t.get("vtp_originalTagType")
        if f == "__html":
            row["hosts"] = hosts_in(str(_gtm_render(t.get("vtp_html"), None)))
        out_tags.append(row)

    perms = data.get("permissions", {})
    for row in out_tags:
        p = perms.get(row["type"])
        if p:
            row["permissions"] = {"inject_script": (p.get("inject_script") or {}).get("urls")}
    notes = ["Client code: tag, trigger and variable names are not in the file. The tag_id is the ID shown in the GTM interface.",
             "%d GTM infrastructure tags (listeners, trigger groups) %s." %
             (infra, "included" if include_infra else "excluded from the view")]
    meta = {"container_version": r.get("version"), "tags_total": len(tags), "tags_infrastructure": infra,
            "macros": len(macros), "predicates": len(preds), "rules": len(rules)}
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


def gtm_export(d, include_infra):
    cv = d.get("containerVersion", d)
    trig = {t["triggerId"]: t for t in cv.get("trigger", [])}

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
        tags.append({"platform": "GTM", "id": str(t.get("tagId")), "name": t.get("name"), "type": t.get("type"),
                     "status": "paused" if t.get("paused") else "active",
                     "params": params,
                     "firing": [trig_view(x) for x in t.get("firingTriggerId", [])],
                     "blocking": [trig_view(x) for x in t.get("blockingTriggerId", [])],
                     "once": t.get("tagFiringOption"), "priority": (t.get("priority") or {}).get("value"),
                     "consent_native": cs.get("consentStatus"),
                     "hosts": hosts_in(str(params.get("html", ""))) if t.get("type") == "html" else []})
    templates = [{"id": "cvt_" + str(c.get("templateId")), "name": c.get("name"),
                  "gallery": (c.get("galleryReference") or {}).get("repository")} for c in cv.get("customTemplate", [])]
    tviews = [trig_view(k) for k in trig]
    c = cv.get("container", {})
    meta = {"container_public_id": c.get("publicId"), "container_name": c.get("name"),
            "version_id": cv.get("containerVersionId"), "version_name": cv.get("name"),
            "tags_total": len(tags), "triggers": len(trig), "variables": len(cv.get("variable", [])),
            "custom_templates": templates}
    notes = ["Interface export: names, triggers, blockers and native consent settings are available.",
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
                                "setConsentGiven": c["parameters"].get("setConsentGiven")} for c in cfg]}
    notes = ["Version export: names, status, schedule dates and trigger references are available."]
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
    launch_re = re.compile(r'tC\.launchTag\((\d+),"((?:[^"\\]|\\.)*)",(-?\d+),(\d+),(\d+),(\d+)\)')

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
            rows.append({"tag_id": int(tid), "name": fix_mojibake(m.group(2).replace("\\'", "'")),
                         "template_id": int(m.group(3)), "trigger_id": int(m.group(6)),
                         "scope_raw": raw, "scope_mode": mode,
                         "scope": explain_scope(raw, mode) if mode in ("run_if_true", "run_if_false") else short(raw, 200)})
        return rows

    launches = []
    starts = [m.start() for m in lis]
    ev_pos = text.find("tC.event=tC.event||{}", starts[-1]) if starts else -1
    for n, s0 in enumerate(starts):
        e0 = starts[n + 1] if n + 1 < len(starts) else (ev_pos if ev_pos > 0 else s0 + 20000)
        launches.extend(scan(text[s0:e0]))
    for m in re.finditer(r"tC\.event\.(\w+?)ListFunctions\.push\(\(function\(t,e\)\{", text):
        end = text.find("}))", m.end())
        for row in scan(text[m.end():end]):
            row["event"] = m.group(1)
            launches.append(row)
            trig.setdefault(row["trigger_id"], {"id": row["trigger_id"], "kind": "custom event",
                                               "name": None, "category": "tC.event.%s" % m.group(1)})

    # tag definitions (body of the executed code)
    defs = {}
    dpos = [(int(m.group(1)), m.start()) for m in re.finditer(r"executeTag(\d+)_\d+_\d+:function\(el,p\)\{", text)]
    for n, (tid, p0) in enumerate(dpos):
        p1 = dpos[n + 1][1] if n + 1 < len(dpos) else len(text)
        defs[tid] = hosts_in(text[p0:p1])

    by_tag = {}
    for r in launches:
        by_tag.setdefault(r["tag_id"], []).append(r)
    tags = []
    for tid in sorted(defs):
        ls = by_tag.get(tid, [])
        tags.append({"platform": "Tag Commander", "id": str(tid), "name": ls[0]["name"] if ls else None,
                     "type": ("template %s" % ls[0]["template_id"]) if ls else None,
                     "status": "active" if ls else "defined but never launched in this file",
                     "hosts": defs[tid],
                     "launches": [{"trigger_id": r["trigger_id"],
                                   "trigger": (trig.get(r["trigger_id"], {}).get("name")
                                               or trig.get(r["trigger_id"], {}).get("category")),
                                   "trigger_kind": trig.get(r["trigger_id"], {}).get("kind"),
                                   "scope": r["scope"], "scope_raw": short(r["scope_raw"], 400),
                                   "scope_mode": r["scope_mode"]} for r in ls]})
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
    tviews = sorted(trig.values(), key=lambda x: x["id"])
    return meta, tags, tviews, notes, {"launches": launches, "defs": {str(k): v for k, v in defs.items()}}


# ---------------------------------------------------------------------- output
def one_line(t):
    def cond(c):
        if isinstance(c, dict) and "if" in c:
            s = " & ".join(c["if"])
            if c.get("unless"):
                s += " UNLESS " + " | ".join(c["unless"])
            return s
        if isinstance(c, dict):
            return "%s#%s %s" % (c.get("type"), c.get("id"), " & ".join(c.get("conditions", [])))
        return str(c)
    if t["platform"] == "Tag Commander":
        ls = t.get("launches", [])
        return "%s | %s | %s | %s | %s" % (t["id"], t.get("name"), t.get("type"),
                                          "; ".join(sorted({str(l["trigger"]) for l in ls}))[:70],
                                          "; ".join(sorted({l["scope"] for l in ls if l["scope"]}))[:110])
    return "%s | %s | %s | F: %s | B: %s" % (t["id"], t.get("name") or t.get("name_md5") or "-", t.get("type"),
                                            " || ".join(cond(c) for c in t.get("firing", []))[:110],
                                            " || ".join(cond(c) for c in t.get("blocking", []))[:110])


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
    if fn:
        meta, tags, trigs, notes, raw = fn(text, a.all)
    elif kind == ("GTM", "interface export"):
        meta, tags, trigs, notes, raw = gtm_export(parsed, a.all)
    else:
        meta, tags, trigs, notes, raw = mtm_export(parsed, a.all)

    view = {"platform": plat, "source": src, "meta": meta, "notes": notes, "tags": tags, "triggers": trigs}
    print("Platform : %s | Source : %s" % (plat, src))
    print("Meta     :", json.dumps(meta, ensure_ascii=False)[:600])
    for n in notes:
        print("Note     :", n)
    print("Tags     : %d in the view | Triggers: %d" % (len(tags), len(trigs)))
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
