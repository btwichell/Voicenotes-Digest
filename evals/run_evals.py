"""Eval runner: feed synthetic notes directly, judge the digest output."""

import json
import re
import sys
import textwrap
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-4-5"

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "digest_v1.md"


def run_digest(system_prompt: str, notes: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": f"I've already pulled all your voice notes. Here they are:\n\n{notes}\n\nGive me my morning briefing."}],
    )
    return response.content[0].text


def check_word_count(output: str, criterion: str) -> dict:
    match = re.search(r'(\d+)\s+words', criterion)
    if not match:
        return {"criterion": criterion, "verdict": "PASS", "reason": "no limit found"}
    limit = int(match.group(1))
    count = len(output.split())
    if count <= limit:
        return {"criterion": criterion, "verdict": "PASS", "reason": f"{count} words"}
    return {"criterion": criterion, "verdict": "FAIL", "reason": f"{count} words, limit is {limit}"}


def judge_output(output: str, criteria: list[str]) -> dict:
    criteria_str = "\n".join(f"- {c}" for c in criteria)
    response = client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": f"""Grade this morning digest against the rubric.

DIGEST:
{output}

CRITERIA:
{criteria_str}

Return JSON only, no markdown fences:
{{
  "criteria_results": [
    {{"criterion": "...", "verdict": "PASS", "reason": "10 words max"}}
  ],
  "overall": "PASS"
}}

overall is PASS only if every criterion passes."""}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(raw.strip())
    return obj


def run_fixture(fixture_path: Path, system_prompt: str) -> bool:
    fixture = json.loads(fixture_path.read_text())
    print(f"\n{'=' * 50}")
    print(f"Fixture : {fixture_path.name}")
    print(f"Scenario: {fixture['description']}")

    digest = run_digest(system_prompt, fixture["notes"])
    preview = digest[:300] + "..." if len(digest) > 300 else digest
    wrapped = textwrap.fill(preview, width=80)
    print(f"\nDigest output:\n{wrapped}\n")

    word_count_criteria = [c for c in fixture["criteria"] if "words" in c.lower()]
    qualitative_criteria = [c for c in fixture["criteria"] if "words" not in c.lower()]

    all_results = [check_word_count(digest, c) for c in word_count_criteria]

    if qualitative_criteria:
        verdict = judge_output(digest, qualitative_criteria)
        all_results.extend(verdict["criteria_results"])

    for cr in all_results:
        icon = "✓" if cr["verdict"] == "PASS" else "✗"
        print(f"  {icon}  {cr['criterion']}")
        if cr["verdict"] == "FAIL":
            print(f"       → {cr['reason']}")

    overall = "PASS" if all(cr["verdict"] == "PASS" for cr in all_results) else "FAIL"
    print(f"\n  Overall: {overall}")
    return overall == "PASS"


def main() -> None:
    system_prompt = SYSTEM_PROMPT_PATH.read_text()
    fixtures = sorted(FIXTURES_DIR.glob("*.json"))

    if not fixtures:
        print("No fixtures found in evals/fixtures/")
        sys.exit(1)

    results = [run_fixture(f, system_prompt) for f in fixtures]
    passed = sum(results)
    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
