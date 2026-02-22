from pathlib import Path

from cc_dump.side_channel_eval import main, run_evaluation
from cc_dump.side_channel_eval_metrics import PURPOSE_MIN_PASS_RATE


def test_run_evaluation_produces_all_purpose_rows():
    corpus = Path("docs/side-channel/eval/side_channel_eval_corpus.json")
    report = run_evaluation(corpus)

    assert report["report_version"] == 1
    assert len(report["corpus_sha256"]) == 64
    assert report["summary"]["checks_total"] >= len(PURPOSE_MIN_PASS_RATE)
    purposes = report["purposes"]
    for purpose in PURPOSE_MIN_PASS_RATE:
        assert purpose in purposes
        assert purposes[purpose]["status"] == "pass"


def test_run_evaluation_is_stable_for_fixed_corpus():
    corpus = Path("docs/side-channel/eval/side_channel_eval_corpus.json")
    first = run_evaluation(corpus)
    second = run_evaluation(corpus)
    assert first == second


def test_main_check_writes_report_and_passes(tmp_path):
    output = tmp_path / "side_channel_eval.json"
    rc = main(
        [
            "--corpus",
            "docs/side-channel/eval/side_channel_eval_corpus.json",
            "--output",
            str(output),
            "--check",
        ]
    )
    assert rc == 0
    assert output.exists()
