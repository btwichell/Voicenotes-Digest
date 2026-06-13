# voicenotes-digest

A Python agent that reads voice notes via the Voicenotes MCP server and
delivers a morning briefing to your phone via iMessage, scheduled at 7am via
launchd. Built on the raw Anthropic API with a hand-rolled MCP client.

The output is table stakes -- Claude ships a connector that produces the same
thing with no code. The point of this repo is the inspectable loop: the OAuth
handshake, tool-call mechanics, agent loop, persistent token storage, and eval
suite are all visible and explainable.

---

## Architecture

    Voice Notes (mobile app)
            |
            v
    Voicenotes MCP Server       OAuth 2.1 / PKCE
    api.voicenotes.com/mcp      tokens at ~/.config/voicenotes_mcp/
            |  list_notes, get_transcript
            v
    agent_loop.py               Python MCP client
      connect, fetch tool list
      drive the tool-call loop
            |  messages.create + tool_result
            v
    Anthropic API               claude-sonnet-4-5
      select tools, generate digest
            |  final text
            v
    send_sms.py                 AppleScript -> iMessage
            |
            v
    Your phone @ 7am            scheduled via launchd

Eval flow (no live MCP required):

    evals/fixtures/*.json -> run_evals.py
      synthetic notes               |
      + criteria per fixture        +-- word count: Python (deterministic)
                                    +-- quality:    LLM-as-judge -> PASS/FAIL
                                    9/10 passing

---

## Files

| File | What it is |
|---|---|
| `agent_loop.py` | Production agent: connects, runs the loop, delivers digest |
| `send_sms.py` | iMessage delivery via AppleScript |
| `prompts/digest_v1.md` | System prompt: retrieval strategy, format rules, word cap |
| `evals/run_evals.py` | Eval runner: hybrid word-count + LLM-as-judge |
| `evals/fixtures/` | 10 synthetic test cases covering edge scenarios |
| `DECISIONS.md` | Architecture decisions with reasoning and tradeoffs |
| `connect.py` | Task 5 proof: OAuth handshake + tool listing only |
| `single_call.py` | Task 6 proof: single tool round trip, wire format visible |
| `first_call.py` | Task 3 proof: raw API call, simplest possible |

---

## Setup

Requires Python 3.13 and uv (https://docs.astral.sh/uv/).

    git clone <repo>
    cd voicenotes-digest
    uv sync
    cp .env.example .env   # add your ANTHROPIC_API_KEY

First run opens a browser to authorize Voicenotes. Tokens persist to
~/.config/voicenotes_mcp/tokens.json so subsequent runs are headless.

    uv run agent_loop.py       # run the agent
    uv run evals/run_evals.py  # run the eval suite

To schedule at 7am, see the launchd plist at
~/Library/LaunchAgents/com.bennett.voicenotes-digest.plist.

---

## Evals

10 fixtures covering: single urgent item, multiple priorities, errands, wins,
repeated topics, large volume, ideas-only, stale items, and no actionable
content. Word count checked in Python; qualitative criteria via LLM-as-judge
returning structured JSON.

9/10 passing. Fixture 06 (large volume, five items) reliably fails the two-item
cap -- documented in DECISIONS.md as a known ceiling, not a bug to chase.

---

## Design decisions

See DECISIONS.md for 12 entries covering architecture choices, tradeoffs
considered, and what each decision transfers to a real production context.
