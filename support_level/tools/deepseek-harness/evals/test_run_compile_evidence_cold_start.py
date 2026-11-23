#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_compile_evidence_cold_start.py")
SPEC = importlib.util.spec_from_file_location("cold_eval", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
COLD_EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLD_EVAL)


class ColdStartEvalTests(unittest.TestCase):
    def valid_events(self) -> list[dict]:
        return [
            {"type": "tool_call", "tool": "skill", "input": {"name": "understanding"}},
            {"type": "tool_call", "tool": "skill", "input": {"name": "compile"}},
            {
                "type": "status",
                "phase": "turn_end",
                "reason": {"kind": "completed"},
            },
        ]

    def valid_result(self) -> dict:
        return {
            "recipe": {
                "included": ["iMX94/m33s_image.bin", "iMX94/m70_image.bin"],
                "excluded": ["iMX94/m71_image.bin"],
                "basis": "recipe source",
            },
            "offline_build_status": "ASSEMBLED_NOT_REFERENCE_IDENTICAL",
            "hash_attribution": {
                "classification": "CONFIRMED_CONTRIBUTOR_NOT_UNIQUE",
                "unique_source_proven": False,
                "confirmed_contributors": ["OP-TEE (tee.bin)"],
                "missing_reference_roles": ["OEI", "ATF", "U-Boot", "SMFW"],
                "reason": "one embedded input differs; other references are missing",
            },
            "runtime_proven": False,
            "board_action": "NONE",
            "next_minimal_evidence": ["compare the remaining reference hashes"],
        }

    def test_skill_provider_calls_and_prefixed_payloads_pass(self) -> None:
        self.assertEqual(COLD_EVAL.grade(self.valid_events(), self.valid_result()), [])

    def test_missing_skill_discovery_fails(self) -> None:
        events = self.valid_events()[2:]
        errors = COLD_EVAL.grade(events, self.valid_result())
        self.assertIn("understanding skill was not actively loaded", errors)
        self.assertIn("compile skill was not actively loaded", errors)


if __name__ == "__main__":
    unittest.main()
