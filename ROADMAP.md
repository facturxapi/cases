# Roadmap of the corpus

Status of what is planned, written so that nothing here reads as done. Owners and dates are those of the 11/11 pack of the lead; the contents of the lots come from that pack.

| Lot | What | State |
|---|---|---|
| 8.1 | this skeleton: format, checker, 23 cases (20 oracle, 3 staging runs), index | built, not published |
| 4.2, 4.3, 4.4 | scenario runs on staging (S1 S2 S5 S6 S7, S3 France 2026, V1 to V3 of a supplied PDF) | planned, builder-2; each result becomes a `PR-*` case with its receipts; the production runs need the founder's agreement |
| 8.2 | nine executed error cases | planned, builder-2; the `EO-ERR-*` cases are the oracle side of the same rules |
| 8.3 | `verify.sh` and a receipt per case | planned, after the V4 Schematron-per-environment work; `check_cases.py --verify-remote` is the first brick |
| 7.1, 7.2 | `case run` in the CLI, `get_case` in the MCP server | planned after this skeleton; both read `index.json` and `cases/<id>/case.json` |
| 9.2 | "replay this case" / "automate this check" calls to action on the site | planned, after 8.1 and 7.1 |

Open decisions (not taken here): where the corpus is published (a new public repository of the organisation is the proposal; publication is a founder gesture), and the licence of the case descriptions (MIT proposed).
