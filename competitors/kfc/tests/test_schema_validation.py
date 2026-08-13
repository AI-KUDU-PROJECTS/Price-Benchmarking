"""
tests/test_schema_validation.py
Covers required test #16: API schema validation, plus the promotion of a
schema-invalid response into a FAILED run rather than a crash (spec:
"If an API response changes: Log the error, save raw response, mark run
Partial/Failed. Do not generate Missing or Removed events.").
"""
from __future__ import annotations

from competitors.kfc.backend import schema_validator
from competitors.kfc.tests.test_change_detector import bump_run, ingest


def test_valid_channel_result_has_no_problems(delivery_result):
    problems = schema_validator.validate_channel_result(delivery_result)
    assert problems == []
    usable, _ = schema_validator.is_usable(delivery_result)
    assert usable is True


def test_malformed_result_is_flagged(malformed_result):
    problems = schema_validator.validate_channel_result(malformed_result)
    assert problems  # missing branchId, categoryResults, products, etc.
    usable, _ = schema_validator.is_usable(malformed_result)
    assert usable is False


def test_invalid_status_alone_does_not_block_ingestion():
    """A well-shaped result with an unexpected status string should still
    be flagged as a problem, but must not block ingestion outright - the
    ingestion layer decides what to do with an odd status, not the
    schema validator."""
    data = {
        "channel": "PICKUP", "status": "WEIRD_NEW_STATUS", "branchId": 251, "branchName": "SITEEN",
        "categoryResults": [], "products": [],
    }
    problems = schema_validator.validate_channel_result(data)
    assert any("invalid status" in p for p in problems)
    usable, _ = schema_validator.is_usable(data)
    assert usable is True


def test_product_missing_identity_fields_is_flagged():
    data = {
        "channel": "PICKUP", "status": "SUCCESS", "branchId": 251, "branchName": "SITEEN",
        "categoryResults": [], "products": [{"originalPrice": 10}],  # no id, no name
    }
    problems = schema_validator.validate_channel_result(data)
    assert any("neither 'id' nor 'name'" in p for p in problems)


def test_products_not_a_list_is_flagged_and_blocks_ingestion():
    data = {
        "channel": "PICKUP", "status": "SUCCESS", "branchId": 251, "branchName": "SITEEN",
        "categoryResults": [], "products": {"not": "a list"},
    }
    usable, problems = schema_validator.is_usable(data)
    assert usable is False
    assert any("not a list" in p for p in problems)


def test_schema_invalid_file_becomes_a_failed_run_not_a_crash(conn, tmp_path, malformed_result):
    result = ingest(conn, tmp_path, "batch1", "PICKUP", bump_run(malformed_result, "2026-08-01") if "startedAt" not in malformed_result else malformed_result)
    assert result["status"] == "FAILED"
    row = conn.execute("SELECT * FROM crawl_runs WHERE run_id = ?", (result["run_id"],)).fetchone()
    assert row["status"] == "FAILED"
    assert row["error_message"] is not None
    # No change events, no dimension-table pollution from an unusable file.
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (result["run_id"],)).fetchall()
    assert events == []
