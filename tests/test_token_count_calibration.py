from __future__ import annotations

import json

from cc_dump.experiments.token_count_calibration import (
    build_comparison_rows,
    build_report,
    load_count_map,
)


def _har_entry(*, request_body: dict, response_body: dict, started: str, comment: str = "") -> dict:
    entry: dict = {
        "startedDateTime": started,
        "request": {"postData": {"text": json.dumps(request_body)}},
        "response": {"content": {"text": json.dumps(response_body)}},
    }
    if comment:
        entry["comment"] = comment
    return entry


def _write_har(tmp_path, name: str, entries: list[dict]) -> str:
    payload = {"log": {"entries": entries}}
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_build_comparison_rows_emits_request_identifiers_and_deltas(tmp_path):
    har_path = _write_har(
        tmp_path,
        "sample.har",
        [
            _har_entry(
                started="2026-02-24T00:00:00Z",
                request_body={
                    "model": "claude-sonnet-4-5",
                    "messages": [{"role": "user", "content": "short prompt"}],
                },
                response_body={
                    "id": "msg_alpha",
                    "usage": {
                        "input_tokens": 100,
                        "cache_read_input_tokens": 20,
                        "cache_creation_input_tokens": 0,
                    },
                },
            ),
            _har_entry(
                started="2026-02-24T00:01:00Z",
                request_body={
                    "model": "claude-sonnet-4-5",
                    "messages": [
                        {"role": "user", "content": "run tests"},
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_1",
                                    "name": "Bash",
                                    "input": {"command": "uv run pytest tests/test_sample.py -q"},
                                },
                                {"type": "text", "text": "done"},
                            ],
                        },
                    ],
                },
                response_body={
                    "id": "msg_beta",
                    "usage": {
                        "input_tokens": 210,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 12,
                    },
                },
            ),
        ],
    )

    rows = build_comparison_rows(har_files=[har_path])
    assert len(rows) == 2
    assert rows[0].request_key == "msg_alpha"
    assert rows[1].request_key == "msg_beta"
    assert rows[0].provider_total_input_tokens == 120
    assert rows[1].provider_total_input_tokens == 222
    assert rows[0].tiktoken_delta_tokens == rows[0].tiktoken_input_tokens - 120
    assert rows[1].tiktoken_delta_tokens == rows[1].tiktoken_input_tokens - 222
    assert rows[1].tool_use_count >= 1


def test_count_map_supports_request_key_and_file_index_fallback(tmp_path):
    har_path = _write_har(
        tmp_path,
        "map.har",
        [
            _har_entry(
                started="2026-02-24T00:00:00Z",
                request_body={
                    "model": "claude-haiku-3",
                    "messages": [{"role": "user", "content": "A"}],
                },
                response_body={
                    "id": "msg_map_1",
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            ),
            _har_entry(
                started="2026-02-24T00:00:01Z",
                request_body={
                    "model": "claude-haiku-3",
                    "messages": [{"role": "user", "content": "B"}],
                },
                response_body={
                    "usage": {
                        "input_tokens": 11,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            ),
        ],
    )
    count_map_path = tmp_path / "count_map.json"
    count_map_path.write_text(
        json.dumps(
            {
                "msg_map_1": 9,
                "map.har:1": 13,
            }
        ),
        encoding="utf-8",
    )

    count_map = load_count_map(str(count_map_path))
    rows = build_comparison_rows(har_files=[har_path], count_map=count_map)
    assert len(rows) == 2
    assert rows[0].count_tokens_input_tokens == 9
    assert rows[1].count_tokens_input_tokens == 13


def test_build_report_includes_summary_stratification_and_algorithm(tmp_path):
    har_path = _write_har(
        tmp_path,
        "report.har",
        [
            _har_entry(
                started="2026-02-24T00:00:00Z",
                request_body={
                    "model": "claude-sonnet-4-5",
                    "messages": [{"role": "user", "content": "x" * 3000}],
                },
                response_body={
                    "id": "msg_r1",
                    "usage": {
                        "input_tokens": 500,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            ),
            _har_entry(
                started="2026-02-24T00:00:30Z",
                request_body={
                    "model": "claude-sonnet-4-5",
                    "messages": [
                        {"role": "user", "content": "foo"},
                        {"role": "assistant", "content": [{"type": "text", "text": "bar"}]},
                    ],
                },
                response_body={
                    "id": "msg_r2",
                    "usage": {
                        "input_tokens": 30,
                        "cache_read_input_tokens": 10,
                        "cache_creation_input_tokens": 0,
                    },
                },
            ),
        ],
    )
    rows = build_comparison_rows(
        har_files=[har_path],
        count_map={
            "msg_r1": 490,
            "msg_r2": 42,
        },
    )
    report = build_report(rows)

    assert report["request_count"] == 2
    assert len(report["rows"]) == 2
    assert "summary" in report
    assert "tiktoken_vs_provider" in report["summary"]
    assert "count_tokens_vs_provider" in report["summary"]
    assert report["summary"]["tiktoken_vs_provider"]["request_count"] == 2.0
    assert report["summary"]["count_tokens_vs_provider"]["request_count"] == 2.0
    assert report["summary"]["stratified_by_bucket"]
    assert "proposed_algorithm" in report
    assert "bucket_bias_tokens" in report["proposed_algorithm"]
    assert "fallback_estimator_formula" in report["proposed_algorithm"]
