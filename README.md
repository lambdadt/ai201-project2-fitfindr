# FitFindr

An AI agent that helps users find secondhand clothing and get outfit suggestions
based on their existing wardrobe. Uses the Groq API (llama-3.3-70b-versatile)
for LLM-powered outfit suggestions and fit card generation.

## Setup

```bash
# Install dependencies
uv pip install -r requirements.txt

# Set your Groq API key
echo 'GROQ_API_KEY=your_key_here' > .env

# Run the app
python app.py
# → opens http://localhost:7860

# Run agent from CLI
python agent.py                  # deterministic mode
python agent.py --agentic        # LLM-driven mode
python agent.py --agentic --verbose   # with ReAct trace

# Run tests
uv run pytest tests/ -v
```

## Architecture

```
tools.py       →  3 standalone tool functions (search_listings, suggest_outfit, create_fit_card)
agent.py       →  planning loop (deterministic + agentic modes), session state, CLI
app.py         →  Gradio web UI (3 output panels: listing, outfit, fit card)
data/          →  listings.json (40 mock items), wardrobe_schema.json
utils/         →  data_loader.py
tests/         →  test_tools.py (12 tests)
```

## Tool Inventory

### Tool 1: `search_listings(description, size, max_price) -> list[dict]`

| Field | Type | Description |
|---|---|---|
| `description` | `str` | Keywords describing what to search for (e.g. "vintage graphic tee") |
| `size` | `str \| None` | Optional size filter — case-insensitive substring match ("M" matches "S/M") |
| `max_price` | `float \| None` | Optional price ceiling (inclusive) |

Searches the 40-item mock dataset by scoring each listing on keyword overlap
against its title, description, and style_tags. Filters by size and price when
provided. Returns matches sorted by relevance (highest score first). Returns
`[]` on no matches — does not raise.

**Purpose**: Translates a user's natural language request into filtered, ranked
search results the agent can pass to downstream tools.

### Tool 2: `suggest_outfit(new_item, wardrobe) -> str`

| Field | Type | Description |
|---|---|---|
| `new_item` | `dict` | A listing dict from `search_listings` |
| `wardrobe` | `dict` | Dict with `"items"` key containing a list of wardrobe item dicts |

Calls the Groq LLM to generate 1–2 outfit suggestions. When the wardrobe has
items, names specific pieces. When the wardrobe is empty, returns general
styling advice. Never returns an empty string — if the API fails, returns a
fallback message with the exception details.

**Purpose**: Bridges search results and the user's wardrobe to produce
actionable styling advice the LLM can pass to the caption generator.

### Tool 3: `create_fit_card(outfit, new_item) -> str`

| Field | Type | Description |
|---|---|---|
| `outfit` | `str` | The outfit suggestion string from `suggest_outfit` |
| `new_item` | `dict` | The listing dict for the thrifted item |

Calls the Groq LLM at temperature 0.9 to generate a 2–4 sentence
Instagram/TikTok-style caption. Mentions the item name, price, and platform
naturally. Returns an error string (not an exception) if the outfit string is
empty or whitespace-only. On API failure, returns the exception message.

**Purpose**: Produces a shareable, authentic-feeling caption from the outfit
suggestion and item details.

## Planning Loop

The agent supports **two modes**, selected via `deterministic=` keyword:

### Deterministic Mode (default)

Fixed pipeline: **parse → search → select → suggest → create**

1. `_parse_query()` uses the LLM to extract `description`, `size`, `max_price`
   from natural language.
2. `search_listings()` searches with the parsed parameters.
3. **Branch**: if results are empty, sets `session["error"]` and returns
   early — `suggest_outfit` and `create_fit_card` are never called.
4. Selects `results[0]` as `selected_item`.
5. `suggest_outfit(selected_item, wardrobe)` → stores in `outfit_suggestion`.
6. `create_fit_card(outfit_suggestion, selected_item)` → stores in `fit_card`.
7. Returns the session dict.

Every step is wrapped in try/except — failures set `session["error"]` with a
descriptive message including the exception.

### Agentic Mode (`--agentic`)

LLM-driven **ReAct loop** using Groq's native tool calling API
(`tools=[...]`, `tool_choice="auto"`). The LLM receives:

- A system prompt describing the workflow and rules
- The user's query
- The available tool definitions (JSON schemas for each function)
- The full chat history (all prior tool calls and results)

Each iteration, the LLM decides which tool to call next. The loop:

1. Calls Groq with the current `messages` list.
2. If the response has **no `tool_calls`**: the LLM is done → exit.
3. If the response has **`tool_calls`**: execute each tool, inject stored
   session data (`selected_item`, `wardrobe`, `outfit_suggestion`) into the
   args so the LLM doesn't need to pass large objects, append results to
   `messages`, and loop.

The LLM handles the no-results case naturally — when `search_listings` returns
`[]`, the LLM writes a natural language response telling the user nothing was
found. The post-loop check detects this and sets `session["error"]` from the
LLM's text.

A retry mechanism handles transient Groq `tool_use_failed` errors (malformed
LLM-generated JSON) — up to 3 retries per step.

## State Management

Two parallel tracks serve different consumers:

**Chat history (`messages` list)** — the LLM's view of state. Every tool call
and result is appended in order. The LLM reads back through the history to see
what happened and decide what to do next.

**Session dict** — the caller's view of state. Built inside the planning loop
and returned to `handle_query()` in `app.py`, which reads `selected_item`,
`outfit_suggestion`, and `fit_card` to populate the three Gradio panels.
The LLM never accesses the session dict directly.

```
session = {
    "query": str,                  # original user input
    "parsed": dict,                # extracted description/size/max_price
    "search_results": list[dict],  # matching listings
    "selected_item": dict | None,  # top result, passed into suggest_outfit
    "wardrobe": dict,              # user's wardrobe
    "outfit_suggestion": str | None,  # from suggest_outfit
    "fit_card": str | None,        # from create_fit_card
    "error": str | None,           # set on early termination
}
```

**Verification**: `selected_item` is the identical Python object as
`search_results[0]` — no copies or re-fetching between tool calls.

## Error Handling

| Tool | Failure mode | Behavior | Verified by test |
|---|---|---|---|
| `search_listings` | No matches | Returns `[]`. Planning loop sets `session["error"]` and returns early — `suggest_outfit` and `create_fit_card` are never called. | `test_search_empty_results` |
| `search_listings` | Exception during search | Caught in `_run_deterministic`, sets `session["error"]` with the exception message. | (tested manually) |
| `suggest_outfit` | Wardrobe empty | Returns general styling advice instead of specific pairings — never an empty string. | `test_suggest_outfit_empty_wardrobe` |
| `suggest_outfit` | Groq API failure | Catches the exception, returns a fallback string with the traceback included. | `test_suggest_outfit_api_failure` |
| `create_fit_card` | Empty/whitespace outfit | Returns `"Unable to generate a fit card — no outfit was provided. Try running the outfit suggestion step first."` (no exception). | `test_create_fit_card_empty_outfit`, `test_create_fit_card_whitespace_outfit` |
| `create_fit_card` | Groq API failure | Catches the exception, returns `"Error generating fit card: <message>"`. | `test_create_fit_card_api_failure` |
| Agentic mode | `tool_use_failed` from Groq | Retries up to 3 times. On final failure, sets `session["error"]` with the full error. | (verified in verbose agentic runs) |

### Concrete example from testing

**No-results path** (`designer ballgown size XXS under $5`):
```
session["error"]    → "No listings matched 'designer ballgown' under $5.
                       Try broader keywords, drop the size filter, or raise
                       your price ceiling."
session["fit_card"] → None
```
`suggest_outfit` and `create_fit_card` are never invoked — the loop returns
after `search_listings` returns `[]`.

## Spec Reflection

The implementation largely matches the planning.md spec. Key divergences:

- **How the spec helped**: Filling in the error handling table in planning.md
  before writing `_run_deterministic` made the branching logic obvious — every
  row in the table became a try/except block with a specific `session["error"]`
  message. Without the table, it would have been easy to miss the
  `create_fit_card` API failure case or the whitespace-only outfit guard in
  `handle_query`. The table also directly informed which tests to write —
  each row maps to a `test_*` function in `tests/test_tools.py`.

- **`suggest_outfit` return type**: planning.md originally explored
  `list[list[dict]]` for structured outfit data, but the stub signature returns
  `str` (free-form text). The implementation follows the stub — natural
  language outfit descriptions that `create_fit_card` can caption directly.
  This kept the tools simpler and avoided the LLM needing to parse structured
  JSON from another LLM.

- **Session dict vs. result dict**: planning.md described a result dict
  returned by `run_tool_phase()`. The implementation uses the session dict
  from the starter template (`_new_session()`) instead, passed by reference
  into the planning loop and returned to the caller. Same concept, different
  naming.

- **Agentic mode arg injection**: planning.md assumed the LLM would pass
  tool arguments from the chat history, but Groq's tool calling struggles with
  large nested objects. The implementation injects `selected_item`, `wardrobe`,
  and `outfit_suggestion` from the session before calling each tool, so the
  LLM controls *when* tools are called but not *what data* they receive.

- **Result compression**: planned but not yet implemented. The compact mock
  dataset (40 listings) makes this unnecessary for current usage, but it
  should be added if the dataset grows or for multi-turn conversations with
  many tool calls.

## AI Usage

### Instance 1: `search_listings` in `tools.py`

**Input given**: Tool 1 block from planning.md (what it does, input parameters
with types, return value with field descriptions, failure mode), plus the
data loader API (`load_listings()` from `utils/data_loader.py`).

**What it produced**: A function that loads the 40 listings, tokenizes the
description, scores each listing by keyword overlap against `title` +
`description` + `style_tags`, filters by size (case-insensitive substring)
and `max_price` (≤ ceiling), drops score-0 items, and returns results sorted
by score descending with price as tiebreaker.

**What I changed**: The initial output didn't handle the empty-description
edge case gracefully (split on `""` produces `[""]`, causing a phantom match
and returning all listings). I verified with `search_listings("", max_price=10)`
to ensure it returned `[]`. Also adjusted the test `test_search_price_filter`
from `max_price=10` to `max_price=50` after discovering the cheapest jacket in
the dataset is $33 — the original test had no matches in the dataset.

### Instance 2: Agentic planning loop (`_run_agentic`) in `agent.py`

**Input given**: Planning Loop section from planning.md (two-loop design,
inner loop branching logic, key branches the LLM can take), State Management
section (chat history as LLM state, result dict for caller), and the
Architecture Mermaid diagram showing data flow through the tool phase.

**What it produced**: An LLM-driven ReAct loop using Groq's native
`tools=[...]` API with `tool_choice="auto"`. The loop builds `messages`
(system prompt + user query + wardrobe), calls Groq, executes any returned
`tool_calls`, appends tool results, and repeats until the LLM returns text
with no `tool_calls`. The system prompt encodes the workflow rules (no
results → stop, empty wardrobe → still proceed).

**What I changed**:
- **Arg injection**: The LLM struggled to pass large nested dicts (listing
  objects, wardrobe) between tool calls — Groq's API errored with
  `tool_use_failed` when the LLM tried to inline full listing JSON. I
  overrode the tool call execution to inject `selected_item`, `wardrobe`, and
  `outfit_suggestion` from the session dict before calling each tool, so the
  LLM controls *when* tools are called but the execution layer handles *what
  data* they receive.
- **Retry on `tool_use_failed`**: Added a retry loop (up to 3 attempts) for
  transient `tool_use_failed` errors caused by malformed LLM-generated JSON
  (extra braces, trailing commas). This eliminated spurious failures.
- **Post-loop error detection**: Added a check after the loop exits — if
  `search_results` is empty and `selected_item` is None, the LLM's final text
  response is used as `session["error"]` so `app.py` routes it correctly
  without the LLM needing to know about the session schema.
- **Verbose logging**: Added `verbose` parameter that prints each step's tool
  call arguments and result summaries, making the ReAct loop inspectable at
  runtime (`--verbose` flag).

## Commands Reference

```bash
# Install
uv pip install -r requirements.txt

# Run app
python app.py

# Run agent CLI
python agent.py                      # deterministic
python agent.py --agentic            # LLM-driven
python agent.py --agentic --verbose  # LLM-driven with ReAct trace

# Tests
uv run pytest tests/ -v              # all tests
uv run pytest tests/test_tools.py -v # tool tests only
```
