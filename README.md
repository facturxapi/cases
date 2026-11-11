# FacturX cases

A corpus of small, dated, replayable cases for French e-invoicing checks (EN 16931, Factur-X, the French CTC rules): for each one, what was expected,
what was observed, by which tool, on which revision, and the receipts to check it again.

It starts from two public repositories of the organisation and does not copy them:

- [en16931-oracles](https://github.com/facturxapi/en16931-oracles): the ConnectingEurope 1.3.17 examples, their SVRL receipts and mutants;
- [validate-einvoice](https://github.com/facturxapi/validate-einvoice): the GitHub Action that runs the same official artefacts.

And from the two dated captures already published on facturxapi.com/demo (a JSON ERP document converted on staging, and the two `/scan` test files).

## What is in it today

| Family | Count | What it is |
|---|---|---|
| `EO-OK-*` | 10 | the official examples, expected to pass the EN 16931 Schematron (oracle only) |
| `EO-ERR-*` | 10 | the same examples with one semantic change each, expected to fail on named rules (oracle only) |
| `PR-*` | 3 | dated FacturX API runs on staging: convert (valid), scan of the valid sample, scan of an XML with a BR-CO-16 error |

`index.json` lists them. The format and its honesty rules are in [CASE-FORMAT.md](CASE-FORMAT.md); what is planned is in [ROADMAP.md](ROADMAP.md).

## Check it

```bash
python3 scripts/check_cases.py                  # offline: structure, honesty rules, index up to date
python3 scripts/check_cases.py --verify-remote  # fetches every referenced file and compares its SHA-256
python3 -m unittest discover -s tests           # tests of the checker
```

Python 3 standard library only.

## What it does not claim

A case says what one tool observed on one file, on one date and revision. It does not say a product is compliant, that a document will be accepted by a Plateforme
Agréée (that layer is always "not evaluated"), or that production behaves like staging. The PR cases are staging captures; no case here is a production result.

## Licence

The case descriptions, scripts and tests of this repository: MIT (see LICENSE). The official ConnectingEurope examples, XSLT and reports stay under EUPL 1.2 in
`en16931-oracles` (referenced, not copied; see its NOTICE and LICENSE-NOTES.md). The synthetic data of the PR cases is MIT, as stated in their capture manifests.
Every GitHub Action of `.github/workflows` is pinned by commit.
