# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40-item mock listings JSON dataset for secondhand clothing items whose title, description, or style_tags match the user's search terms. Scores each candidate by keyword overlap with the description string, drops any listing with score 0, and returns matches sorted best-first. Also filters by size (case-insensitive substring match, e.g. "M" matches "S/M") and max_price (≤ ceiling) when provided.

**Input parameters:**
- `description` (str): Free-text keywords describing what the user wants (e.g. "vintage graphic tee"). The tool splits this into tokens and checks overlap against each listing's title, description, and style_tags fields.
- `size` (str | None): A size string to filter by (e.g. "M", "8", "S"). Matching is case-insensitive and uses substring containment so "M" finds "S/M" or "M/L". Pass None to skip size filtering.
- `max_price` (float | None): An inclusive price ceiling. Listings with price > max_price are dropped. Pass None to skip price filtering.

**What it returns:**
A `list[dict]` of matching listing objects, sorted by relevance score descending. Each dict has the keys: `id`, `title`, `description`, `category` (one of "tops", "bottoms", "outerwear", "shoes", "accessories"), `style_tags` (list[str]), `size`, `condition` ("excellent"/"good"/"fair"), `price` (float), `colors` (list[str]), `brand` (str or null), `platform` ("depop"/"thredUp"/"poshmark").

**What happens if it fails or returns nothing:**
Returns `[]` — an empty list, not an exception. The LLM reads the empty result from the chat history and sets `result["error"]` to a message like: *"No listings matched 'vintage graphic tee' under $30. Try broader keywords, drop the size filter, or raise your price ceiling to $50."* The inner loop returns early without calling `suggest_outfit` or `create_fit_card`. The error message is displayed in the first Gradio panel.

---

### Tool 2: suggest_outfit

**What it does:**
Takes a selected thrifted listing and the user's wardrobe, then calls the Groq LLM (`llama-3.3-70b-versatile`) to generate 1–2 complete outfit suggestions as free-form text. The LLM sees the new item's details (title, category, colors, style_tags, brand) and every wardrobe item's details (name, category, color, style), and responds with specific outfit pairings using named pieces from the wardrobe alongside the new item.

**Input parameters:**
- `new_item` (dict): A full listing dict — the same format returned by `search_listings`. Key fields used by the LLM: `title`, `category`, `colors`, `style_tags`, `brand`, `price`, `platform`.
- `wardrobe` (dict): A dict with an `"items"` key containing a list of wardrobe item dicts. Each wardrobe item has keys: `name`, `category`, `color`, `style`. The wardrobe may be empty (`"items": []`).

**What it returns:**
A `str` — a non-empty string with 1–2 outfit suggestions in natural language. When the wardrobe has items, the text names specific pieces: *"Pair the Nirvana tee with your light-wash baggy jeans, the chunky white sneakers, and add a beanie for that effortless 90s grunge look. For a second option, layer it under your vintage denim jacket with the black cargos."* When the wardrobe is empty, the text offers general styling advice: *"You don't have any wardrobe items saved yet. The Nirvana tee would pair well with high-waisted jeans, chunky sneakers, and a cropped jacket for a casual streetwear vibe. Try it tucked into a flowy midi skirt for a dressed-up take."*

**What happens if it fails or returns nothing:**
Never returns an empty string. If wardrobe is empty, returns general styling advice instead of specific pairings. If the Groq API call fails (network error, rate limit), the tool catches the exception and returns a fallback string: *"Unable to generate outfit suggestions right now. Here's a quick idea: [new_item.title] works well as a statement piece — build the rest of your outfit around neutral basics."* The tool does not raise exceptions for API errors.

---

### Tool 3: create_fit_card

**What it does:**
Generates a 2–4 sentence Instagram/TikTok-style caption for a thrifted find, using the outfit combinations from `suggest_outfit` and the selected item's details. Calls the Groq LLM with a higher temperature (0.9–1.0) so captions vary across inputs. The caption should feel casual and authentic — like a real OOTD post — mention the item name, price, and platform naturally (each once), and capture the outfit vibe in specific terms.

**Input parameters:**
- `outfits` (list[list[dict]]): The outfit suggestions from `suggest_outfit`. Each inner list is one outfit: `[new_item, ...wardrobe_items]`. Used to ground the caption in what the user would actually wear with the item.
- `new_item` (dict): The same listing dict — used to extract the item's title, price, brand, and platform for the caption.

**What it returns:**
A `str` — a 2–4 sentence caption. Example: *"Found this 1994 Nirvana tour tee on Depop for $22 and it's already living rent-free in my head. Styled it with my baggy jeans and chunky sneaks for that effortless 90s grunge energy. Sometimes the best fits come from 1am scrolling."*

When `outfits` is `[[new_item]]` (empty wardrobe), the caption focuses on the item itself: *"Just scored this Nirvana tee on Depop for $22. Giving major 90s band-tee energy — would look sick with some high-waisted denim and beat-up Converse. Thrift win."*

**What happens if it fails or returns nothing:**
If `outfits` is empty (`[]`), returns the error string: *"Unable to generate a fit card — no outfits were provided. Try running the outfit suggestion step first."* If the Groq API call fails, returns a fallback caption: *"Just thrifted this [new_item.title] on [new_item.platform] for $[new_item.price]. Too good to pass up. #thrifted #secondhandfinds"*. The tool does not raise exceptions.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**

The agent uses **two nested loops**:

**Outer loop (chat turn):** Owned by `handle_query()` in `app.py` (or `run_agent()` in `agent.py`). Maintains the `messages` list across turns. On each user message: appends `{"role": "user", "content": query}`, calls the inner loop, reads the returned result dict to populate Gradio panels, and keeps the compressed `messages` for the next turn.

**Inner loop (`run_tool_phase()`):** Takes the current `messages` list, calls Groq with native `tools=[...]` and `tool_choice="auto"`, and loops until the LLM returns a plain text response (no `tool_calls`). The LLM decides what to call by reading the full chat history — it sees prior tool calls and their results inline. This is not a fixed pipeline; the LLM adapts to what it receives.

**Inner loop branching logic (step by step):**

1. Send `messages` (system prompt + user query + any prior assistant/tool messages) and all available tool definitions to Groq's `chat.completions.create` with `tool_choice="auto"`.

2. If the response message has **no `tool_calls`**: the LLM is done for this turn. Compress old tool results in `messages`, return `(messages, result)` where `result` contains whatever the tools have produced so far (selected_item, outfit_suggestion, fit_card, error).

3. If the response has **`tool_calls`**: append the assistant message to `messages`, then execute each requested tool call:
   - **`search_listings`**: Run the tool with the LLM-supplied arguments. If it returns `[]` (no matches), set `result["error"]` to a message like *"No listings matched 'vintage graphic tee' under $30. Try broadening your keywords or raising your price ceiling."* Return early — skip any remaining tool calls in this response and do not loop again.
   - **`suggest_outfit`**: Run with the LLM-supplied arguments (the LLM should pass the top listing from prior search results as `new_item` and the wardrobe as `wardrobe`). Update `result["outfit_suggestion"]` with the returned string. Even if wardrobe is empty, the tool returns a non-empty styling advice string — the LLM can still proceed.
   - **`create_fit_card`**: Run with the LLM-supplied arguments (the outfit string from `suggest_outfit` as `outfit`, and the selected listing as `new_item`). Update `result["fit_card"]` with the returned caption. If outfit was empty, the tool returns an error string — the LLM can relay that to the user.
   - Append each tool result to `messages` as `{"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)}`.
   - Update `result` dict fields as tools execute: `selected_item` from the first search_listings call, `outfit_suggestion` from suggest_outfit, `fit_card` from create_fit_card.

4. Loop back to step 1 with the updated `messages`. The LLM now sees the tool results appended to the history and decides whether to call more tools or respond with text.

5. **Safety valve:** The loop exits after `max_steps` iterations (default 20) even if the LLM hasn't finished, returning whatever `result` has accumulated plus a fallback error.

**Key branches the LLM can take:**
- If `search_listings` returns an empty list → the LLM should set `result["error"]` or return a text response telling the user nothing was found. It should NOT call `suggest_outfit` or `create_fit_card`.
- If `search_listings` returns results → the LLM can call `suggest_outfit` with the top result.
- If `suggest_outfit` returns styling advice for an empty wardrobe → the LLM can still call `create_fit_card` — the tool handles this case and produces a caption focused on the item.
- The LLM can call **multiple tools in a single response** if it's confident, or call them one at a time. The loop supports either pattern.

---

## State Management

**How does information from one tool get passed to the next?**

Two parallel state tracks serve different consumers:

**1. Chat history (`messages` list) — for the LLM:**

Every tool call and its result are appended to `messages` in order. The LLM reads the entire history to understand what's happened. For example, after `search_listings` returns 3 listings, those results appear as a `{"role": "tool", "content": "[...]"}` message. When the LLM next decides to call `suggest_outfit`, it reads back through the history to find the search results and picks the top listing to pass as `new_item`. No separate state object is needed — the conversation record is self-contained.

After the inner loop finishes, old tool results are **compressed** to one-line summaries:
```
Before: {"role": "tool", "content": "[3 full listing dicts with all fields...]"}
After:  {"role": "tool", "content": "[search_listings returned 3 matches: 'Nirvana Tee' $22, 'Band Tee' $18, 'Retro Tee' $28]"}
```
The latest 1–2 tool results stay in full so details are accessible. Summaries are immutable once written, keeping the prefix stable for KV-cache reuse across future chat turns.

**2. Result dict — for the caller (app.py):**

The inner loop builds and returns a `result` dict that the outer loop reads to populate the three Gradio panels:

```python
result = {
    "selected_item": dict | None,     # top listing from search_listings
    "outfit_suggestion": str | None,  # outfit string from suggest_outfit
    "fit_card": str | None,           # caption from create_fit_card
    "error": str | None,              # set on early termination
}
```

The `result` dict is created fresh inside `run_tool_phase()` and returned alongside the compressed `messages`. `app.py` checks `result["error"]` first — if set, it displays the error in the first panel. Otherwise, it reads `selected_item`, `outfit_suggestion`, and `fit_card` for the three output panels.

**How the wardrobe flows:** The wardrobe dict is part of the initial system prompt or user message — the LLM sees it in the chat history at the start of a turn. When the LLM calls `suggest_outfit`, it passes items from that wardrobe as the `wardrobe` argument. The wardrobe does not change within a turn, so it doesn't need separate state tracking.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Sets `result["error"]` to *"No listings matched '[description]' under $[max_price]. Try broader keywords (e.g. 'graphic tee' instead of 'vintage Nirvana tour tee'), dropping the size filter, or raising your price ceiling."* Returns early — does not call `suggest_outfit` or `create_fit_card`. The error message is displayed in the first Gradio panel; the other two panels remain empty. |
| suggest_outfit | Wardrobe is empty | Returns general styling advice instead of specific pairings — a non-empty string like *"You don't have any wardrobe items saved yet. The [item] would pair well with..."*. The LLM can still call `create_fit_card`, which handles this by generating a caption focused on the item itself. |
| suggest_outfit | Groq API call fails (network error, rate limit) | Catches the exception, logs it, and returns a fallback string: *"Unable to generate outfit suggestions right now. Here's a quick idea: [item] works well as a statement piece — build the rest of your outfit around neutral basics."* The LLM still gets a non-empty string and can proceed to `create_fit_card`. |
| create_fit_card | Outfit input is empty or whitespace-only | Returns the string *"Unable to generate a fit card — no outfit was provided. Try running the outfit suggestion step first."* The LLM relays this to the user. |
| create_fit_card | Groq API call fails | Returns a fallback caption: *"Just thrifted this [title] on [platform] for $[price]. Too good to pass up. #thrifted #secondhandfinds"*. The user still sees a caption — it's generic but functional. |
| Groq client init | `GROQ_API_KEY` not set | `_get_groq_client()` raises `ValueError` at startup. `app.py` should catch this and display a setup message: *"GROQ_API_KEY not found. Add it to a .env file in the project root and restart."* |

---

## Architecture

```mermaid
flowchart TD
    U[User] -->|natural language query| OL[Outer Loop\nhandle_query / run_agent]
    OL -->|appends user msg| IL[Inner Loop\nrun_tool_phase]

    subgraph IL[Inner Loop — Tool Phase]
        direction TB
        MSG[messages list\nsystem + user + history] --> GROQ[Groq API\nllama-3.3-70b-versatile\ntools=tool_defs, tool_choice=auto]
        GROQ -->|no tool_calls| DONE[Done — return text]
        GROQ -->|tool_calls| TC{Which tool?}

        TC -->|search_listings| SL[search_listings\nmatches listings dataset]
        SL -->|results: list[dict]| CHK{results empty?}
        CHK -->|yes| ERR[Set result.error\nReturn early]
        CHK -->|no| MSG2[Append tool result\nto messages]

        TC -->|suggest_outfit| SO[suggest_outfit\nLLM generates outfit ideas]
        SO -->|suggestion: str| MSG2

        TC -->|create_fit_card| CFC[create_fit_card\nLLM generates caption]
        CFC -->|fit_card: str| MSG2

        MSG2 --> GROQ
    end

    DONE --> COMPRESS[Compress old tool results\nto one-line summaries]
    COMPRESS --> RESULT[Return messages, result dict]
    ERR --> RESULT

    RESULT --> OL
    OL -->|selected_item, outfit, fit_card| UI[Gradio Panels\n🛍️ listing 👗 outfit ✨ fit card]
    OL -->|saves compressed messages| OL
```

**Data flow summary:**
- User query enters the outer loop → appended to `messages`
- Inner loop sends `messages` + tool definitions to Groq → Groq returns tool_calls or text
- Tool results are appended to `messages` and recorded in the `result` dict
- The inner loop repeats until Groq returns plain text; old tool results are compressed
- The outer loop reads `result` to populate the three Gradio panels, keeps compressed `messages` for the next turn
- If `search_listings` returns `[]`: the error branch sets `result["error"]` and returns immediately — `suggest_outfit` and `create_fit_card` are never called

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

*Tool 1 — search_listings:* I'll give Claude the Tool 1 block from planning.md (inputs, return value, failure mode, listing field descriptions) and the Architecture diagram. I'll ask it to implement `search_listings()` in `tools.py` using `load_listings()` from `utils/data_loader.py`, with keyword scoring via token overlap against `title` + `description` + `style_tags`, case-insensitive substring matching for size, and a `max_price` filter. Before trusting the output, I'll verify: (a) the function filters by all three parameters, (b) it returns `[]` (not an exception) when nothing matches, (c) it sorts by score descending, and (d) it drops score-0 items. Then I'll test it with 3 queries: a broad match ("graphic tee"), a narrow no-match ("designer ballgown size XXS under $5"), and a price-only filter ("jacket under $10").

*Tool 2 — suggest_outfit:* I'll give Claude the Tool 2 block from planning.md (inputs, return `str`, empty-wardrobe fallback to general styling advice, Groq API error fallback string) and the tools.py scaffold with `_get_groq_client()`. I'll ask it to build a prompt that includes the new item details and every wardrobe item's name/category/color/style, and return the LLM's response directly as a string. Before trusting: (a) with a populated wardrobe, it returns a non-empty string naming specific wardrobe pieces, (b) with an empty wardrobe, it returns general styling advice (not an empty string), (c) the Groq call uses the existing `_get_groq_client()` helper. I'll mock `_get_groq_client()` in tests to avoid real API calls.

*Tool 3 — create_fit_card:* I'll give Claude the Tool 3 block from planning.md (inputs: `outfit` string and `new_item` dict, higher-temperature LLM call, empty-string guard, API failure fallback) and the Architecture diagram. I'll ask it to format the outfit text and item details into a prompt that the LLM can caption naturally. Before trusting: (a) with a valid outfit string it returns a 2–4 sentence caption mentioning the item name/price/platform, (b) with an empty or whitespace-only outfit string it returns the error string, (c) with general styling advice text it still produces a caption focused on the item.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the entire Planning Loop, State Management, and Architecture sections of planning.md, plus the Architecture diagram (Mermaid). I'll ask it to implement `run_tool_phase()` in `agent.py` as the inner loop: takes `messages`, calls Groq with `tools=[...]`, loops on `tool_calls`, builds the `result` dict, compresses old tool results, and returns `(messages, result)`. I'll also ask it to update `handle_query()` in `app.py` to call `run_tool_phase()` and read the `result` dict for the three Gradio panels. Before trusting: (a) the inner loop exits correctly when no `tool_calls` remain, (b) empty search results trigger early return with `result["error"]` set, (c) old tool results are compressed to one-liners after the loop, (d) `app.py` populates all three panels from the `result` dict. I'll test with a full happy-path query and the no-results query from Milestone 3.

---

## A Complete Interaction (Step by Step)

FitFindr takes a user's natural language query describing what clothing they want, parses out filters like size and max price, searches secondhand listings across platforms, and — using their existing wardrobe — generates specific outfit combinations and a shareable social-media caption. The agent loop presents the chat history (system prompt, user query, and all prior assistant/tool messages) and available tool definitions to the LLM. The **LLM decides** which tool to call next by reading back through the conversation to understand what's already happened — it doesn't rely on a separate state object for context. (A result dict returned by the inner loop carries the structured outputs — selected item, outfit suggestion, fit card, error — for the UI to display, but the LLM's reasoning comes from the chat history itself.) For example, if `search_listings` returns nothing, the LLM can skip `suggest_outfit` and `create_fit_card` entirely, setting an error message instead; if the wardrobe is empty, the LLM can still invoke `suggest_outfit` knowing that tool returns general styling advice for that case. Each tool handles its own failure mode gracefully (returning empty lists, fallback text, or error strings) rather than raising exceptions, so the LLM always has enough information to decide what to do next.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — LLM calls search_listings:** The inner loop starts with the chat history containing the system prompt, the user query, and the available tool definitions. The LLM sees the full context and decides to search listings first. It returns a tool call for `search_listings(description="vintage graphic tee", size=None, max_price=30)`. The tool loads the 40 mock listings, filters to items priced ≤ $30 whose title/description/style_tags overlap with "vintage graphic tee", scores them by keyword relevance, and returns a sorted list. The top match is a Depop listing: "Vintage Band Tee — Nirvana 1994 Tour" at $22, size M, condition good. The tool result is appended to the chat history and the loop continues.

**Step 2 — LLM calls suggest_outfit:** The LLM reviews the search results in the chat history and selects the top match as the best candidate. It calls `suggest_outfit(new_item=top_listing, wardrobe=<user's wardrobe>)`. The tool formats the wardrobe and the Nirvana tee into a prompt, calls the Groq API, and asks the LLM to suggest outfit pairings using named wardrobe pieces. The tool returns a string like: *"Pair the Nirvana tee with your light-wash baggy jeans, the chunky white sneakers, and add a beanie for that effortless 90s grunge look. For a second option, layer it under your vintage denim jacket with the black cargos."* The result is appended to the chat history and recorded in `result["outfit_suggestion"]`.

**Step 3 — LLM calls create_fit_card:** The LLM sees the outfit suggestion in the chat history and decides to generate a shareable caption. It calls `create_fit_card(outfit=<suggestion string>, new_item=top_listing)`. The tool formats the outfit text and item details into a prompt, calls the Groq API at higher temperature, and returns: *"Found this 1994 Nirvana tour tee on Depop for $22 and immediately knew it belonged with my baggy jeans and chunky sneaks. Giving major 90s off-duty energy. Sometimes the best fits come from scrolling at 1am."* The result is appended to the chat history and recorded in `result["fit_card"]`.

**Step 4 — LLM signals done:** With all three tools called and results in the chat history, the LLM returns a plain text response with no tool_calls. The inner loop exits. The returned result dict now contains: `selected_item` (the Nirvana tee dict), `outfit_suggestion` (the outfit text string), and `fit_card` (the caption string).

**Failure path (no search results):** If `search_listings` had returned `[]`, the LLM would see the empty list in the chat history, recognize there's nothing to build an outfit from, and set `result["error"]` to a message like "No listings matched your query — try different keywords or a higher price ceiling." It would then return a text response with no further tool calls. The inner loop exits without `suggest_outfit` or `create_fit_card` ever being called.

**Final output to user:** The Gradio UI displays three panels: the listing details in the first panel, the outfit suggestion in the second, and the fit card in the third. If the error path was taken, only the first panel shows the error message.
