# DECISIONS.md

Running log of architecture decisions for the Voicenotes Automation Hub.

---

## Build on the raw API instead of the managed Voicenotes connector

Claude already ships a Voicenotes connector, and a scheduled task on top of it
would produce the same morning digest with no code. I built the client against
the raw Anthropic API and MCP endpoint anyway, because the connector hides the
parts worth learning: the OAuth handshake, the tool-call loop, error and
empty-state handling, and where the context budget gets spent.

The managed path is the right default for almost anyone who just wants the
output. The reason to own the loop is control and inspectability: custom
tool-selection logic, your own retry and failure behavior, and the ability to
see exactly what gets sent to the model. This repo exists to be that inspectable
version.

The transferable judgment: knowing when a managed abstraction is enough and when
a team needs to own the loop themselves. That call depends on how much the team
needs to customize tool behavior, control failure modes, or audit what hits the
model. Defaulting to the managed layer until one of those forces a change is
usually the cheaper path.

---

## Custom MCP client over the Anthropic SDK's built-in mcp_servers parameter

The Anthropic SDK has a built-in mcp_servers parameter that handles MCP
connections automatically. Using it would have been faster. I built against the
mcp Python package directly instead, managing the tool list and agent loop
manually.

The reason is artifact quality. The built-in parameter hides the transport
layer, the OAuth handshake, and the tool-call mechanics. Owning those explicitly
makes the repo inspectable and makes the architecture explainable in an
interview. The SDK shortcut produces the same output but none of the
demonstrable work.

The transferable judgment: use the abstraction when shipping speed matters and
the internals are not the point. Own the loop when the internals are the
artifact.

---

## Ship dumb first

Early in the build there was a pull toward correct architecture before working
code. The better outcome came from building the simplest version that ran
end-to-end, then upgrading when a real constraint forced it.

Architecture decisions made before something runs are guesses. Decisions made
after something runs are based on actual friction. For ADHD-paced work in
particular, a working ugly thing maintains momentum in a way that a stalled
elegant design does not. Phase 0 is the ugly working version. Upgrades happen
when a limit is actually hit.

---

## iMessage over Twilio, Pushover, and email-to-text for delivery

Twilio requires 10DLC registration for personal use, which means a multi-week
wait for a daily digest. Pushover works but produces a generic app notification
that competes with hundreds of others. Email-to-text via Verizon's vtext.com
gateway has a 160-character limit that truncates the digest.

iMessage via AppleScript sends to your own number with no third-party service,
no new credentials, no length limit, and no registration. The tradeoff is that
it only runs when the Mac is awake. For a personal digest scheduled at 7am that
is acceptable. If this moves to a cloud runner later, the delivery layer swaps
to something with an HTTP API.

---

## Prompt wording drives tool selection, not just output format

Changing the user message from "what notes do I have from the last few days" to
"review all my voice notes and give me my morning briefing" changed the entire
tool call pattern. The first prompt produced one list_notes call. The second
produced eight parallel search_notes calls followed by six get_transcript calls.

The prompt is not just instructions for how to format the answer. It signals
what the task is, and the model decides which tools to reach for based on that
signal. Treating prompt changes as architecture changes, not copy changes, is
the right mental model.

---

## Parallel tool calls hit rate limits; list_notes replaced search_notes

On the first run with the briefing prompt, Claude fired eight simultaneous
search_notes calls. The Voicenotes MCP server returned a 429 Too Many Requests
error partway through, and the code crashed rather than retrying.

Options considered: retry with backoff, cap parallel calls, or switch retrieval
strategy entirely. The landed fix was replacing search_notes as the primary tool
with list_notes at limit 50, then calling get_transcript selectively on notes
whose titles suggested open items. This eliminated the parallel burst at the
source rather than handling the 429 downstream. Retry logic was added separately
in Task 10 as a safety net, not as the primary fix.

The transferable judgment: a 429 caused by parallel bursts is an architecture
signal, not just an error to catch. If the retrieval pattern is generating
unnecessary requests, fix the pattern first.

---

## FileTokenStorage over InMemoryTokenStorage for unattended execution

The initial OAuth implementation used in-memory token storage: tokens lived only
for the duration of the process, and every run triggered a browser redirect to
re-authenticate. That works fine during development when you are present to
authorize. It breaks completely when a launchd job fires at 7am with no browser
available.

The fix was a FileTokenStorage class that persists tokens to
~/.config/voicenotes_mcp/tokens.json at mode 0600. The tradeoff is tokens on
disk, which is a weaker security posture than a system keychain. For a personal
tool on a personal machine that tradeoff is acceptable. A production deployment
would use the system keychain or a secrets manager instead.

The decision moment was Task 11: the upgrade was not worth doing until
unattended execution was actually required. Doing it earlier would have been
premature. This is the ship-dumb-first principle applied to auth.

---

## LLM-as-judge over string matching for qualitative eval criteria

The target output is defined qualitatively: concise, prioritized, nudge-style,
not a laundry list. None of those properties can be grepped. A string-match
approach would catch only surface patterns, not the thing actually being tested.

LLM-as-judge works here because the rubric can be stated in plain English and
the judge can reason about whether a digest satisfies it. Each criterion is a
short statement the judge grades PASS or FAIL with a brief reason. The judge
returns structured JSON so the runner can aggregate results without parsing
prose.

The tradeoff: LLM grading introduces variance. The same output might get a
different verdict on different runs. That variance is acceptable at this scale
because the criteria are clear enough that borderline cases are rare, and because
the alternative would test the wrong thing entirely.

The transferable judgment: use deterministic checks for anything measurable. Use
LLM-as-judge for anything that requires reading comprehension to evaluate.

---

## Word count enforced in code, not by the judge

The 120-word hard limit is purely numeric and should produce a consistent verdict
every time. Delegating it to the LLM judge introduces unnecessary variance
because language models are unreliable at counting words precisely.

The runner splits criteria at load time: anything containing "words" goes to
check_word_count, which uses Python's str.split() and compares against the
limit. Everything else goes to the judge. The judge never sees the word count
criterion and is not asked to count anything.

This is a general pattern: deterministic checks belong in code, judgment calls
belong in the model. Mixing them by handing counting to an LLM is a source of
flaky tests, not a simplification.

---

## Eval runner feeds notes directly, bypassing the agent loop

The runner calls the digest model with a single messages.create call rather than
running the full agent loop with MCP. This is intentional.

The agent loop was already proven correct in Tasks 5-11: it connects, fetches
notes, and calls the right tools. What Task 12 tests is whether the digest
prompt produces good output given notes that are already in hand. Those are
separate questions. Testing them together would make failures harder to diagnose
and would couple the eval to live API credentials.

Bypassing the loop also makes the eval faster and deterministic in inputs: each
fixture specifies exactly what notes the model sees, which is impossible when the
loop is fetching from the live API.

The transferable judgment: evals should test one thing. If prompt quality and
integration correctness are both in scope, test them separately.

---

## Fixture 06 accepted as a known ceiling, not a fixable bug

Fixture 06 describes a high-volume scenario: five open items across different
priority levels. The prompt instructs the model to surface at most two items and
cut the rest entirely. On this fixture the model lists all five.

Several prompt variations were tried: explicit numeric caps, examples of correct
two-item output, instructions to cut rather than trim. None reliably held the
cap at high volume. The failure appears to be a genuine ceiling on instruction
following when the constraint conflicts with the model's instinct to be
comprehensive.

Accepting this as a documented limit rather than chasing it further was the
right call. The fixture stays in the suite and fails on every run as a reminder
that the two-item constraint is not fully reliable. If a future prompt version
fixes it, the suite will catch that automatically.

The transferable judgment: some eval failures are bugs to fix; others are honest
measurements of a real limit. Knowing which is which prevents wasted iteration.

---

## Prompt iteration required three passes to stabilize eval results

The first eval run exposed a bad assumption: the runner was passing notes to the
same system prompt used in production, but without providing a tool server. The
model responded with raw tool-call XML because it was trying to call list_notes
and had nowhere to send it. The fix was a different user message for evals --
"here are your notes already" -- which bypasses tool selection entirely and
tests only the formatting and prioritization logic.

After that the rubric failures were real. The first version of the prompt had no
explicit word count, a soft instruction to "lead with wins," and no cap on how
many items to surface. Three failures showed up across the fixture set: outputs
ran over the word target, the wins section appeared even when there were no wins,
and Claude surfaced all available items rather than cutting to the most important.

Each failure drove one targeted prompt change: a 120-word hard limit with an
explicit cut instruction; a skip rule for the wins section when there is nothing
to report; a two-item cap; and a clarification that ideas and passing thoughts
are not action items. The suite stabilized at 9/10 after those four changes.

The transferable judgment: change one thing at a time and re-run immediately.
Batching prompt changes obscures which fix moved the needle.
