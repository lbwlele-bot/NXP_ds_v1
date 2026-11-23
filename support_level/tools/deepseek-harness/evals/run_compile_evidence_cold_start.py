#!/usr/bin/env python3
"""Run and semantically grade a no-session DeepSeek compile-evidence eval."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
HARNESS_DIR = HERE.parent
DS_ROOT = HARNESS_DIR.parents[2]
WORKSPACE = DS_ROOT / "workspace"
PROMPT = HERE / "compile-evidence-cold-start.md"
READONLY_PATCH = HARNESS_DIR / "readonly.patch.yml"
DSH = HARNESS_DIR / "dsh"  # Offline eval: do not inject the board MCP.


def parse_json_lines(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def final_object(events: list[dict]) -> dict:
    finals = [event for event in events if event.get("type") == "final"]
    if not finals:
        raise ValueError("missing final event")
    text = finals[-1].get("text")
    if not isinstance(text, str):
        raise ValueError("final event has no text")
    result = json.loads(text.strip())
    if not isinstance(result, dict):
        raise ValueError("final text is not a JSON object")
    return result


def normalized_set(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value).strip().lower() for value in values}


def normalized_basenames(values: object) -> set[str]:
    return {value.rsplit("/", 1)[-1] for value in normalized_set(values)}


def grade(events: list[dict], result: dict) -> list[str]:
    errors: list[str] = []

    completed = any(
        event.get("type") == "status"
        and event.get("phase") == "turn_end"
        and event.get("reason", {}).get("kind") == "completed"
        for event in events
    )
    if not completed:
        errors.append("turn_end.reason.kind is not completed")

    tool_calls = [event for event in events if event.get("type") == "tool_call"]
    tool_inputs = [
        json.dumps(event.get("input", {}), ensure_ascii=False).lower()
        for event in tool_calls
    ]
    loaded_skills = {
        str(event.get("input", {}).get("name", "")).strip().lower()
        for event in tool_calls
        if event.get("tool") == "skill" and isinstance(event.get("input"), dict)
    }
    if "understanding" not in loaded_skills and not any(
        "understanding/skill.md" in value for value in tool_inputs
    ):
        errors.append("understanding skill was not actively loaded")
    if "compile" not in loaded_skills and not any(
        "compile/skill.md" in value for value in tool_inputs
    ):
        errors.append("compile skill was not actively loaded")

    recipe = result.get("recipe")
    if not isinstance(recipe, dict):
        errors.append("recipe is not an object")
    else:
        included = normalized_basenames(recipe.get("included"))
        excluded = normalized_basenames(recipe.get("excluded"))
        if included != {"m33s_image.bin", "m70_image.bin"}:
            errors.append(f"wrong included M payloads: {sorted(included)}")
        if "m71_image.bin" not in excluded:
            errors.append("m71_image.bin was not explicitly excluded")
        if not str(recipe.get("basis", "")).strip():
            errors.append("recipe basis is empty")

    if result.get("offline_build_status") != "ASSEMBLED_NOT_REFERENCE_IDENTICAL":
        errors.append("offline build status is not ASSEMBLED_NOT_REFERENCE_IDENTICAL")

    attribution = result.get("hash_attribution")
    if not isinstance(attribution, dict):
        errors.append("hash_attribution is not an object")
    else:
        if attribution.get("classification") != "CONFIRMED_CONTRIBUTOR_NOT_UNIQUE":
            errors.append("hash attribution overclaims or misses the confirmed contributor")
        if attribution.get("unique_source_proven") is not False:
            errors.append("unique_source_proven must be false")
        contributors = normalized_set(attribution.get("confirmed_contributors"))
        if not any("op-tee" in value or "optee" in value for value in contributors):
            errors.append("OP-TEE is not identified as a confirmed contributor")
        missing = normalized_set(attribution.get("missing_reference_roles"))
        required_missing = {"oei", "atf", "u-boot", "smfw"}
        if not required_missing.issubset(missing):
            errors.append(
                "missing_reference_roles does not cover "
                + ", ".join(sorted(required_missing - missing))
            )
        if not str(attribution.get("reason", "")).strip():
            errors.append("hash attribution reason is empty")

    if result.get("runtime_proven") is not False:
        errors.append("runtime_proven must be false")
    if result.get("board_action") != "NONE":
        errors.append("board_action must be NONE")
    next_evidence = result.get("next_minimal_evidence")
    if not isinstance(next_evidence, list) or not next_evidence:
        errors.append("next_minimal_evidence is empty")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output.exists():
        print(f"REFUSE_OVERWRITE: {output}", file=sys.stderr)
        return 2
    if not output.parent.is_dir():
        print(f"OUTPUT_PARENT_MISSING: {output.parent}", file=sys.stderr)
        return 2

    command = [
        str(DSH),
        "--profile",
        "headless",
        "--patch",
        str(READONLY_PATCH),
        "--json",
        PROMPT.read_text(encoding="utf-8"),
    ]
    completed = subprocess.run(
        command,
        cwd=WORKSPACE,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        check=False,
    )
    output.write_text(completed.stdout, encoding="utf-8")
    if completed.stderr:
        output.with_suffix(output.suffix + ".stderr").write_text(
            completed.stderr, encoding="utf-8"
        )

    events = parse_json_lines(completed.stdout)
    try:
        result = final_object(events)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    errors = grade(events, result)
    if completed.returncode != 0:
        errors.append(f"dsh exit code is {completed.returncode}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    session_ids = [
        event.get("sessionId")
        for event in events
        if event.get("type") == "session" and event.get("sessionId")
    ]
    session = session_ids[-1] if session_ids else "UNKNOWN"
    print(f"PASS: fresh session {session}")
    print(f"RESULT: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
