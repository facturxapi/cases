#!/usr/bin/env python3
"""check_cases.py — structural and honesty checks of the case corpus, and its generated index.

    python3 scripts/check_cases.py [--root DIR] [--write] [--verify-remote]

Default: read-only. Every cases/*/case.json is checked against the rules of CASE-FORMAT.md; index.json must equal what the cases generate (--write regenerates it).
--verify-remote downloads each evidence source (https only, 20 s timeout, 12 MB cap) and compares its SHA-256: the only network step, never part of the offline check.
Standard library only. Exit 0 = every case and the index are sound, 1 = at least one finding (printed one per line), 2 = usage.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

LAYERS = ("packaging", "facturx_profile", "en16931", "fr_ctc", "pa_acceptance")
STATES = ("confirmed", "mismatch", "not_run", "not_evaluated")
KINDS = ("oracle", "product-run")
CLASSES = ("valid", "error")
FORMATS = ("CII", "UBL", "PDF", "JSON")
VERDICTS = ("pass", "fail")
RUN_KINDS = ("oracle-replay", "api-call")
ID_RE = re.compile(r"^(PR|EO)-[A-Za-z0-9][A-Za-z0-9_.-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")
# Claims a technical check can never carry (product truth): a case states what was observed, never an acceptance or a guarantee.
FORBIDDEN = ("certified", "certifié", "certifiée", "garantit", "guarantees", "guaranteed", "accepted by the pa", "accepted by a pa", "accepté par la pa", "pa-approved", "100% compliant", "100 % conforme", "fully compliant")
MAX_REMOTE_BYTES = 12_000_000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def evidence_url(source):
    """The https URL a source can be fetched from, or None."""
    if source.get("type") == "url":
        return source.get("url")
    if source.get("type") == "git":
        return "https://raw.githubusercontent.com/%s/%s/%s" % (source["repo"], source["commit"], source["path"])
    return None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def derived_state(layer):
    """The state a layer's expectation / observation imply (None when they are inconsistent with a plain reading)."""
    expectation, observed = layer.get("expectation"), layer.get("observed")
    if expectation is None and observed is None:
        return "not_evaluated"
    if expectation is not None and observed is None:
        return "not_run"
    if expectation is None and observed is not None:
        return None
    same_verdict = expectation.get("verdict") == observed.get("verdict")
    same_ids = sorted(expectation.get("ids", [])) == sorted(observed.get("ids", []))
    return "confirmed" if same_verdict and same_ids else "mismatch"


def check_source(source, where, out):
    if not isinstance(source, dict):
        out.append("%s: source must be an object" % where)
        return
    if source.get("type") == "git":
        if not isinstance(source.get("repo"), str) or not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", source.get("repo", "")):
            out.append("%s: git source needs repo owner/name" % where)
        if not SHA1_RE.match(str(source.get("commit", ""))):
            out.append("%s: git source must pin a 40-hex commit (a branch name moves)" % where)
        if not isinstance(source.get("path"), str) or not source.get("path") or source["path"].startswith("/") or ".." in source["path"].split("/"):
            out.append("%s: git source needs a relative path" % where)
    elif source.get("type") == "url":
        if not str(source.get("url", "")).startswith("https://"):
            out.append("%s: url source must be https" % where)
    else:
        out.append("%s: source type must be git or url" % where)


def check_case(path, case, out):
    name = os.path.basename(os.path.dirname(path))
    tag = "[%s]" % name
    for key in ("schema_version", "id", "title", "kind", "class", "synthetic", "rights", "inputs", "evidence", "layers", "runs", "limits"):
        if key not in case:
            out.append("%s missing key %s" % (tag, key))
    if out and any(line.startswith(tag + " missing key") for line in out):
        return
    if case["schema_version"] != 1:
        out.append("%s schema_version must be 1" % tag)
    if not ID_RE.match(str(case["id"])) or case["id"] != name:
        out.append("%s id must match the folder name and ^(PR|EO)-…$" % tag)
    if not str(case["title"]).strip():
        out.append("%s title is empty" % tag)
    if case["kind"] not in KINDS:
        out.append("%s kind must be one of %s" % (tag, KINDS))
    if case["class"] not in CLASSES:
        out.append("%s class must be one of %s" % (tag, CLASSES))
    if case["synthetic"] is not True:
        out.append("%s synthetic must be true (the public corpus holds no real invoice)" % tag)
    if not str(case["rights"]).strip():
        out.append("%s rights is empty" % tag)
    for text in _strings(case):
        low = text.lower()
        for phrase in FORBIDDEN:
            if phrase in low:
                out.append("%s forbidden claim wording «%s» (a case states what was observed)" % (tag, phrase))
    # inputs
    if not isinstance(case["inputs"], list) or not case["inputs"]:
        out.append("%s needs at least one input" % tag)
    for i, item in enumerate(case["inputs"] if isinstance(case["inputs"], list) else []):
        where = "%s inputs[%d]" % (tag, i)
        if not str(item.get("role", "")).strip():
            out.append("%s role is empty" % where)
        if item.get("format") not in FORMATS:
            out.append("%s format must be one of %s" % (where, FORMATS))
        if not SHA_RE.match(str(item.get("sha256", ""))):
            out.append("%s sha256 must be 64 lowercase hex" % where)
        if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            out.append("%s bytes must be a non-negative integer" % where)
        check_source(item.get("source"), where, out)
    # evidence
    evidence = case["evidence"]
    if not isinstance(evidence, dict):
        out.append("%s evidence must be an object" % tag)
        evidence = {}
    for key, item in evidence.items():
        where = "%s evidence.%s" % (tag, key)
        if not SHA_RE.match(str(item.get("sha256", ""))):
            out.append("%s sha256 must be 64 lowercase hex" % where)
        if not str(item.get("what", "")).strip():
            out.append("%s says nothing about what it is (what)" % where)
        check_source(item.get("source"), where, out)
    # layers
    layers = case["layers"]
    if not isinstance(layers, dict) or tuple(layers.keys()) != LAYERS:
        out.append("%s layers must be exactly %s, in this order" % (tag, list(LAYERS)))
        layers = {}
    verdicts = []
    for key in LAYERS:
        layer = layers.get(key)
        if layer is None:
            continue
        where = "%s layers.%s" % (tag, key)
        if layer.get("state") not in STATES:
            out.append("%s state must be one of %s" % (where, STATES))
        expected_state = derived_state(layer)
        if expected_state is None:
            out.append("%s has an observation but no expectation (say what was expected)" % where)
        elif layer.get("state") != expected_state:
            out.append("%s state is %s but its expectation and observation say %s" % (where, layer.get("state"), expected_state))
        for part in ("expectation", "observed"):
            data = layer.get(part)
            if data is None:
                continue
            if data.get("verdict") not in VERDICTS:
                out.append("%s %s.verdict must be pass or fail" % (where, part))
            if "ids" in data and (not isinstance(data["ids"], list) or any(not isinstance(x, str) or not x for x in data["ids"])):
                out.append("%s %s.ids must be a list of rule ids" % (where, part))
            if data.get("verdict") == "pass" and data.get("ids"):
                out.append("%s %s: a pass cannot carry failing rule ids" % (where, part))
            if part == "expectation":
                verdicts.append(data.get("verdict"))
        if layer.get("observed") is not None:
            refs = layer["observed"].get("evidence")
            if not isinstance(refs, list) or not refs:
                out.append("%s observed needs evidence (a result without a receipt is a claim)" % where)
            else:
                for ref in refs:
                    if ref not in evidence:
                        out.append("%s observed cites evidence %s which is not in evidence{}" % (where, ref))
            if not str(layer["observed"].get("engine", "")).strip():
                out.append("%s observed.engine is empty (which tool produced it)" % where)
        if layer.get("state") == "not_evaluated" and not str(layer.get("reason", "")).strip():
            out.append("%s is not_evaluated: say why (reason)" % where)
        if layer.get("state") == "not_run" and not str(layer.get("reason", "")).strip():
            out.append("%s is not_run: say why (reason)" % where)
    pa = layers.get("pa_acceptance")
    if pa is not None and pa.get("state") != "not_evaluated":
        out.append("%s layers.pa_acceptance must stay not_evaluated: a technical check never proves PA acceptance" % tag)
    if case.get("class") == "valid" and "fail" in verdicts:
        out.append("%s class valid but a layer expects fail" % tag)
    if case.get("class") == "error" and "fail" not in verdicts:
        out.append("%s class error but no layer expects fail" % tag)
    # runs
    runs = case["runs"]
    if not isinstance(runs, list):
        out.append("%s runs must be a list" % tag)
        runs = []
    for i, run in enumerate(runs):
        where = "%s runs[%d]" % (tag, i)
        if run.get("kind") not in RUN_KINDS:
            out.append("%s kind must be one of %s" % (where, RUN_KINDS))
        if run.get("kind") == "api-call":
            if not ISO_RE.match(str(run.get("when", ""))):
                out.append("%s api-call needs when (ISO UTC)" % where)
            if run.get("target") not in ("staging", "production"):
                out.append("%s api-call target must be staging or production" % where)
            if not SHA1_RE.match(str((run.get("api_build") or {}).get("commit_sha", ""))):
                out.append("%s api-call needs api_build.commit_sha (40 hex): a result belongs to a revision" % where)
        if run.get("kind") == "oracle-replay" and not str(run.get("engine", "")).strip():
            out.append("%s oracle-replay needs engine" % where)
        for ref in run.get("receipts", []):
            if ref not in evidence:
                out.append("%s cites receipt %s which is not in evidence{}" % (where, ref))
    observed_any = any((layers.get(k) or {}).get("observed") is not None for k in LAYERS)
    if observed_any and not runs:
        out.append("%s has an observation but no run" % tag)
    if case.get("kind") == "product-run" and not any(r.get("kind") == "api-call" for r in runs):
        out.append("%s kind product-run needs an api-call run" % tag)
    # limits
    if not isinstance(case["limits"], list) or not case["limits"] or any(not str(x).strip() for x in case["limits"]):
        out.append("%s limits must list at least one limit (what this case does NOT show)" % tag)


def load_cases(root):
    cases_dir = os.path.join(root, "cases")
    found = []
    if os.path.isdir(cases_dir):
        for name in sorted(os.listdir(cases_dir)):
            path = os.path.join(cases_dir, name, "case.json")
            if os.path.isfile(path):
                found.append(path)
    return found


def build_index(root, cases):
    rows = []
    for path, case in cases:
        rows.append({
            "id": case["id"], "title": case["title"], "kind": case["kind"], "class": case["class"],
            "path": "cases/%s/case.json" % case["id"],
            "layers": {key: case["layers"][key]["state"] for key in LAYERS},
            "inputs": [{"role": i["role"], "format": i["format"]} for i in case["inputs"]],
            "runs": len(case["runs"]),
        })
    rows.sort(key=lambda row: row["id"])
    return {"schema_version": 1, "generated_by": "scripts/check_cases.py", "case_count": len(rows), "cases": rows}


def verify_remote(cases, out, fetch=None):
    def default_fetch(url):
        request = urllib.request.Request(url, headers={"User-Agent": "facturx-cases-check/1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(MAX_REMOTE_BYTES + 1)
        if len(data) > MAX_REMOTE_BYTES:
            raise ValueError("larger than %d bytes" % MAX_REMOTE_BYTES)
        return data
    get = fetch or default_fetch
    for path, case in cases:
        items = [("inputs[%d]" % i, x) for i, x in enumerate(case["inputs"])] + [("evidence.%s" % k, v) for k, v in case["evidence"].items()]
        for label, item in items:
            url = evidence_url(item["source"])
            if not url or not url.startswith("https://"):
                out.append("[%s] %s: no https source to verify" % (case["id"], label))
                continue
            try:
                got = hashlib.sha256(get(url)).hexdigest()
            except Exception as error:
                out.append("[%s] %s: cannot fetch (%s)" % (case["id"], label, str(error)[:80]))
                continue
            if got != item["sha256"]:
                out.append("[%s] %s: sha256 differs from the published file (%s…)" % (case["id"], label, got[:12]))


def main(argv=None, fetch=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--write", action="store_true", help="regenerate index.json")
    parser.add_argument("--verify-remote", action="store_true", help="fetch every source and compare its sha256 (network)")
    args = parser.parse_args(argv)
    findings, cases = [], []
    paths = load_cases(args.root)
    if not paths:
        findings.append("no case found under %s/cases" % args.root)
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                case = json.load(f)
        except (OSError, ValueError) as error:
            findings.append("[%s] unreadable case.json: %s" % (os.path.basename(os.path.dirname(path)), error))
            continue
        before = len(findings)
        check_case(path, case, findings)
        if len(findings) == before:
            cases.append((path, case))
    if not findings:
        index = build_index(args.root, cases)
        text = json.dumps(index, indent=1, ensure_ascii=False) + "\n"
        index_path = os.path.join(args.root, "index.json")
        if args.write:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            try:
                with open(index_path, encoding="utf-8") as f:
                    current = f.read()
            except OSError:
                current = None
            if current != text:
                findings.append("index.json is %s: run scripts/check_cases.py --write" % ("missing" if current is None else "out of date"))
        if args.verify_remote:
            verify_remote(cases, findings, fetch)
    for line in findings:
        print("FINDING " + line)
    print("check_cases: %d case(s), %d finding(s)" % (len(paths), len(findings)))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
