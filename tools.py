"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import traceback

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()
    keywords = description.lower().split()

    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    if size is not None:
        size_lower = size.lower()
        listings = [l for l in listings if size_lower in l["size"].lower()]

    scored = []
    for listing in listings:
        searchable = " ".join([
            listing["title"],
            listing["description"],
            " ".join(listing["style_tags"]),
        ]).lower()

        score = sum(1 for kw in keywords if kw in searchable)

        if score > 0:
            scored.append((score, listing))

    scored.sort(key=lambda x: (-x[0], x[1]["price"]))

    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.
    """
    item_details = (
        f"Item: {new_item['title']}\n"
        f"Category: {new_item['category']}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n"
        f"Brand: {new_item.get('brand') or 'unknown'}\n"
        f"Price: ${new_item['price']}\n"
        f"Platform: {new_item['platform']}"
    )

    wardrobe_items = wardrobe.get("items", [])
    if not wardrobe_items:
        prompt = (
            f"The user is considering buying this item:\n\n{item_details}\n\n"
            f"Their wardrobe is empty. Suggest 1–2 outfit ideas for how to style "
            f"this piece. Recommend specific types of items (e.g. 'high-waisted "
            f"jeans', 'chunky sneakers', 'a cropped jacket') that would pair well. "
            f"Describe the overall vibe each outfit creates."
        )
    else:
        wardrobe_text = "\n".join(
            f"- {item['name']} ({item['category']}, {item['color']}, {item['style']})"
            for item in wardrobe_items
        )
        prompt = (
            f"The user is considering buying this item:\n\n{item_details}\n\n"
            f"Their current wardrobe:\n{wardrobe_text}\n\n"
            f"Suggest 1–2 complete outfits using the new item paired with specific "
            f"pieces from the wardrobe above. Name the wardrobe pieces explicitly. "
            f"For each outfit, describe the overall vibe."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a fashion stylist. Suggest outfits in natural, "
                        "conversational language. Keep suggestions concise — "
                        "1–2 outfits, 2–4 sentences each. Do not use markdown formatting."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or "No suggestion was made"
    except Exception as e:
        stack_trace_string = traceback.format_exc()
        return (
            f"Unable to generate outfit suggestions right now. "
            #f"Here's a quick idea: the {new_item['title']} works well as a "
            #f"statement piece — build the rest of your outfit around neutral basics.\n\n"
            + f"Error details: {stack_trace_string}"
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)
    """
    if not outfit or not outfit.strip():
        return (
            "Unable to generate a fit card — no outfit was provided. "
            "Try running the outfit suggestion step first."
        )

    item_details = (
        f"Item: {new_item['title']}\n"
        f"Price: ${new_item['price']}\n"
        f"Platform: {new_item['platform']}\n"
        f"Brand: {new_item.get('brand') or 'unknown'}\n"
        f"Category: {new_item['category']}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}"
    )

    prompt = (
        f"Write a short, casual Instagram/TikTok caption for this thrifted find.\n\n"
        f"{item_details}\n\n"
        f"Outfit suggestion:\n{outfit.strip()}\n\n"
        f"Guidelines:\n"
        f"- 2–4 sentences, casual and authentic like a real OOTD post\n"
        f"- Mention the item name, price ($22), and platform (Depop) naturally, once each\n"
        f"- Capture the outfit vibe in specific, evocative terms\n"
        f"- Sound like something a real person would post, not a product description\n"
        f"- Use informal language, feel free to use lowercase, slang, or emojis sparingly"
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.9,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a fashion content creator. Write short, authentic "
                        "social media captions. Use casual language, lowercase is fine, "
                        "sound like a real person posting an outfit-of-the-day."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        stack_trace_string = traceback.format_exc()
        return f"Error generating fit card: {stack_trace_string}"
