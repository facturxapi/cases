import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import check_cases  # noqa: E402

SAMPLES = ("EO-ERR-CII_example1", "PR-0003-scan-invalid-br-co-16", "PR-0002-scan-valid-sample-facturx")


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def run_main(root, *extra, fetch=None):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = check_cases.main(["--root", root] + list(extra), fetch=fetch)
    return code, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "corpus")
        os.makedirs(os.path.join(self.root, "cases"))
        for name in SAMPLES:
            shutil.copytree(os.path.join(HERE, "cases", name), os.path.join(self.root, "cases", name))
        code, _ = run_main(self.root, "--write")
        assert code == 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, name):
        with open(os.path.join(self.root, "cases", name, "case.json"), encoding="utf-8") as f:
            return json.load(f)

    def save(self, name, case):
        with open(os.path.join(self.root, "cases", name, "case.json"), "w", encoding="utf-8") as f:
            json.dump(case, f, indent=1, ensure_ascii=False)

    def mutate(self, name, fn):
        # every call starts from the pristine samples, so one mutation never leaks into the next assertion
        for sample in SAMPLES:
            shutil.copyfile(os.path.join(HERE, "cases", sample, "case.json"), os.path.join(self.root, "cases", sample, "case.json"))
        case = self.load(name)
        fn(case)
        self.save(name, case)
        return run_main(self.root)

    def assertFinding(self, result, fragment):
        code, out = result
        self.assertEqual(code, 1, out)
        self.assertIn(fragment, out)


class TestSound(Base):
    def test_the_real_corpus_is_sound(self):
        code, out = run_main(HERE)
        self.assertEqual(code, 0, out)
        self.assertIn("23 case(s), 0 finding(s)", out)

    def test_sample_corpus_is_sound(self):
        code, out = run_main(self.root)
        self.assertEqual((code, "0 finding(s)" in out), (0, True), out)

    def test_index_is_deterministic_and_sorted(self):
        with open(os.path.join(self.root, "index.json"), encoding="utf-8") as f:
            first = f.read()
        run_main(self.root, "--write")
        with open(os.path.join(self.root, "index.json"), encoding="utf-8") as f:
            self.assertEqual(first, f.read())
        ids = [row["id"] for row in json.loads(first)["cases"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(json.loads(first)["case_count"], 3)

    def test_index_missing_and_stale(self):
        os.remove(os.path.join(self.root, "index.json"))
        self.assertFinding(run_main(self.root), "index.json is missing")
        run_main(self.root, "--write")
        with open(os.path.join(self.root, "index.json"), "a", encoding="utf-8") as f:
            f.write(" ")
        self.assertFinding(run_main(self.root), "index.json is out of date")

    def test_no_case(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(os.path.join(empty, "cases"))
        self.assertFinding(run_main(empty), "no case found")

    def test_unreadable_json(self):
        with open(os.path.join(self.root, "cases", SAMPLES[0], "case.json"), "w") as f:
            f.write("{not json")
        self.assertFinding(run_main(self.root), "unreadable case.json")


class TestRules(Base):
    EO, PR_ERR, PR_OK = SAMPLES

    def test_missing_key(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c.pop("limits")), "missing key limits")

    def test_identity(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c.update(id="EO-ERR-other")), "id must match the folder name")
        self.assertFinding(self.mutate(self.EO, lambda c: c.update(schema_version=2)), "schema_version must be 1")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c.update(kind="manual")), "kind must be one of")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c.update({"class": "maybe"})), "class must be one of")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c.update(title="  ")), "title is empty")

    def test_synthetic_and_rights(self):
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c.update(synthetic=False)), "synthetic must be true")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c.update(rights="")), "rights is empty")

    def test_forbidden_wording(self):
        for phrase in ("This result is certified.", "Le service garantit la conformité.", "accepted by the PA", "100 % conforme"):
            self.assertFinding(self.mutate(self.PR_OK, lambda c, p=phrase: c["limits"].append(p)), "forbidden claim wording")

    def test_inputs(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c.update(inputs=[])), "at least one input")
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0].update(sha256="abc")), "sha256 must be 64 lowercase hex")
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0].update(bytes=-1)), "bytes must be a non-negative integer")
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0].update(format="DOCX")), "format must be one of")
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0].update(role="")), "role is empty")

    def test_sources(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0]["source"].update(commit="main")), "pin a 40-hex commit")
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0]["source"].update(path="../x.xml")), "relative path")
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0]["source"].update(path="/abs.xml")), "relative path")
        self.assertFinding(self.mutate(self.EO, lambda c: c["inputs"][0]["source"].update(repo="notarepo")), "owner/name")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c["inputs"][0].update(source={"type": "url", "url": "http://x.example/a"})), "must be https")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c["inputs"][0].update(source={"type": "ftp"})), "source type must be git or url")

    def test_evidence_entries(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c["evidence"]["svrl"].update(what="")), "says nothing about what it is")
        self.assertFinding(self.mutate(self.EO, lambda c: c["evidence"]["svrl"].update(sha256="zz")), "sha256 must be 64 lowercase hex")

    def test_layers_shape(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c["layers"].pop("fr_ctc")), "layers must be exactly")
        self.assertFinding(self.mutate(self.EO, lambda c: c.update(layers=dict(reversed(list(c["layers"].items()))))), "layers must be exactly")

    def test_state_is_derived(self):
        def lie(c):
            c["layers"]["en16931"]["observed"]["ids"] = ["BR-CO-99"]
        self.assertFinding(self.mutate(self.EO, lie), "state is confirmed but its expectation and observation say mismatch")
        def verdict_lie(c):
            c["layers"]["en16931"]["observed"]["verdict"] = "pass"
            c["layers"]["en16931"]["observed"]["ids"] = []
        self.assertFinding(self.mutate(self.EO, verdict_lie), "say mismatch")
        def declared(c):
            c["layers"]["en16931"]["observed"]["ids"] = ["BR-CO-99"]
            c["layers"]["en16931"]["state"] = "mismatch"
        code, out = self.mutate(self.EO, declared)
        self.assertNotIn("state is", out)
        def not_run_lie(c):
            c["layers"]["en16931"]["observed"] = None
        self.assertFinding(self.mutate(self.EO, not_run_lie), "say not_run")
        def not_run_no_reason(c):
            c["layers"]["en16931"]["observed"] = None
            c["layers"]["en16931"]["state"] = "not_run"
        self.assertFinding(self.mutate(self.EO, not_run_no_reason), "is not_run: say why")

    def test_observation_needs_expectation_evidence_engine(self):
        def no_expectation(c):
            c["layers"]["en16931"]["expectation"] = None
        self.assertFinding(self.mutate(self.EO, no_expectation), "no expectation")
        def no_evidence(c):
            c["layers"]["en16931"]["observed"]["evidence"] = []
        self.assertFinding(self.mutate(self.EO, no_evidence), "a result without a receipt is a claim")
        def unknown_ref(c):
            c["layers"]["en16931"]["observed"]["evidence"] = ["ghost"]
        self.assertFinding(self.mutate(self.EO, unknown_ref), "which is not in evidence{}")
        def no_engine(c):
            c["layers"]["en16931"]["observed"]["engine"] = " "
        self.assertFinding(self.mutate(self.EO, no_engine), "observed.engine is empty")

    def test_not_evaluated_needs_a_reason(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c["layers"]["fr_ctc"].pop("reason")), "is not_evaluated: say why")

    def test_pa_acceptance_stays_not_evaluated(self):
        def pa(c):
            c["layers"]["pa_acceptance"] = {"expectation": {"verdict": "pass"}, "observed": {"verdict": "pass", "engine": "x", "evidence": ["svrl"]}, "state": "confirmed"}
        self.assertFinding(self.mutate(self.EO, pa), "pa_acceptance must stay not_evaluated")

    def test_verdicts_and_class(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c.update({"class": "valid"})), "class valid but a layer expects fail")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c.update({"class": "error"})), "class error but no layer expects fail")
        def pass_with_ids(c):
            c["layers"]["en16931"]["expectation"] = {"verdict": "pass", "ids": ["BR-01"]}
        self.assertFinding(self.mutate(self.PR_OK, pass_with_ids), "a pass cannot carry failing rule ids")
        def bad_verdict(c):
            c["layers"]["en16931"]["expectation"]["verdict"] = "ok"
        self.assertFinding(self.mutate(self.PR_OK, bad_verdict), "verdict must be pass or fail")
        def bad_ids(c):
            c["layers"]["en16931"]["expectation"]["ids"] = [1]
        self.assertFinding(self.mutate(self.EO, bad_ids), "ids must be a list of rule ids")

    def test_runs(self):
        def drop_when(c):
            c["runs"][0].pop("when")
        self.assertFinding(self.mutate(self.PR_OK, drop_when), "needs when (ISO UTC)")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c["runs"][0].update(target="laptop")), "target must be staging or production")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c["runs"][0].update(api_build={})), "api_build.commit_sha")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c["runs"][0].update(api_build={"commit_sha": "abc"})), "api_build.commit_sha")
        self.assertFinding(self.mutate(self.EO, lambda c: c["runs"][0].pop("engine")), "oracle-replay needs engine")
        self.assertFinding(self.mutate(self.EO, lambda c: c["runs"][0].update(kind="manual")), "kind must be one of")
        self.assertFinding(self.mutate(self.EO, lambda c: c["runs"][0].update(receipts=["ghost"])), "cites receipt ghost")
        self.assertFinding(self.mutate(self.EO, lambda c: c.update(runs=[])), "has an observation but no run")
        self.assertFinding(self.mutate(self.PR_OK, lambda c: c["runs"][0].update(kind="oracle-replay", engine="x")), "needs an api-call run")

    def test_limits(self):
        self.assertFinding(self.mutate(self.EO, lambda c: c.update(limits=[])), "at least one limit")
        self.assertFinding(self.mutate(self.EO, lambda c: c.update(limits=["  "])), "at least one limit")


class TestHelpers(unittest.TestCase):
    def test_derived_state(self):
        d = check_cases.derived_state
        self.assertEqual(d({"expectation": None, "observed": None}), "not_evaluated")
        self.assertEqual(d({"expectation": {"verdict": "pass"}, "observed": None}), "not_run")
        self.assertIsNone(d({"expectation": None, "observed": {"verdict": "pass"}}))
        self.assertEqual(d({"expectation": {"verdict": "fail", "ids": ["B", "A"]}, "observed": {"verdict": "fail", "ids": ["A", "B"]}}), "confirmed")
        self.assertEqual(d({"expectation": {"verdict": "fail", "ids": ["A"]}, "observed": {"verdict": "fail", "ids": ["A", "B"]}}), "mismatch")
        self.assertEqual(d({"expectation": {"verdict": "pass"}, "observed": {"verdict": "fail", "ids": []}}), "mismatch")

    def test_build_index_sorts_whatever_order_it_is_given(self):
        def case(i):
            return {"id": i, "title": "t", "kind": "oracle", "class": "valid", "inputs": [{"role": "r", "format": "CII"}], "runs": [], "layers": {k: {"state": "not_evaluated"} for k in check_cases.LAYERS}}
        index = check_cases.build_index("x", [("p", case("EO-OK-b")), ("p", case("EO-OK-a"))])
        self.assertEqual([row["id"] for row in index["cases"]], ["EO-OK-a", "EO-OK-b"])
        self.assertEqual(index["case_count"], 2)

    def test_evidence_url(self):
        u = check_cases.evidence_url
        self.assertEqual(u({"type": "url", "url": "https://a.example/x"}), "https://a.example/x")
        self.assertEqual(u({"type": "git", "repo": "o/r", "commit": "c" * 40, "path": "a/b.xml"}), "https://raw.githubusercontent.com/o/r/%s/a/b.xml" % ("c" * 40))
        self.assertIsNone(u({"type": "other"}))


class TestRemote(Base):
    def fetcher(self, mapping, default=b"x"):
        def fetch(url):
            value = mapping.get(url, default)
            if isinstance(value, Exception):
                raise value
            return value
        return fetch

    def test_every_source_is_checked_and_a_difference_is_reported(self):
        seen = []
        def fetch(url):
            seen.append(url)
            return b"not the published bytes"
        code, out = run_main(self.root, "--verify-remote", fetch=fetch)
        self.assertEqual(code, 1)
        self.assertGreater(out.count("sha256 differs from the published file"), 5)
        self.assertEqual(len(seen), len(set(seen)) + (len(seen) - len(set(seen))))
        self.assertTrue(all(u.startswith("https://") for u in seen))

    def test_matching_bytes_pass(self):
        mapping = {}
        for name in SAMPLES:
            case = self.load(name)
            for item in list(case["inputs"]) + list(case["evidence"].values()):
                mapping[check_cases.evidence_url(item["source"])] = item
        def fetch(url):
            # a fixture whose digest equals the recorded one: the checker only compares digests, so serve bytes that hash to it by patching the case
            return mapping[url]["bytes_for_test"]
        for name in SAMPLES:
            case = self.load(name)
            for item in list(case["inputs"]) + list(case["evidence"].values()):
                data = ("payload:" + check_cases.evidence_url(item["source"])).encode()
                item["sha256"] = hashlib.sha256(data).hexdigest()
                mapping[check_cases.evidence_url(item["source"])] = {"bytes_for_test": data}
            self.save(name, case)
        run_main(self.root, "--write")
        code, out = run_main(self.root, "--verify-remote", fetch=fetch)
        self.assertEqual(code, 0, out)

    def test_fetch_errors_are_findings(self):
        code, out = run_main(self.root, "--verify-remote", fetch=self.fetcher({}, default=OSError("offline")))
        self.assertEqual(code, 1)
        self.assertIn("cannot fetch (offline)", out)

    def test_no_network_without_the_flag(self):
        def boom(url):
            raise AssertionError("fetched without --verify-remote")
        code, out = run_main(self.root, fetch=boom)
        self.assertEqual(code, 0, out)


class TestSeedFromOracles(unittest.TestCase):
    """A tiny synthetic oracles checkout: the seed derives ids from the SVRL, cross-checks the MUTANTS.md table, and refuses a dirty or inconsistent checkout."""
    SVRL_FAIL = '<?xml version="1.0"?><svrl:schematron-output xmlns:svrl="http://purl.oclc.org/dsdl/svrl"><svrl:failed-assert id="BR-CO-15"/><svrl:failed-assert id="BR-CO-16"/></svrl:schematron-output>'
    SVRL_OK = '<?xml version="1.0"?><svrl:schematron-output xmlns:svrl="http://purl.oclc.org/dsdl/svrl"/>'

    def make(self, table_ids="`BR-CO-15`, `BR-CO-16`", dirty=False, wrong_sha=False, mutant_count=2):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = os.path.join(tmp, "oracles")
        for d in ("fixtures", "mutants/receipts", "oracles/receipts"):
            os.makedirs(os.path.join(repo, d))
        files = {"fixtures/A.xml": b"<a>ok</a>", "mutants/A.xml": b"<a>bad</a>", "oracles/receipts/A.svrl.xml": self.SVRL_OK.encode(), "mutants/receipts/A.svrl.xml": self.SVRL_FAIL.encode()}
        for rel, data in files.items():
            with open(os.path.join(repo, rel), "wb") as f:
                f.write(data)
        sha = lambda b: hashlib.sha256(b).hexdigest()
        res = lambda rel, failed, n: [{"engine": "E", "failed_assert": failed, "file": "A.xml", "fired_rule": n, "sha256": ("0" * 64) if wrong_sha else sha(files[rel]), "syntax": "CII", "xslt": "x"}]
        with open(os.path.join(repo, "oracles/receipts/RESULTS.json"), "w") as f:
            json.dump(res("fixtures/A.xml", 0, 5), f)
        with open(os.path.join(repo, "mutants/RESULTS.json"), "w") as f:
            json.dump(res("mutants/A.xml", mutant_count, 5), f)
        with open(os.path.join(repo, "MUTANTS.md"), "w") as f:
            f.write("| Mutant | Fixture | Classe | Diff | fail | ids | SVRL |\n|---|---|---|---|---:|---|---|\n| `mutants/A.xml` | `A.xml` | TOTAL (BT-112) | L1 `x` : `1` → `2` | 2 | %s | `r` |\n" % table_ids)
        for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", repo] + cmd, check=True, capture_output=True)
        if dirty:
            with open(os.path.join(repo, "fixtures/A.xml"), "a") as f:
                f.write("changed")
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        return repo, out

    def seed(self, repo, out):
        return subprocess.run([sys.executable, os.path.join(HERE, "scripts", "seed_from_oracles.py"), "--oracles", repo, "--out", out], capture_output=True, text=True)

    def test_derives_both_families_and_the_result_passes_the_checker(self):
        repo, out = self.make()
        result = self.seed(repo, out)
        self.assertEqual(result.returncode, 0, result.stderr)
        for case_id in ("EO-OK-A", "EO-ERR-A"):
            self.assertTrue(os.path.isfile(os.path.join(out, "cases", case_id, "case.json")))
        err = json.loads(read_bytes(os.path.join(out, "cases", "EO-ERR-A", "case.json")).decode("utf-8"))
        self.assertEqual(err["layers"]["en16931"]["observed"]["ids"], ["BR-CO-15", "BR-CO-16"])
        self.assertEqual(err["layers"]["en16931"]["state"], "confirmed")
        self.assertEqual(err["inputs"][0]["source"]["commit"], subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip())
        code, text = run_main(out, "--write")
        self.assertEqual(code, 0, text)
        first = read_bytes(os.path.join(out, "cases", "EO-ERR-A", "case.json"))
        self.assertEqual(self.seed(repo, out).returncode, 0)
        self.assertEqual(first, read_bytes(os.path.join(out, "cases", "EO-ERR-A", "case.json")), "deterministic")

    def test_refuses_a_table_that_disagrees_with_the_receipt(self):
        repo, out = self.make(table_ids="`BR-CO-15`")
        result = self.seed(repo, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("disagree", result.stderr + result.stdout)

    def test_refuses_a_receipt_whose_assert_count_disagrees_with_results_json(self):
        repo, out = self.make(mutant_count=3)
        result = self.seed(repo, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lists 2 failed-assert but RESULTS.json says 3", result.stderr)

    def test_refuses_a_dirty_checkout(self):
        repo, out = self.make(dirty=True)
        self.assertIn("local changes", self.seed(repo, out).stderr)

    def test_refuses_a_file_that_does_not_match_its_recorded_sha(self):
        repo, out = self.make(wrong_sha=True)
        self.assertIn("does not match the sha256", self.seed(repo, out).stderr)


if __name__ == "__main__":
    unittest.main()
