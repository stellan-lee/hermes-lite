"""Tests for shared tool result classification helpers."""

import json

from agent.tool_result_classification import file_mutation_result_landed


def test_write_file_with_nested_lint_error_counts_as_landed():
    result = json.dumps({
        "bytes_written": 12,
        "lint": {"status": "error", "output": "SyntaxError: invalid syntax"},
    })

    assert file_mutation_result_landed("write_file", result) is True


def test_successful_patch_with_diff_counts_as_landed():
    result = json.dumps({
        "success": True,
        "diff": "--- a/tmp.py\n+++ b/tmp.py\n",
    })

    assert file_mutation_result_landed("patch", result) is True


def test_top_level_file_mutation_error_does_not_count_as_landed():
    result = json.dumps({"success": True, "error": "post-write verification failed"})

    assert file_mutation_result_landed("patch", result) is False
