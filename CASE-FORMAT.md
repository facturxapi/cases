# Case format (schema_version 1)

A **case** is one document (or one input) with what we expected, what was observed, by which tool, on which revision, with the receipts to check it again.
It is a small folder: `cases/<id>/case.json`. Nothing is copied from other repositories: a case **points** at its files by address and SHA-256.

## Rules of honesty (enforced by `scripts/check_cases.py`)

1. **Layers are separate.** `packaging` (PDF/A-3 and the embedded Factur-X part), `facturx_profile`, `en16931`, `fr_ctc`, `pa_acceptance`. A pass on one never implies the next.
2. **Not evaluated is not OK.** A layer a case does not judge says `not_evaluated` and **why**. A layer expected but not yet observed says `not_run`.
3. **A result without a receipt is a claim.** An `observed` block names the tool that produced it (`engine`) and cites at least one `evidence` entry (address + SHA-256).
4. **A result belongs to a revision.** An `api-call` run carries the date (UTC), the target (`staging` or `production`) and the 40-hex API commit it ran against. An `oracle-replay` run names its engine; git sources are pinned to a commit.
5. **The state is derived, not typed.** `confirmed` = expectation and observation agree (same verdict, same rule ids); `mismatch` = they differ; `not_run`; `not_evaluated`. The checker recomputes it and refuses a different one.
6. **`pa_acceptance` is always `not_evaluated`.** A technical check never proves acceptance by a PA (Plateforme Agréée).
7. **Synthetic only.** `synthetic` must be `true` and `rights` says under which licence the data may be reused. No real invoice, no customer data, no credential in any file.
8. **Limits are part of the case.** `limits` lists what the case does NOT show. The checker refuses wording that no technical check can carry (certified, guaranteed, accepted by the PA, 100 % compliant…).

## Fields

| Key | Meaning |
|---|---|
| `id` | `PR-<n>-<slug>` for a product run, `EO-OK-<stem>` / `EO-ERR-<stem>` for an official oracle example and its one-change mutant. Equals the folder name. |
| `kind` | `oracle` (an independent engine only, no FacturX product run) or `product-run` (a dated call of the FacturX API). |
| `class` | `valid` (every expectation is a pass) or `error` (at least one expectation is a fail). |
| `inputs[]` | `role`, `format` (`CII`, `UBL`, `PDF`, `JSON`), `source` (`git` with repo + 40-hex commit + path, or `url` over https), `sha256`, `bytes`. |
| `evidence{}` | Named receipts: `what`, `source`, `sha256`. |
| `layers{}` | The five layers, in this order: `expectation` (`verdict` pass/fail, `ids` = rule ids), `observed` (`verdict`, `ids`, `engine`, `evidence[]`), `state`, `reason` when not evaluated or not run. |
| `runs[]` | `oracle-replay` (`engine`, `source`, `receipts`, `replay` command) or `api-call` (`target`, `when`, `api_build.commit_sha`, `request`, `receipts`). |
| `limits[]` | What this case does not show. At least one. |
| `notes` | Optional. How the input was built. |

`index.json` is generated from the cases (`python3 scripts/check_cases.py --write`) and checked to be up to date; it is what a web page or a tool lists.

## Check a case, or the whole corpus

```bash
python3 scripts/check_cases.py                  # offline: structure, honesty rules, index up to date
python3 scripts/check_cases.py --verify-remote  # downloads every source (https, capped) and compares its SHA-256
```

## Add a case

1. Run the case and keep the receipts (request, response, independent checks, the API build or the engine version).
2. Write `cases/<id>/case.json` with the rules above; point at the receipts by address and SHA-256.
3. `python3 scripts/check_cases.py --write`, then `--verify-remote`.
4. Say in `limits` what the case does not show.

The EO cases are derived by `scripts/seed_from_oracles.py` from a checkout of `facturxapi/en16931-oracles` at one commit; the PR cases by `scripts/seed_product_runs.py` from the published captures. Both are deterministic.
