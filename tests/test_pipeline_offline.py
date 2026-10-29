"""The whole night, offline: fixture source + stub agents -> published JSON -> site."""

import json
import os
import unittest
from datetime import date

from pipeline import paths
from pipeline.run import load_state, nightly
from tests.helpers import DOC_ID, STUB, TempDataTest


class NightlyOfflineTests(TempDataTest):
    def run_night(self):
        return nightly("kansascity", days=10, max_docs=4, loop_cap=4.0, fixture=True,
                       stub_dir=STUB, today=date(2026, 10, 29))

    def test_one_night_publishes_only_accepted_claims(self):
        self.assertEqual(self.run_night(), 0.0)
        with open(os.path.join(paths.PUBLISHED, f"{DOC_ID}.json"), encoding="utf-8") as f:
            pub = json.load(f)
        self.assertEqual([c["id"] for c in pub["claims"]], ["c1", "c2", "c3"])
        self.assertTrue(all(s["claim_ids"] for s in pub["sentences"]))

    def test_rejected_facts_never_reach_the_site(self):
        self.run_night()
        with open(os.path.join(paths.SITE, "doc", f"{DOC_ID}.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("1,100,000.00", page)
        self.assertNotIn("2,100,000", page)          # c4's wrong amount
        self.assertNotIn("property tax", page)       # c5's invented claim
        self.assertNotIn("unanimously", page)        # c7
        self.assertIn("Official record", page)

    def test_state_metrics_and_second_night_is_a_no_op(self):
        self.run_night()
        state = load_state()["docs"]
        self.assertEqual(state[DOC_ID]["status"], "ok")
        # The fixture has no agenda text, so the agenda fails ingest and is retried next night.
        self.assertEqual(state["kc-19561-agenda"]["status"], "error")
        self.run_night()
        with open(paths.METRICS, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
        self.assertEqual([x["doc_id"] for x in lines], [DOC_ID])   # minutes processed once
        self.assertEqual(load_state()["docs"]["kc-19561-agenda"]["tries"], 2)

    def test_index_page_shows_the_metric(self):
        self.run_night()
        with open(os.path.join(paths.SITE, "index.html"), encoding="utf-8") as f:
            idx = f.read()
        self.assertIn("3 of 7 extracted facts passed", idx)


if __name__ == "__main__":
    unittest.main()
