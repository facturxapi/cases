#!/usr/bin/env python3
"""seed_product_runs.py — write the PR-* cases of the two dated staging captures already published on facturxapi.com/demo.

    python3 scripts/seed_product_runs.py --demo-dir /path/to/facturx-validation-web/public/demo [--out corpus-root]

Sources: integration-proof-20261105 (JSON ERP to Factur-X PDF + XML, convert) and scan-test-files-20261106 (the two /scan test files). The sizes and SHA-256
come from each folder's manifest.json, after re-hashing the local file; a mismatch stops the run. Nothing is copied: a case points at the served URL.
The observations are the ones those folders already publish (their README, oracles and projections); this script adds the structure, not new results.
"""
import argparse
import hashlib
import json
import os
import sys

BASE = "https://facturxapi.com/demo/"
RIGHTS = "MIT; authored synthetic data, no customer input (see the manifest.json of the capture)"


def digest(path):
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data).hexdigest(), len(data)


class Folder:
    def __init__(self, demo, name):
        self.demo, self.name = demo, name
        with open(os.path.join(demo, name, "manifest.json"), encoding="utf-8") as f:
            self.manifest = json.load(f)

    def item(self, rel, what):
        sha, size = digest(os.path.join(self.demo, self.name, rel))
        listed = self.manifest["files"].get(rel)
        if not listed or listed["sha256"] != sha or listed["bytes"] != size:
            sys.exit("refused: %s/%s does not match its manifest.json entry" % (self.name, rel))
        return {"what": what, "source": {"type": "url", "url": "%s%s/%s" % (BASE, self.name, rel)}, "sha256": sha, "bytes": size}


def layer(state, reason=None, expectation=None, observed=None):
    out = {"expectation": expectation, "observed": observed, "state": state}
    if reason:
        out["reason"] = reason
    return out


def observed(verdict, engine, evidence, ids=None):
    out = {"verdict": verdict, "engine": engine, "evidence": evidence}
    if ids is not None:
        out["ids"] = ids
    return out


def write(out, case):
    path = os.path.join(out, "cases", case["id"])
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "case.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(case, indent=1, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--demo-dir", required=True)
    parser.add_argument("--out", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = parser.parse_args()
    demo = os.path.abspath(args.demo_dir)

    # ---- PR-0001: convert (JSON ERP -> Factur-X PDF + XML), staging 2026-11-05
    f = Folder(demo, "integration-proof-20261105")
    ev = {
        "capture": f.item("capture.json", "date, request and HTTP status of the capture"),
        "response": f.item("response.json", "the complete HTTP response (PDF and XML base64-encoded)"),
        "result_pdf": f.item("result.pdf", "the Factur-X PDF the API returned"),
        "result_xml": f.item("result.xml", "the CII XML the API returned"),
        "oracles": f.item("oracles/oracles.json", "independent checks: XSD, CEN Schematron, PDF/A-3B"),
        "cen_svrl": f.item("oracles/cen-svrl.xml", "SVRL report of the official CEN EN16931 1.3.16 Schematron on the returned XML"),
        "mustang_pdf": f.item("oracles/mustang-pdf.xml", "Mustang / veraPDF report on the returned PDF"),
        "preservation": f.item("preservation.json", "comparison of the input values with the XML and PDF output"),
        "manifest": {"what": "sizes and SHA-256 of every published file of the capture", "source": {"type": "url", "url": BASE + f.name + "/manifest.json"}, "sha256": digest(os.path.join(demo, f.name, "manifest.json"))[0], "bytes": digest(os.path.join(demo, f.name, "manifest.json"))[1]},
    }
    api = f.manifest["api_build"]["commit_sha"]
    case = {
        "schema_version": 1, "id": "PR-0001-erp-json-to-facturx-pdfa3",
        "title": "ERP JSON converted to a Factur-X PDF/A-3 and CII XML on staging (target EN16931)",
        "kind": "product-run", "class": "valid", "synthetic": True, "rights": RIGHTS,
        "inputs": [dict(role="invoice_data", format="JSON", **{k: f.item("invoice.json", "")[k] for k in ("source", "sha256", "bytes")})],
        "evidence": ev,
        "layers": {
            "packaging": layer("confirmed", expectation={"verdict": "pass"}, observed=observed("pass", "veraPDF 1.26.5 via Mustang CLI 2.24.0 (PDF/A-3B)", ["oracles", "mustang_pdf"])),
            "facturx_profile": layer("confirmed", expectation={"verdict": "pass"}, observed=observed("pass", "lxml 6.1.0 against Factur-X_1.09.2_EN16931.xsd", ["oracles"])),
            "en16931": layer("confirmed", expectation={"verdict": "pass", "ids": []}, observed=observed("pass", "official CEN validation-1.3.16 XSLT, SaxonC-HE 12.9.0 (a second reference: the service applies the Factur-X pack for CII)", ["oracles", "cen_svrl"], ids=[])),
            "fr_ctc": layer("not_evaluated", reason="no France CTC validation was run or claimed in this capture"),
            "pa_acceptance": layer("not_evaluated", reason="a technical check never proves acceptance by a PA"),
        },
        "runs": [{"kind": "api-call", "target": "staging", "when": f.manifest["primary_capture"]["started_at"].replace("+00:00", "Z").split(".")[0] + "Z",
                  "api_build": {"commit_sha": api, "build_date": f.manifest["api_build"]["build_date"]},
                  "request": "POST /api/v1/convert?enrich=false with invoice_data=invoice.json, validation_target=en16931, output=facturx_pdfa3 (a staging API key is needed to replay it)",
                  "receipts": ["capture", "response", "result_pdf", "result_xml", "oracles", "cen_svrl", "mustang_pdf", "preservation", "manifest"]}],
        "limits": [
            "Staging at the build above, on the date above: not production, and it can change if the rules or the service change.",
            "Five texts of the input are not kept identically in the visible PDF (for example an em dash becomes a question mark and the euro sign becomes EUR); the accents of this example do not prove support for all Unicode characters.",
            "A text annex added to a source PDF disappeared from the returned PDF in a second test, although the response was a success (see the attachment-probe folder of the capture).",
            "No lossless conversion, no France CTC validation, no Peppol / XRechnung conformity and no acceptance by a PA is shown by this case.",
        ],
    }
    write(args.out, case)

    # ---- PR-0002 and PR-0003: the two /scan test files, staging 2026-11-06
    g = Folder(demo, "scan-test-files-20261106")
    ref = g.manifest["referenced_not_copied"]["/demo/facturx-valid-sample.pdf"]
    meta = json.load(open(os.path.join(demo, g.name, "staging/api-meta-after.json"), encoding="utf-8"))["build"]
    cap = json.load(open(os.path.join(demo, g.name, "capture.json"), encoding="utf-8"))
    common = {
        "capture": g.item("capture.json", "date, request, API build before and after, and digests of the unpublished raw responses"),
        "api_meta": g.item("staging/api-meta-after.json", "the API build and the Schematron authority used for CII, read after the calls"),
        "oracle": g.item("oracles/cen-en16931-cii-1.3.16.json", "offline check with the official CEN EN16931 CII Schematron 1.3.16 (SaxonC-HE 12.9.0)"),
        "manifest": {"what": "sizes and SHA-256 of every published file of the capture", "source": {"type": "url", "url": BASE + g.name + "/manifest.json"}, "sha256": digest(os.path.join(demo, g.name, "manifest.json"))[0], "bytes": digest(os.path.join(demo, g.name, "manifest.json"))[1]},
    }
    when = cap["started_at"]
    run_base = {"kind": "api-call", "target": "staging", "when": when, "api_build": {"commit_sha": meta["commit_sha"], "build_date": meta["build_date"]},
                "note": "the france_2026 response for the valid file dates from 16:24Z (first pass); the three others from 16:25Z (capture.json)"}
    valid_ev = dict(common, en16931_response=g.item("staging/facturx-valid-sample.en16931.json", "projection of the /scan response, target en16931"), france_response=g.item("staging/facturx-valid-sample.france_2026.json", "projection of the /scan response, target france_2026"))
    valid = {
        "schema_version": 1, "id": "PR-0002-scan-valid-sample-facturx", "title": "The valid Factur-X sample PDF scanned on staging (targets EN16931 and France 2026)",
        "kind": "product-run", "class": "valid", "synthetic": True, "rights": RIGHTS,
        "inputs": [{"role": "invoice", "format": "PDF", "source": {"type": "url", "url": BASE.replace("/demo/", "") + "/demo/facturx-valid-sample.pdf"}, "sha256": ref["sha256"], "bytes": ref["bytes"]}],
        "evidence": valid_ev,
        "layers": {
            "packaging": layer("confirmed", expectation={"verdict": "pass"}, observed=observed("pass", "FacturX API staging /api/scan: checks pdfa and facturx_pdf passed", ["en16931_response"])),
            "facturx_profile": layer("confirmed", expectation={"verdict": "pass"}, observed=observed("pass", "FacturX API staging /api/scan: checks xsd and schematron passed, facturxProfile passed", ["en16931_response"])),
            "en16931": layer("confirmed", expectation={"verdict": "pass", "ids": []}, observed=observed("pass", "FacturX API staging /api/scan target en16931; cross-checked offline with the official CEN CII Schematron 1.3.16 (0 failed assertion)", ["en16931_response", "oracle"], ids=[])),
            "fr_ctc": layer("confirmed", expectation={"verdict": "pass"}, observed=observed("pass", "FacturX API staging /api/scan target france_2026: frCtc passed, reason fr_ctc_no_findings", ["france_response"])),
            "pa_acceptance": layer("not_evaluated", reason="the responses report paAcceptance as not_submitted: nothing was sent to a PA"),
        },
        "runs": [dict(run_base, request="POST /api/scan with the file and validation_target=en16931, then france_2026 (public scanner, no key)", receipts=["capture", "en16931_response", "france_response", "oracle", "api_meta", "manifest"])],
        "limits": [
            "Staging at the build above, on the date above: not production, and it can change if the rules or the service change.",
            "The service applies the Factur-X 1.09.2 Schematron pack for CII; the CEN XSLT is loaded but not routed for this format (api_meta), so the CEN check here is a second reference run outside the service.",
            "A pass on these layers is not an acceptance by a PA.",
        ],
    }
    write(args.out, valid)
    inv_ev = dict(common, xml=g.item("facture-exemple-invalide-br-co-16.xml", "the XML embedded in the valid PDF, with two changes (invoice number suffix, BT-115 amount due)"),
                  en16931_response=g.item("staging/facture-exemple-invalide-br-co-16.en16931.json", "projection of the /scan response, target en16931"),
                  france_response=g.item("staging/facture-exemple-invalide-br-co-16.france_2026.json", "projection of the /scan response, target france_2026"))
    invalid = {
        "schema_version": 1, "id": "PR-0003-scan-invalid-br-co-16", "title": "A CII XML whose amount due (BT-115) does not equal the invoice total, scanned on staging",
        "kind": "product-run", "class": "error", "synthetic": True, "rights": RIGHTS,
        "inputs": [dict(role="invoice", format="CII", **{k: inv_ev["xml"][k] for k in ("source", "sha256", "bytes")})],
        "evidence": inv_ev,
        "layers": {
            "packaging": layer("not_evaluated", reason="XML only: the pdfa and facturx_pdf checks were skipped"),
            "facturx_profile": layer("not_evaluated", reason="the response reports facturxProfile as blocked by the EN16931 failure; the XSD check passed but the profile is not judged separately here"),
            "en16931": layer("confirmed", expectation={"verdict": "fail", "ids": ["BR-CO-16"]}, observed=observed("fail", "FacturX API staging /api/scan target en16931 (Factur-X 1.09.2 CII Schematron pack); cross-checked offline with the official CEN CII Schematron 1.3.16: BR-CO-16 alone, level fatal", ["en16931_response", "oracle"], ids=["BR-CO-16"])),
            "fr_ctc": layer("not_evaluated", reason="target france_2026 was blocked: fr_ctc_blocked_by_base_profile_failure, missing input totals.due"),
            "pa_acceptance": layer("not_evaluated", reason="the responses report paAcceptance as not_submitted: nothing was sent to a PA"),
        },
        "runs": [dict(run_base, request="POST /api/scan with the XML and validation_target=en16931, then france_2026 (public scanner, no key)", receipts=["capture", "en16931_response", "france_response", "oracle", "api_meta", "manifest"])],
        "limits": [
            "Staging at the build above, on the date above: not production, and it can change if the rules or the service change.",
            "BR-CO-16: amount due for payment (BT-115) = invoice total with VAT (BT-112) - paid amount (BT-113) + rounding amount (BT-114); here 1200.00 - 0 + 0 is not 1100.00.",
            "The France 2026 rules were not run on this file, because the base profile failed first.",
        ],
        "notes": "Built from the valid sample by two changes: the invoice number gets the suffix -BRCO16 and BT-115 becomes 1100.00 instead of 1200.00.",
    }
    write(args.out, invalid)
    print("seed_product_runs: 3 case(s)")


if __name__ == "__main__":
    main()
