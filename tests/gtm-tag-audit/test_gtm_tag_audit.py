# -*- coding: utf-8 -*-
"""Regression tests for gtm-tag-audit, run on the anonymised example containers.

    python -m unittest discover -s tests/gtm-tag-audit
"""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gtm-tag-audit")
SCRIPTS = os.path.join(ROOT, "scripts")
EXAMPLES = os.path.join(ROOT, "references", "examples")
sys.path.insert(0, SCRIPTS)

import build_audit_xlsx  # noqa: E402
import openpyxl  # noqa: E402


def extract(path):
    """Runs extract_container.py and returns (process, view or None)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "view.json")
        proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, "extract_container.py"), path, "--table",
                               "--out", out], capture_output=True, text=True)
        view = json.loads(read(out)) if os.path.exists(out) else None
    return proc, view


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def example(name):
    return os.path.join(EXAMPLES, name)


def write(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class Extraction(unittest.TestCase):
    def test_every_example_is_recognised(self):
        expected = {"gtm_client_code_example.js": ("GTM", "client code", 8),
                    "gtm_interface_export_example.json": ("GTM", "interface export", 8),
                    "mtm_client_code_example.js": ("MTM", "client code", 5),
                    "mtm_interface_export_example.json": ("MTM", "interface export", 6),
                    "tagcommander_client_code_example.js": ("Tag Commander", "client code", 13)}
        for name, (platform, source, count) in expected.items():
            proc, view = extract(example(name))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((view["platform"], view["source"], len(view["tags"])), (platform, source, count), name)

    def test_gtm_client_and_export_agree(self):
        _, client = extract(example("gtm_client_code_example.js"))
        _, export = extract(example("gtm_interface_export_example.json"))
        self.assertEqual({t["id"] for t in client["tags"]}, {t["id"] for t in export["tags"]})
        blocked = lambda v: {t["id"] for t in v["tags"] if t["blocking"]}
        self.assertEqual(blocked(client), blocked(export))

    def test_export_view_says_what_variables_read(self):
        _, export = extract(example("gtm_interface_export_example.json"))
        cookie = [v for v in export["variables"] if v["name"] == "Cookie CMP"][0]
        self.assertEqual(cookie["params"]["name"], "cmp_consent")
        _, mtm = extract(example("mtm_interface_export_example.json"))
        self.assertTrue(mtm["variables"])

    def test_gtm_export_keeps_consent_types_and_sequencing(self):
        d = json.loads(read(example("gtm_interface_export_example.json")))
        tag = d["containerVersion"]["tag"][1]
        tag["consentSettings"] = {"consentStatus": "NEEDED", "consentType": {
            "type": "LIST", "list": [{"type": "TEMPLATE", "value": "ad_storage"}]}}
        tag["setupTag"] = [{"tagName": "CMP - Consent initialization"}]
        with tempfile.TemporaryDirectory() as tmp:
            _, view = extract(write(tmp, "export.json", json.dumps(d)))
        row = view["tags"][1]
        self.assertEqual((row["consent_native"], row["consent_types"]), ("NEEDED", ["ad_storage"]))
        self.assertEqual(row["setup_tags"], ["CMP - Consent initialization"])

    def test_gtm_client_resolves_tables_consent_and_sequencing(self):
        js = '''var data = {"resource": {"version":"3","macros":[{"function":"__k","vtp_name":"cmp"},
{"function":"__remm","vtp_input":["macro",0],"vtp_map":["list",["map","key","ads=1","value","granted"]],
 "vtp_defaultValue":"denied"},{"function":"__j","vtp_name":"window.user.email"},{"function":"__e"}],
"tags":[{"function":"__awct","tag_id":5,"vtp_email":["macro",2],"consent":["list","ad_storage","ad_user_data"],
 "setup_tags":["list",["tag",1,0]],"priority":10},{"function":"__html","tag_id":6,"vtp_html":"x"}],
"predicates":[{"function":"_eq","arg0":["macro",1],"arg1":"granted"},{"function":"_eq","arg0":["macro",3],"arg1":"gtm.js"}],
"rules":[[["if",0,1],["add",0]]]},"runtime":[]};'''
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "gtm.js", js))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tag = view["tags"][0]
        condition = tag["firing"][0]["if"][0]
        self.assertIn("cookie:cmp", condition)      # the table's input is resolved
        self.assertIn("ads=1=>granted", condition)  # and its rows
        self.assertEqual(tag["params"]["email"], "{{JS variable:window.user.email}}")
        self.assertEqual(tag["consent_native"], ["ad_storage", "ad_user_data"])
        self.assertEqual((tag["setup_tags"], tag["priority"]), (["6"], 10))

    def test_tag_commander_handler_with_nested_callback(self):
        text = read(example("tagcommander_client_code_example.js"))
        patched = re.sub(r"(tC\.event\.purchaseListFunctions\.push\(\(function\(t,e\)\{)",
                         r'\1tC.onDomReady((function(){tC.log("x")})),', text, count=1)
        self.assertNotEqual(text, patched)
        with tempfile.TemporaryDirectory() as tmp:
            _, view = extract(write(tmp, "tc.js", patched))
        tag = [t for t in view["tags"] if t["id"] == "132"][0]
        self.assertEqual((tag["status"], len(tag["launches"])), ("active", 1))
        orphan = [t for t in view["tags"] if t["id"] == "140"][0]
        self.assertEqual(orphan["launches"], [])

    def test_tag_commander_name_in_single_quotes(self):
        # terser writes the name in single quotes when it contains a double quote
        text = read(example("tagcommander_client_code_example.js"))
        old = 'tC.launchTag(132,"Meta - Purchase",2652,1234,5,11)'
        self.assertIn(old, text)
        patched = text.replace(old, "tC.launchTag(132,'Meta - \"Purchase\" d\\'achat',2652,1234,5,11)")
        with tempfile.TemporaryDirectory() as tmp:
            _, view = extract(write(tmp, "tc.js", patched))
        tag = [t for t in view["tags"] if t["id"] == "132"][0]
        self.assertEqual((tag["status"], tag["name"]), ("active", 'Meta - "Purchase" d\'achat'))

    def test_tag_commander_wrongly_encoded_scope_value_is_flagged(self):
        text = read(example("tagcommander_client_code_example.js"))
        self.assertIn('"trial"', text)
        patched = text.replace('"trial"', '"pr\u00c3\u00a9contractuel"')
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "tc.js", patched))
        launch = [t for t in view["tags"] if t["id"] == "122"][0]["launches"][0]
        self.assertIn("pr\u00e9contractuel", launch["scope"])
        self.assertTrue(launch["scope_encoding_suspect"])
        self.assertIn("wrongly encoded", proc.stdout)

    def test_server_side_map_is_the_same_from_client_code_and_export(self):
        for name in ("gtm_client_code_example.js", "gtm_interface_export_example.json"):
            proc, view = extract(example(name))
            self.assertEqual(len(view["server_side"]), 1, name)
            entry = view["server_side"][0]
            self.assertEqual((entry["endpoint"], entry["declared_by"]), ("https://sgtm.example-shop.com", ["20"]))
            self.assertEqual([h["tag_id"] for h in entry["hits"]], ["20", "21"])
            self.assertEqual(entry["hits"][1]["event"], "purchase")
            self.assertEqual(list(entry["hits"][1]["parameters"]), ["value"])
            routed = {t["id"] for t in view["tags"] if (t.get("signals") or {}).get("server_side")}
            self.assertEqual(routed, {"20", "21"}, name)
            self.assertIn("Endpoint : https://sgtm.example-shop.com", proc.stdout)

    def test_runtime_keywords_are_not_signals(self):
        # the tool's own library contains every keyword: only the tags' text counts
        js = '''var data = {"resource": {"version":"1","macros":[{"function":"__e"}],
"tags":[{"function":"__googtag","tag_id":1,"vtp_tagId":"G-AAAA"}],
"predicates":[{"function":"_eq","arg0":["macro",0],"arg1":"gtm.js"}],"rules":[[["if",0],["add",0]]]},
"runtime":[["server_container_url","transport_url","user_data","fbq('consent','grant')"]]};'''
        with tempfile.TemporaryDirectory() as tmp:
            _, view = extract(write(tmp, "gtm.js", js))
        self.assertEqual(view["server_side"], [])
        self.assertFalse(view["tags"][0].get("signals"))

    def test_user_data_and_vendor_consent_signals(self):
        html = ("<script>fbq('consent','revoke');fbq('init','1',{em:'x'});"
                "window.uetq.push('consent','default',{'ad_storage':'denied'});"
                "pa.consent.setMode('essential');ttq.grantConsent();gtag('set','user_data',{email:e});</script>")
        js = '''var data = {"resource": {"version":"1","macros":[{"function":"__e"},{"function":"__v","vtp_name":"email"},
{"function":"__awec","vtp_mode":"MANUAL","vtp_email":["macro",1]}],
"tags":[{"function":"__html","tag_id":1,"vtp_html":%s},
{"function":"__awud","tag_id":2,"vtp_userDataVariable":["macro",2],"vtp_conversionId":"1"},
{"function":"__baut","tag_id":3,"vtp_c_consentUpdates":false,"vtp_c_enhancedConversion":true},
{"function":"__awct","tag_id":4,"vtp_enableEnhancedConversion":false}],
"predicates":[{"function":"_eq","arg0":["macro",0],"arg1":"gtm.js"}],"rules":[[["if",0],["add",0,1,2,3]]]}};''' % json.dumps(html)
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "gtm.js", js))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sig = {t["id"]: t.get("signals") or {} for t in view["tags"]}
        consent = " | ".join(sig["1"]["consent_api"])
        for expected in ("fbq consent revoke", "uetq consent default", "setMode(essential)", "ttq.grantConsent"):
            self.assertIn(expected, consent)
        self.assertTrue(any("advanced matching" in x for x in sig["1"]["user_data"]))
        self.assertTrue(any("gtag user_data" in x for x in sig["1"]["user_data"]))
        self.assertTrue(any("email={{dataLayer:email}}" in x for x in sig["2"]["user_data"]))
        self.assertTrue(any("c_consentUpdates=False" in x for x in sig["3"]["consent_api"]))
        self.assertTrue(any("c_enhancedConversion = true" in x for x in sig["3"]["user_data"]))
        self.assertNotIn("user_data", sig["4"])  # available but disabled: not a signal

    def test_signals_in_matomo_and_tag_commander_tags(self):
        _, mtm = extract(example("mtm_client_code_example.js"))
        self.assertTrue(any("setConsentGiven" in x for t in mtm["tags"]
                            for x in (t.get("signals") or {}).get("consent_api", [])))
        text = read(example("tagcommander_client_code_example.js"))
        marker = "executeTag111_1234_5:function(el,p){"
        self.assertIn(marker, text)
        with tempfile.TemporaryDirectory() as tmp:
            _, tc = extract(write(tmp, "tc.js", text.replace(marker, marker + "fbq('consent','revoke');")))
        tag = [t for t in tc["tags"] if t["id"] == "111"][0]
        self.assertIn("Meta consent API: fbq consent revoke", tag["signals"]["consent_api"])

    def test_regex_pattern_under_plain_operator_is_checked(self):
        # client code: blocker on event ".*" compared with "=" (regex box unchecked), and the same with _re
        js = """var data = {"resource": {"version":"1","macros":[{"function":"__e"},{"function":"__k","vtp_name":"cmp"}],
"tags":[{"function":"__awct","tag_id":5},{"function":"__awct","tag_id":6}],
"predicates":[{"function":"_eq","arg0":["macro",0],"arg1":"gtm.js"},{"function":"_eq","arg0":["macro",0],"arg1":".*"},
{"function":"_re","arg0":["macro",0],"arg1":".*"},{"function":"_cn","arg0":["macro",1],"arg1":"ads"}],
"rules":[[["if",0],["add",0,1]],[["if",1],["unless",3],["block",0]],[["if",2],["unless",3],["block",1]]]}};"""
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "gtm.js", js))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(view["checks"]), 1, view["checks"])
        self.assertIn("{{event}} = .*", view["checks"][0])
        self.assertIn("blocks tags 5", view["checks"][0])
        self.assertIn("Checks   : 1 to look at", proc.stdout)
        # export: the same on a blocker trigger, the example container itself has none
        d = json.loads(read(example("gtm_interface_export_example.json")))
        trig = [t for t in d["containerVersion"]["trigger"] if t["triggerId"] == "5"][0]
        trig["customEventFilter"] = [{"type": "EQUALS", "parameter": [
            {"type": "TEMPLATE", "key": "arg0", "value": "{{_event}}"}, {"type": "TEMPLATE", "key": "arg1", "value": ".*"}]}]
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "export.json", json.dumps(d)))
            proc0, view0 = extract(example("gtm_interface_export_example.json"))
        self.assertEqual(view0["checks"], [])
        self.assertEqual(len(view["checks"]), 1, view["checks"])
        self.assertIn("#5: {{_event}} EQUALS .*; blocks tags 40", view["checks"][0])

    def test_client_view_lists_what_variables_read(self):
        code = "function(){var s=document.querySelector('.step');return s?s.dataset.step:undefined}" + " " * 80 + "//end"
        js = """var data = {"resource": {"version":"1","macros":[{"function":"__e"},
{"function":"__jsm","vtp_javascript":["template",%s]},
{"function":"__d","vtp_elementSelector":"input#mail","vtp_attributeName":"data-value","vtp_selectorType":"CSS"}],
"tags":[{"function":"__awct","tag_id":5,"vtp_email":["macro",2]}],
"predicates":[{"function":"_eq","arg0":["macro",1],"arg1":"1"}],"rules":[[["if",0],["add",0]]]}};""" % json.dumps(code)
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "gtm.js", js))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tag = view["tags"][0]
        self.assertEqual(tag["params"]["email"], "{{DOM:input#mail (attribute data-value)}}")
        self.assertIn("[m1]", tag["firing"][0]["if"][0])  # shortened JS variable, with its index
        m1 = [v for v in view["variables"] if v["id"] == "m1"][0]
        self.assertTrue(m1["code"].endswith("//end"))  # full code in the view

    def test_meta_parameter_builder_is_a_server_side_hint(self):
        js = """var data = {"resource": {"version":"1","macros":[{"function":"__e"}],
"tags":[{"function":"__cvt_12","tag_id":7,"vtp_pixelId":"1","vtp_enableParamBuilderSdk":true},
{"function":"__html","tag_id":8,"vtp_html":"<script src=\\"https://unpkg.com/meta-capi-param-builder-clientjs/x.js\\"></script>"},
{"function":"__cvt_12","tag_id":9,"vtp_pixelId":"1","vtp_enableParamBuilderSdk":false}],
"predicates":[{"function":"_eq","arg0":["macro",0],"arg1":"gtm.js"}],"rules":[[["if",0],["add",0,1,2]]]}};"""
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "gtm.js", js))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sig = {t["id"]: (t.get("signals") or {}).get("server_side", []) for t in view["tags"]}
        self.assertTrue(any("parameter builder" in x for x in sig["7"]))
        self.assertTrue(any("parameter builder" in x for x in sig["8"]))
        self.assertEqual(sig["9"], [])

    def test_google_tag_settings_and_destination_in_export(self):
        d = json.loads(read(example("gtm_interface_export_example.json")))
        cv = d["containerVersion"]
        B = lambda k, v: {"type": "BOOLEAN", "key": k, "value": v}
        cv["gtagConfig"] = [
            {"gtagConfigId": "90", "type": "ogt_consent_defaults", "parameter": [
                B("adsToggle", "true"), B("analyticsToggle", "false"),
                {"type": "TEMPLATE", "key": "adsTargetingMode", "value": "ALL"}]},
            {"gtagConfigId": "91", "type": "ogt_dtc", "parameter": [B("preventAnalytics", "true"),
                                                                    B("restrictAdvertisingTransmission", "false")]},
            {"gtagConfigId": "92", "type": "ogt_auto_events", "parameter": [B("enableScroll", "true"),
                                                                            B("enableDownload", "false")]},
            {"gtagConfigId": "93", "type": "ogt_1p_data_v2", "parameter": [B("isEnabled", "true"),
                                                                           B("isAutoEnabled", "false")]},
            {"gtagConfigId": "94", "type": "ogt_cross_domain", "parameter": [{"type": "LIST", "key": "rules", "list": [
                {"type": "MAP", "map": [{"type": "TEMPLATE", "key": "matchType", "value": "ENDS_WITH"},
                                        {"type": "TEMPLATE", "key": "matchValue", "value": "example.com"}]}]}]}]
        cv["tag"].append({"tagId": "99", "name": "Google Ads", "type": "dest_aw", "parameter": [
            {"type": "TEMPLATE", "key": "destinationId", "value": "AW-123"}], "firingTriggerId": ["2"]})
        cv["tag"].append({"tagId": "98", "name": "Old linker", "type": "gclidw", "paused": True, "parameter": [
            B("enableUrlPassthrough", "true")], "firingTriggerId": ["2"]})
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "export.json", json.dumps(d)))
            _, plain = extract(example("gtm_interface_export_example.json"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(plain["google_tag_settings"], [])
        self.assertIn("Gtag set.: none", _.stdout)
        st = {x["type"]: x["summary"] for x in view["google_tag_settings"]}
        self.assertEqual(st["ogt_consent_defaults"],
                         "advertising denied by default (all regions); no denied default for analytics")
        self.assertIn("behavioral analytics data blocked until consent", st["ogt_dtc"])
        self.assertEqual(st["ogt_auto_events"], "on: Scroll | off: Download")
        self.assertEqual(st["ogt_1p_data_v2"], "collection on; automatic detection off; manual selectors off")
        self.assertTrue(st["ogt_cross_domain"].startswith("linker on domains: ENDS_WITH example.com"))
        self.assertIn("not URL passthrough", st["ogt_cross_domain"])
        dest = [t for t in view["tags"] if t["id"] == "99"][0]
        self.assertEqual(dest["destination"], {"destination_id": "AW-123", "product": "Google Ads"})
        self.assertTrue(any("Conversion Linker is not a gap" in n for n in view["notes"]))
        self.assertTrue(any("Conversion Linker 98 had URL passthrough on" in n for n in view["notes"]))

    def test_google_tag_settings_in_client_code_are_not_tags(self):
        url = {"contextValue": {"namespaceType": 1, "keyParts": ["hitData", "page_location"]}}
        rule = json.dumps({"type": 2, "args": [
            {"booleanExpressionValue": {"type": 4, "args": [url, {"stringValue": "^https?://example\\.com"}]}},
            {"booleanExpressionValue": {"type": 5, "args": [
                {"stringValue": "page_view"}, {"contextValue": {"namespaceType": 1, "keyParts": ["eventName"]}}]}}]})
        js = """var data = {"resource": {"version":"1","macros":[{"function":"__e"}],
"tags":[{"function":"__ogt_consent_defaults","tag_id":10,"vtp_adsToggle":true,"vtp_analyticsToggle":true,
 "vtp_adsTargetingMode":"ALL","vtp_analyticsTargetingMode":"ALL"},
{"function":"__ogt_cross_domain","tag_id":11,"vtp_rules":["list","example\\\\.com$"]},
{"function":"__ccd_ads_conv_marking","tag_id":12,"vtp_instanceDestinationId":"AW-123",
 "vtp_conversionRules":["list",["map","matchingRules",%s,"conversionLabel","LBL"]]},
{"function":"__ccd_ads_first","tag_id":13,"vtp_instanceDestinationId":"AW-123"},
{"function":"__dest_aw","tag_id":14,"vtp_destinationId":"AW-123"},
{"function":"__ecl","tag_id":15},{"function":"__awct","tag_id":16}],
"predicates":[{"function":"_eq","arg0":["macro",0],"arg1":"gtm.init"}],"rules":[[["if",0],["add",0,1,2,3,4,5,6]]]}};""" % json.dumps(rule)
        with tempfile.TemporaryDirectory() as tmp:
            proc, view = extract(write(tmp, "gtm.js", js))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(t["id"] for t in view["tags"]), ["14", "16"])  # settings and __ecl are not tags
        st = {x["type"]: x for x in view["google_tag_settings"]}
        self.assertEqual(st["ogt_consent_defaults"]["summary"],
                         "advertising denied by default (all regions); analytics denied by default (all regions)")
        self.assertTrue(st["ogt_cross_domain"]["summary"].startswith("linker on domains: example\\.com$"))
        self.assertEqual(st["ccd_ads_conv_marking"]["summary"],
                         "label LBL when (hitData.page_location matches regex '^https?://example\\.com' "
                         "AND eventName equals 'page_view')")
        self.assertEqual(st["ccd_ads_first"]["label"], "processing step")
        self.assertEqual([t for t in view["tags"] if t["id"] == "14"][0]["destination"]["product"], "Google Ads")
        self.assertIn("Setting  : Consent Mode default", proc.stdout)
        self.assertNotIn("processing step", proc.stdout)

    def test_unreadable_files_stop_with_a_message_not_a_traceback(self):
        text = read(example("gtm_client_code_example.js"))
        snippet = '// google_tag_manager loader\n(function(w,d,s,l,i){})(window,document,"script","dataLayer","GTM-X");'
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in (("truncated.js", text[:2500]), ("snippet.js", snippet)):
                proc, view = extract(write(tmp, name, content))
                self.assertNotEqual(proc.returncode, 0, name)
                self.assertIsNone(view, name)
                self.assertNotIn("Traceback", proc.stderr, name)
                self.assertIn("attachment", proc.stderr, name)


class Workbook(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(read(os.path.join(ROOT, "references", "example_spec.json")))
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "audit.xlsx")

    def tearDown(self):
        self.tmp.cleanup()

    def test_example_spec_builds_in_both_languages(self):
        build_audit_xlsx.build_workbook(self.spec, self.out)
        self.assertEqual(len(openpyxl.load_workbook(self.out).sheetnames), 4)
        fr = copy.deepcopy(self.spec)
        fr["lang"] = "fr"
        en, french = build_audit_xlsx.LABELS["en"]["statuses"], build_audit_xlsx.LABELS["fr"]["statuses"]
        for t in fr["tags"]:
            t["status"] = french[en.index(t["status"])]
        build_audit_xlsx.build_workbook(fr, self.out)
        self.assertIn("Synthèse", openpyxl.load_workbook(self.out).sheetnames)

    def test_server_side_sheet_only_when_asked(self):
        build_audit_xlsx.build_workbook(self.spec, self.out)
        wb = openpyxl.load_workbook(self.out)
        self.assertEqual(wb.sheetnames[-1], "Server-side")
        self.assertEqual(wb["Server-side"]["D4"].value, "purchase")
        del self.spec["server_side"]
        build_audit_xlsx.build_workbook(self.spec, self.out)
        self.assertEqual(len(openpyxl.load_workbook(self.out).sheetnames), 3)
        self.spec["server_side"] = [{"platform": "GTM"}]
        with self.assertRaises(ValueError):
            build_audit_xlsx.build_workbook(self.spec, self.out)

    def test_old_constats_key_still_accepted(self):
        self.spec["constats"] = self.spec.pop("findings")
        build_audit_xlsx.build_workbook(self.spec, self.out)
        ws = openpyxl.load_workbook(self.out).worksheets[2]
        self.assertTrue(any("ANOMALY 3" in str(c.value) for row in ws.iter_rows() for c in row))

    def test_text_starting_with_equals_stays_text(self):
        self.spec["tags"][0]["trigger"] = "= purchase (dataLayer event)"
        build_audit_xlsx.build_workbook(self.spec, self.out)
        cell = openpyxl.load_workbook(self.out)["Tags"]["G2"]
        self.assertEqual((cell.data_type, cell.value), ("s", "= purchase (dataLayer event)"))

    def test_inconsistent_spec_is_refused(self):
        cases = {"status": lambda s: s["tags"][0].update(status="Paused"),
                 "category": lambda s: s["tags"][0].update(category="Unknown"),
                 "consent_rows": lambda s: s["consent_rows"].append([])}
        for word, mutate in cases.items():
            spec = copy.deepcopy(self.spec)
            mutate(spec)
            with self.assertRaises(ValueError, msg=word) as ctx:
                build_audit_xlsx.build_workbook(spec, self.out)
            self.assertIn(word, str(ctx.exception))
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
