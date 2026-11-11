#!/usr/bin/env python3
"""seed_from_oracles.py — derive the EO-* cases from a checkout of facturxapi/en16931-oracles at ONE pinned commit.

    python3 scripts/seed_from_oracles.py --oracles /path/to/en16931-oracles [--out corpus-root]

For each official example (oracles/receipts) and each one-line mutant (mutants/receipts) it writes cases/EO-OK-<stem>/case.json or cases/EO-ERR-<stem>/case.json.
Nothing is copied from the oracles repo (the fixtures are EUPL 1.2 there): a case POINTS at it by repository, commit, path and SHA-256.
The failing rule ids are read from the SVRL receipt itself, then compared with the mutants table of MUTANTS.md: a disagreement stops the run.
Deterministic: the same commit always writes the same bytes. Standard library only.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO = "facturxapi/en16931-oracles"
ENGINE_NOTE = "SaxonC-HE 13.0 with the vendored ConnectingEurope validation-1.3.17 XSLT, as recorded in the repository's RESULTS.json"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def failed_ids(svrl_path):
    root = ET.parse(svrl_path).getroot()
    return [el.get("id") for el in root.iter("{http://purl.oclc.org/dsdl/svrl}failed-assert")]


def mutants_table(text):
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 7 and cells[0].startswith("`mutants/"):
            stem = os.path.basename(cells[0].strip("`"))[:-4]
            ids = re.findall(r"`([^`]+)`", cells[5])
            rows[stem] = {"class": cells[2], "change": cells[3].replace("`", ""), "ids": ids}
    return rows


def source(commit, path):
    return {"type": "git", "repo": REPO, "commit": commit, "path": path}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--oracles", required=True)
    parser.add_argument("--out", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = parser.parse_args()
    root = os.path.abspath(args.oracles)
    commit = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", root, "status", "--porcelain"], text=True).strip():
        sys.exit("refused: the oracles checkout has local changes — the cases would not describe the pinned commit")
    with open(os.path.join(root, "MUTANTS.md"), encoding="utf-8") as f:
        table = mutants_table(f.read())
    written = []
    for family, folder, results_path, prefix in (("valid", "fixtures", "oracles/receipts/RESULTS.json", "EO-OK-"), ("error", "mutants", "mutants/RESULTS.json", "EO-ERR-")):
        with open(os.path.join(root, results_path), encoding="utf-8") as f:
            results = json.load(f)
        receipts_dir = "oracles/receipts" if family == "valid" else "mutants/receipts"
        for entry in sorted(results, key=lambda e: e["file"]):
            stem = entry["file"][:-4]
            xml_rel = "%s/%s" % (folder, entry["file"])
            with open(os.path.join(root, xml_rel), "rb") as f:
                xml_bytes = f.read()
            if sha256_bytes(xml_bytes) != entry["sha256"]:
                sys.exit("refused: %s does not match the sha256 recorded in %s" % (xml_rel, results_path))
            svrl_rel = "%s/%s.svrl.xml" % (receipts_dir, stem)
            with open(os.path.join(root, svrl_rel), "rb") as f:
                svrl_bytes = f.read()
            ids = failed_ids(os.path.join(root, svrl_rel))
            if len(ids) != entry["failed_assert"]:
                sys.exit("refused: %s lists %d failed-assert but RESULTS.json says %d" % (svrl_rel, len(ids), entry["failed_assert"]))
            note = None
            if family == "error":
                row = table.get(stem)
                if not row or sorted(row["ids"]) != sorted(ids):
                    sys.exit("refused: the MUTANTS.md table and the SVRL receipt disagree for %s (%s vs %s)" % (stem, row and row["ids"], ids))
                note = "One semantic change to the official example. Class: %s. Change: %s." % (row["class"], row["change"])
            case_id = prefix + stem
            fmt = entry["syntax"]
            verdict = "fail" if family == "error" else "pass"
            title = ("Official EN16931 example %s (%s), expected to pass the EN16931 Schematron" if family == "valid" else "Official EN16931 example %s (%s) with one change, expected to fail the EN16931 Schematron") % (stem, fmt)
            evidence = {"svrl": {"what": "SVRL report of the EN16931 %s Schematron run on this file" % fmt, "source": source(commit, svrl_rel), "sha256": sha256_bytes(svrl_bytes)}}
            case = {
                "schema_version": 1, "id": case_id, "title": title, "kind": "oracle", "class": family,
                "synthetic": True,
                "rights": "Official ConnectingEurope example, EUPL 1.2, referenced and not copied; see NOTICE and LICENSE-NOTES.md of %s" % REPO,
                "inputs": [{"role": "invoice", "format": fmt, "source": source(commit, xml_rel), "sha256": entry["sha256"], "bytes": len(xml_bytes)}],
                "evidence": evidence,
                "layers": {
                    "packaging": {"expectation": None, "observed": None, "state": "not_evaluated", "reason": "XML only: no PDF to check for PDF/A-3 or an embedded Factur-X part"},
                    "facturx_profile": {"expectation": None, "observed": None, "state": "not_evaluated", "reason": "this case runs the EN16931 Schematron only, not a Factur-X profile check"},
                    "en16931": {"expectation": {"verdict": verdict, "ids": ids}, "observed": {"verdict": verdict, "ids": ids, "engine": ENGINE_NOTE, "evidence": ["svrl"]}, "state": "confirmed"},
                    "fr_ctc": {"expectation": None, "observed": None, "state": "not_evaluated", "reason": "the BR-FR rules are outside this oracle run"},
                    "pa_acceptance": {"expectation": None, "observed": None, "state": "not_evaluated", "reason": "a technical check never proves acceptance by a PA"},
                },
                "runs": [{"kind": "oracle-replay", "engine": ENGINE_NOTE, "source": source(commit, results_path), "receipts": ["svrl"],
                          "replay": "python3 scripts/validate.py%s in a checkout of %s at %s" % (" --dir mutants --no-expected" if family == "error" else "", REPO, commit[:12])}],
                "limits": [
                    "Official ConnectingEurope Schematron on one file: it says nothing about a FacturX product, an API, a PDF or the France CTC rules.",
                    "The result belongs to the pinned engine and rule set; another version can differ.",
                ],
            }
            if note:
                case["notes"] = note
            out_dir = os.path.join(args.out, "cases", case_id)
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "case.json"), "w", encoding="utf-8") as f:
                f.write(json.dumps(case, indent=1, ensure_ascii=False) + "\n")
            written.append(case_id)
    print("seed_from_oracles: %d case(s) from %s@%s" % (len(written), REPO, commit[:12]))


if __name__ == "__main__":
    main()
