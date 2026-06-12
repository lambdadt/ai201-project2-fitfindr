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
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): ...
- `size` (str): ...
- `max_price` (float): ...

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): ...
- `wardrobe` (dict): ...

**What it returns:**
<!-- Describe the return value -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (...): ...

**What it returns:**
<!-- Describe the return value -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | |
| suggest_outfit | Wardrobe is empty | |
| create_fit_card | Outfit input is missing or incomplete | |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

**Milestone 4 — Planning loop and state management:**

---

## A Complete Interaction (Step by Step)

FitFindr takes a user's natural language query describing what clothing they want, parses out filters like size and max price, searches secondhand listings across platforms, and — using their existing wardrobe — generates specific outfit combinations and a shareable social-media caption. The agent loop presents the chat history (system prompt, user query, and all prior assistant/tool messages) and available tool definitions to the LLM. The **LLM decides** which tool to call next by reading back through the conversation to understand what's already happened — it doesn't rely on a separate state object for context. (A result dict returned by the inner loop carries the structured outputs — selected item, outfit suggestion, fit card, error — for the UI to display, but the LLM's reasoning comes from the chat history itself.) For example, if `search_listings` returns nothing, the LLM can skip `suggest_outfit` and `create_fit_card` entirely, setting an error message instead; if the wardrobe is empty, the LLM can still invoke `suggest_outfit` knowing that tool returns general styling advice for that case. Each tool handles its own failure mode gracefully (returning empty lists, fallback text, or error strings) rather than raising exceptions, so the LLM always has enough information to decide what to do next.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — LLM calls search_listings:** The inner loop starts with the chat history containing the system prompt, the user query, and the available tool definitions. The LLM sees the full context and decides to search listings first. It returns a tool call for `search_listings(description="vintage graphic tee", size=None, max_price=30)`. The tool loads the 40 mock listings, filters to items priced ≤ $30 whose title/description/style_tags overlap with "vintage graphic tee", scores them by keyword relevance, and returns a sorted list. The top match is a Depop listing: "Vintage Band Tee — Nirvana 1994 Tour" at $22, size M, condition good. The tool result is appended to the chat history and the loop continues.

**Step 2 — LLM calls suggest_outfit:** The LLM reviews the search results in the chat history and selects the top match as the best candidate. It decides the next logical step is an outfit suggestion, so it calls `suggest_outfit(new_item=top_listing, wardrobe=<user's wardrobe>)`. (The wardrobe was included in the initial user message or system prompt.) The wardrobe contains baggy jeans, chunky sneakers, and other items. The tool formats the wardrobe and the Nirvana tee into a prompt, calls the Groq API, and returns something like: *"Pair the Nirvana tee with your light-wash baggy jeans, the chunky white sneakers, and add a beanie for that effortless 90s grunge look."* The result is appended to the chat history.

**Step 3 — LLM calls create_fit_card:** The LLM sees the outfit suggestion in the chat history and decides to generate a shareable caption. It calls `create_fit_card(outfit=<outfit text>, new_item=top_listing)`. The tool prompts the Groq API for a 2–4 sentence Instagram/TikTok-style caption and returns: *"Found this 1994 Nirvana tour tee on Depop for $22 and immediately knew it belonged with my baggy jeans and chunky sneaks. Giving major 90s off-duty energy."* The result is appended to the chat history.

**Step 4 — LLM signals done:** With all three tools called and results in the chat history, the LLM returns a plain text response with no tool_calls. The inner loop exits. The returned result dict now contains: `selected_item` (the Nirvana tee), `outfit_suggestion` (the outfit text), and `fit_card` (the caption).

**Failure path (no search results):** If `search_listings` had returned `[]`, the LLM would see the empty list in the chat history, recognize there's nothing to build an outfit from, and set `result["error"]` to a message like "No listings matched your query — try different keywords or a higher price ceiling." It would then return a text response with no further tool calls. The inner loop exits without `suggest_outfit` or `create_fit_card` ever being called.

**Final output to user:** The Gradio UI displays three panels: the listing details in the first panel, the outfit suggestion in the second, and the fit card in the third. If the error path was taken, only the first panel shows the error message.
