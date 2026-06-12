# AGENTS.md — FitFindr

## Project Overview

FitFindr is a Gradio web app that helps users find secondhand clothing and get outfit suggestions. It uses the Groq API for LLM-powered suggestions. Python 3.12+, managed with `uv`.

Architecture: `tools.py` (3 standalone tool functions) → `agent.py` (inner tool-calling loop + outer chat loop) → `app.py` (Gradio UI). Data lives in `data/` as JSON files, loaded via `utils/data_loader.py`.

### High-Level Loop Design

The agent uses **two nested loops** to support multi-turn conversation:

```
OUTER LOOP (chat — in handle_query / agent.py)
│  user: "find me a vintage tee under $30"
│    └─► INNER LOOP (tool phase — run_tool_phase())
│         LLM → search_listings
│         LLM → suggest_outfit
│         LLM → create_fit_card
│         LLM → "Here's what I found..."        ← final text, no more tool_calls
│         returns (messages, result) where result = {selected_item, outfit, fit_card, error}
│
│  user: "actually, show me cheaper ones"
│    └─► INNER LOOP (tool phase)
│         LLM reads compressed history, calls tools again
│         ...
```

- **Inner loop** (`run_tool_phase()`): takes the current `messages` list, calls the Groq API with `tools=[...]`, executes any tool calls the LLM requests, appends results, and repeats until the LLM returns a text response with no `tool_calls`. Returns a tuple of `(messages, result)` — the compressed message list and a structured dict of what the tools produced.
- **Outer loop** (in `app.py` or `agent.py`): appends each new user message to `messages`, calls the inner loop, then reads the returned result dict to populate the three Gradio output panels.

## Commands

```bash
# Install dependencies
uv pip install -r requirements.txt

# Run the app (starts Gradio on http://localhost:7860)
python app.py

# Run agent from CLI (for quick testing)
python agent.py

# Verify data loads (sanity check)
python utils/data_loader.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_tools.py

# Run a single test function
pytest tests/test_tools.py::test_search_listings

# Run tests with verbose output
pytest -v
```

There is no linter or type-checker configured yet. If you add one, document it here. Recommended: `ruff` for linting/formatting, `mypy` for type checking.

## Code Style

### Imports

Three groups, separated by blank lines, in this order:

```python
# 1. Standard library
import json
import os

# 2. Third-party
from dotenv import load_dotenv
from groq import Groq

# 3. Local / project
from utils.data_loader import load_listings
```

Never use relative imports (`from ..utils import ...`). Always import from the project root.

### Formatting

- 4 spaces for indentation (no tabs)
- Lines should not exceed ~100 characters; break long function signatures across multiple lines with hanging indents
- Top-level functions and classes are separated by two blank lines; methods by one blank line
- Section comments use `# ── Section Name ──` with em-dashes for visual separation (see existing files)

### Types

- Use Python 3.10+ union syntax: `str | None`, not `Optional[str]`
- Every function signature must have type hints on all parameters and the return type
- Pydantic models (from `pydantic>=2.13.4`) should be used for complex data validation when needed
- Avoid `Any` — prefer concrete types or `dict` / `list[dict]` when structure is known

### Naming Conventions

| Category | Convention | Examples |
|---|---|---|
| Files | `snake_case` | `tools.py`, `data_loader.py` |
| Functions | `snake_case` | `search_listings()`, `load_listings()` |
| Variables | `snake_case` | `user_query`, `new_item`, `selected_item` |
| Constants | `UPPER_SNAKE_CASE` | `_DATA_DIR`, `EXAMPLE_QUERIES` |
| Private helpers | `_leading_underscore` | `_get_groq_client()`, `_new_session()` |
| Classes / Pydantic models | `PascalCase` | `WardrobeItem`, `Listing` |
| JSON keys | `snake_case` | `style_tags`, `max_price` |

### Docstrings

Use Google-style docstrings on every public function. Include `Args`, `Returns`, and `Raises` sections when applicable:

```python
def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for matching items.

    Args:
        description: Keywords describing what the user is looking for.
        size: Size string to filter by, or None to skip size filtering.
        max_price: Maximum price (inclusive), or None to skip.

    Returns:
        A list of matching listing dicts, sorted by relevance.
        Returns an empty list if nothing matches — does NOT raise.

    Raises:
        FileNotFoundError: If the listings JSON file is missing.
    """
```

### Error Handling

- **Tools return empty/missing values, not exceptions**, for expected failures:
  - `search_listings()` returns `[]` on no matches
  - `suggest_outfit()` returns styling advice even for empty wardrobes
  - `create_fit_card()` returns an error message string when input is invalid
- The **result dict** returned by the inner loop carries error state via `result["error"]`. When a step sets `result["error"]` to a string, the agent returns early. Check `result["error"]` before accessing output fields.
- Only raise exceptions for truly unexpected failures (missing files, missing API keys, network errors). `_get_groq_client()` raises `ValueError` if `GROQ_API_KEY` is not set.

### Session Pattern

The inner loop returns a **result dict** — the structured output the outer loop reads to populate the UI. It is created fresh inside `run_tool_phase()` and returned alongside the compressed `messages` list:

```python
# Signature:
messages, result = run_tool_phase(messages)

# result dict fields:
result = {
    "selected_item": dict | None,     # top search result
    "outfit_suggestion": str | None,  # from suggest_outfit
    "fit_card": str | None,           # from create_fit_card
    "error": str | None,              # set on early termination
}
```

The inner loop builds `result` as tools execute — when `search_listings` runs, it records the top match; when `suggest_outfit` runs, it records the outfit text; etc. If any step sets `result["error"]`, the loop returns early. The outer loop checks `result["error"]` first, then extracts the three output fields for the Gradio panels.

### Tool Design Patterns

Each tool is a **pure function** — it receives inputs, returns outputs, and does not access global state (except the LLM client factory `_get_groq_client()`). Tools are independently testable before being wired into the agent loop.

The agent loop (`run_agent()`) presents available tools to the LLM along with the current session state. The **LLM decides** which tool to call next and with what arguments, based on what's happened so far. It is not a fixed sequence — if search returns nothing, the LLM can skip outfit suggestion and end early; if the wardrobe is empty, it can still call `suggest_outfit` knowing the tool handles that gracefully. The loop continues until the LLM signals it is done.

### Agent Loop Implementation

The agent uses **Groq's native tool-calling API** (`client.chat.completions.create(..., tools=[...], tool_choice="auto")`). The LLM returns structured `ChatCompletionMessageToolCall` objects — no manual JSON parsing needed.

**Inner loop pseudocode** (`run_tool_phase()`):

```python
def run_tool_phase(messages: list[dict], max_steps: int = 20) -> tuple[list[dict], dict]:
    result = {"selected_item": None, "outfit_suggestion": None,
              "fit_card": None, "error": None}

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOL_DEFS,
            tool_choice="auto",
        )
        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            break                      # LLM returned text → done

        for tc in msg.tool_calls:
            tool_result = TOOL_FNS[tc.function.name](**json.loads(tc.function.arguments))
            record_in_result(result, tc.function.name, tool_result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result),
            })

    return compress_tool_results(messages), result

### Why Native Tool Calling (Not a 3-Message Scratchpad)

- Groq's `tools` parameter produces structured `tool_calls` — no ambiguity, no parsing errors.
- Messages are always appended (system + user + assistant + tool results), so the prefix never changes. The KV-cache stays hot across iterations — no cache misses.
- The chat history *is* the state for the LLM. It reads back through prior tool calls to understand context.

### Result Dict vs. Chat History

The LLM sees the full `messages` list (chat history with tool results). The `result` dict serves a different purpose — it is the **caller's structured view** of what happened, used by `app.py` to populate the three Gradio output panels:

```python
# app.py extracts from the result dict returned by run_tool_phase()
messages, result = run_tool_phase(messages)

listing_text  = format_listing(result["selected_item"])
outfit_text   = result["outfit_suggestion"]
fitcard_text  = result["fit_card"]
```

### Result Compression

After the inner loop finishes, old `role: "tool"` messages have their content replaced with one-line summaries. This keeps the context lean for multi-turn conversations without losing the LLM's awareness of what happened:

```
Before: {"role": "tool", "content": "[40 listings worth of JSON...]" }
After:  {"role": "tool", "content": "[search_listings returned 3 matches: 'Nirvana Tee' $22, 'Band Tee' $18, 'Retro Tee' $28]"}
```

The latest 1–2 tool results stay in full so the LLM can reference details. Summaries are immutable once written, keeping the prefix stable for KV-cache reuse across future outer-loop iterations.

## Testing

- Framework: `pytest` (>=8.0.0)
- Test files go in `tests/`, named `test_*.py`
- Test functions are named `test_<what_you_are_testing>()`
- Use `pytest.fixture` for shared setup (e.g., loading the listings dataset)
- Mock the Groq client for tests that call `_get_groq_client()` to avoid real API calls
- Test each tool in isolation first, then test the agent loop

## Key Dependencies

| Package | Usage |
|---|---|
| `gradio` | Web UI (components, layout, event wiring) |
| `groq` | LLM API client (outfit suggestions, fit-card generation) |
| `pydantic` | Data validation and serialization |
| `python-dotenv` | Load `GROQ_API_KEY` from `.env` |
| `pytest` | Test runner |
