"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import traceback

from tools import search_listings, suggest_outfit, create_fit_card, _get_groq_client


# ── Tool definitions for agentic mode ──────────────────────────────────────────

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "search_listings",
            "description": (
                "Search the secondhand clothing listings for items matching a "
                "description, with optional size and price ceiling filters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Keywords describing what to search for.",
                    },
                    "size": {
                        "type": "string",
                        "description": "Optional size filter (case-insensitive substring).",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Optional maximum price (inclusive).",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_outfit",
            "description": (
                "Given a thrifted item and the user's wardrobe, suggest 1–2 "
                "complete outfits using specific wardrobe pieces."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "new_item": {
                        "type": "object",
                        "description": "The selected listing dict to build outfits around.",
                    },
                    "wardrobe": {
                        "type": "object",
                        "description": "The user's wardrobe dict with an 'items' list.",
                    },
                },
                "required": ["new_item", "wardrobe"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_fit_card",
            "description": (
                "Generate a short, shareable Instagram/TikTok caption for a "
                "thrifted find given an outfit suggestion and the item details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "outfit": {
                        "type": "string",
                        "description": "The outfit suggestion string from suggest_outfit.",
                    },
                    "new_item": {
                        "type": "object",
                        "description": "The selected listing dict.",
                    },
                },
                "required": ["outfit", "new_item"],
            },
        },
    },
]

TOOL_FNS = {
    "search_listings": search_listings,
    "suggest_outfit": suggest_outfit,
    "create_fit_card": create_fit_card,
}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── query parsing (deterministic mode) ────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """Use the LLM to extract description, size, and max_price from a natural language query."""
    prompt = (
        f'Extract the search parameters from this user query:\n\n"{query}"\n\n'
        f"Return a JSON object with these fields:\n"
        f'  "description": str — the item keywords (e.g. "vintage graphic tee")\n'
        f'  "size": str or null — any size mentioned (e.g. "M", "8")\n'
        f'  "max_price": number or null — any price ceiling mentioned\n\n'
        f"Only include fields that are explicitly mentioned. "
        f"Return ONLY valid JSON, no other text."
    )
    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception:
        return {"description": query, "size": None, "max_price": None}


# ── deterministic planning loop ───────────────────────────────────────────────

def _run_deterministic(session: dict) -> dict:
    """
    Fixed-sequence planning loop: parse → search → select → suggest → create.

    Branches on search results: if nothing matches, sets session["error"]
    and returns early without calling suggest_outfit or create_fit_card.
    """
    try:
        parsed = _parse_query(session["query"])
    except Exception as e:
        session["error"] = f"Failed to parse query: {e}"
        return session
    session["parsed"] = parsed

    try:
        results = search_listings(
            description=parsed.get("description", ""),
            size=parsed.get("size"),
            max_price=parsed.get("max_price"),
        )
    except Exception as e:
        session["error"] = f"search_listings failed: {e}"
        return session
    session["search_results"] = results

    if not results:
        session["error"] = (
            f"No listings matched "
            f"'{parsed.get('description', session['query'])}'"
            + (
                f" under ${parsed['max_price']:.0f}"
                if parsed.get("max_price") is not None
                else ""
            )
            + ". Try broader keywords, drop the size filter, "
            + "or raise your price ceiling."
        )
        return session

    selected = results[0]
    session["selected_item"] = selected

    try:
        session["outfit_suggestion"] = suggest_outfit(selected, session["wardrobe"])
    except Exception as e:
        session["error"] = f"suggest_outfit failed: {e}"
        return session

    try:
        session["fit_card"] = create_fit_card(
            session["outfit_suggestion"], selected
        )
    except Exception as e:
        session["error"] = f"create_fit_card failed: {e}"
        return session

    return session


# ── agentic planning loop ─────────────────────────────────────────────────────

def _run_agentic(session: dict, max_steps: int = 10, verbose: bool = False) -> dict:
    """
    LLM-driven planning loop. The LLM decides which tool to call next based on
    the chat history (messages list). Loops until the LLM returns a plain text
    response with no tool_calls, then maps results into the session dict.
    """
    wardrobe = session["wardrobe"]
    wardrobe_items = wardrobe.get("items", [])

    system_prompt = (
        "You are FitFindr, an agent that helps users find secondhand clothing "
        "and get outfit suggestions. Available tools: search_listings, "
        "suggest_outfit, create_fit_card.\n\n"
        "Workflow: search for items matching the user's request, then suggest "
        "outfits using their wardrobe, then generate a shareable fit card caption.\n\n"
        "Rules:\n"
        "- If search_listings returns no results, tell the user and stop — do NOT "
        "call suggest_outfit or create_fit_card.\n"
        "- If the wardrobe is empty, still call suggest_outfit (it returns general "
        "styling advice) and create_fit_card.\n"
        "- Call tools one at a time. When all steps are done, respond with a "
        "friendly summary of what you found.\n"
        f"\nUser's wardrobe ({len(wardrobe_items)} items):\n"
        + "\n".join(
            f"- {item['name']} ({item['category']}, "
            f"{', '.join(item.get('colors', item.get('color', []))) or 'n/a'}, "
            f"{', '.join(item.get('style_tags', [item.get('style', '')]))})"
            for item in wardrobe_items
        )
        if wardrobe_items
        else "(empty)"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": session["query"]},
    ]

    for step in range(max_steps):
        response = None
        for retry in range(5):
            try:
                client = _get_groq_client()
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    tools=TOOL_DEFS,  # type: ignore[arg-type]
                    tool_choice="auto",
                )
                break
            except Exception as e:
                err = str(e)
                if "tool_use_failed" in err and retry < 2: # Sometimes tool call fails on the Groq end due to malformed output generated by the LLM
                    print("Tool use failed; retrying...")
                    continue
                session["error"] = f"Agent error: {e}\n{traceback.format_exc()}"
                return session

        msg = response.choices[0].message # type: ignore
        messages.append(msg)

        if verbose:
            if msg.tool_calls:
                print(f"\n  [{step + 1}] LLM calls:", end=" ")
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    print(f"{tc.function.name}({json.dumps(args, default=str)})", end=" ")
                print()
            else:
                print(f"\n  [{step + 1}] LLM finished:", (msg.content or "")[:120], "...")

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            tool_name = tc.function.name

            if tool_name == "suggest_outfit":
                args["new_item"] = session.get("selected_item")
                args["wardrobe"] = session.get("wardrobe")
            elif tool_name == "create_fit_card":
                args["outfit"] = session.get("outfit_suggestion")
                args["new_item"] = session.get("selected_item")

            tool_fn = TOOL_FNS.get(tool_name)

            try:
                if tool_fn:
                    result = tool_fn(**args)
                else:
                    result = f"Unknown tool: {tool_name}"
            except Exception as e:
                result = f"Tool error: {e}"

            if verbose:
                summary = (
                    f"{len(result)} results" if isinstance(result, list)
                    else result[:100] if isinstance(result, str)
                    else str(result)[:100]
                )
                print(f"    → {tool_name} result:", summary)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result) if not isinstance(result, str) else result,
            })

            if tool_name == "search_listings":
                session["search_results"] = result
                if result and not session["selected_item"]:
                    session["selected_item"] = result[0]
            elif tool_name == "suggest_outfit":
                session["outfit_suggestion"] = result
            elif tool_name == "create_fit_card":
                session["fit_card"] = result

    # If no results were found and the LLM responded with text, set as error
    if (
        not session["search_results"]
        and not session["selected_item"]
        and not session["error"]
        and len(messages) >= 2
        and messages[-1].role == "assistant"
    ):
        session["error"] = messages[-1].content or "No results found."

    return session


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(
    query: str,
    wardrobe: dict,
    deterministic: bool = True,
    verbose: bool = False,
) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py
        deterministic: If True, uses a fixed sequence (parse → search →
                  select → suggest → create). If False, uses an LLM-driven
                  loop where the LLM decides which tool to call next via
                  native tool calling.

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.
    """
    session = _new_session(query, wardrobe)

    if deterministic:
        return _run_deterministic(session)
    else:
        return _run_agentic(session, verbose=verbose)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    deterministic = "--agentic" not in sys.argv
    verbose = "--verbose" in sys.argv
    mode = "deterministic" if deterministic else "agentic"

    print(f"=== {mode} mode — Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
        deterministic=deterministic,
        verbose=verbose,
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print(f"\n\n=== {mode} mode — No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
        deterministic=deterministic,
        verbose=verbose,
    )
    print(f"Error message: {session2['error']}")
