from unittest.mock import patch, MagicMock

from tools import search_listings, suggest_outfit, create_fit_card


# ── search_listings ──────────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=50)
    assert len(results) > 0
    assert all(item["price"] <= 50 for item in results)


def test_search_size_filter_case_insensitive():
    results = search_listings("tee", size="m", max_price=None)
    assert len(results) > 0
    for item in results:
        assert "m" in item["size"].lower()


def test_search_sorted_by_relevance():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert len(results) >= 2
    scores = []
    keywords = "vintage graphic tee".lower().split()
    for listing in results:
        searchable = " ".join([
            listing["title"],
            listing["description"],
            " ".join(listing.get("style_tags", [])),
        ]).lower()
        score = sum(1 for kw in keywords if kw in searchable)
        scores.append(score)
    assert scores == sorted(scores, reverse=True), "Results not sorted by relevance"


# ── suggest_outfit ──────────────────────────────────────────────────────────────

def test_suggest_outfit_populated_wardrobe():
    new_item = {
        "title": "Vintage Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage", "grunge", "band"],
        "brand": None,
        "price": 22.00,
        "platform": "depop",
    }
    wardrobe = {
        "items": [
            {"name": "Baggy Jeans", "category": "bottoms", "color": "blue", "style": "streetwear"},
            {"name": "Chunky Sneakers", "category": "shoes", "color": "white", "style": "streetwear"},
        ],
    }

    mock_msg = MagicMock()
    mock_msg.content = "Pair the Vintage Band Tee with your Baggy Jeans and Chunky Sneakers."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices = [MagicMock(message=mock_msg)]

    with patch("tools._get_groq_client", return_value=mock_client):
        result = suggest_outfit(new_item, wardrobe)

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Vintage Band Tee" in result


def test_suggest_outfit_empty_wardrobe():
    new_item = {
        "title": "Vintage Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage", "grunge", "band"],
        "brand": None,
        "price": 22.00,
        "platform": "depop",
    }
    wardrobe = {"items": []}

    mock_msg = MagicMock()
    mock_msg.content = "Pair the Vintage Band Tee with high-waisted jeans and chunky sneakers."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices = [MagicMock(message=mock_msg)]

    with patch("tools._get_groq_client", return_value=mock_client):
        result = suggest_outfit(new_item, wardrobe)

    assert isinstance(result, str)
    assert len(result) > 0


def test_suggest_outfit_api_failure():
    new_item = {
        "title": "Vintage Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage"],
        "brand": None,
        "price": 22.00,
        "platform": "depop",
    }
    wardrobe = {"items": []}

    with patch("tools._get_groq_client") as mock_get_client:
        mock_get_client.side_effect = RuntimeError("API timeout")
        result = suggest_outfit(new_item, wardrobe)

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Error details" in result
    assert "API timeout" in result


# ── create_fit_card ─────────────────────────────────────────────────────────────

def test_create_fit_card_returns_string():
    outfit = "Pair the Vintage Band Tee with your Baggy Jeans and Chunky Sneakers."
    new_item = {
        "title": "Vintage Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage", "grunge", "band"],
        "brand": None,
        "price": 22.00,
        "platform": "depop",
    }

    mock_msg = MagicMock()
    mock_msg.content = "Found this Vintage Band Tee on Depop for $22. Styled it with my baggy jeans and chunky sneaks for that effortless grunge vibe. Thrift win."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices = [MagicMock(message=mock_msg)]

    with patch("tools._get_groq_client", return_value=mock_client):
        result = create_fit_card(outfit, new_item)

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Vintage Band Tee" in result


def test_create_fit_card_empty_outfit():
    new_item = {
        "title": "Vintage Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage"],
        "brand": None,
        "price": 22.00,
        "platform": "depop",
    }

    result = create_fit_card("", new_item)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "Unable to generate" in result


def test_create_fit_card_whitespace_outfit():
    new_item = {
        "title": "Vintage Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage"],
        "brand": None,
        "price": 22.00,
        "platform": "depop",
    }

    result = create_fit_card("   ", new_item)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "Unable to generate" in result


def test_create_fit_card_api_failure():
    outfit = "Pair with baggy jeans."
    new_item = {
        "title": "Vintage Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage"],
        "brand": None,
        "price": 22.00,
        "platform": "depop",
    }

    with patch("tools._get_groq_client") as mock_get_client:
        mock_get_client.side_effect = RuntimeError("API timeout")
        result = create_fit_card(outfit, new_item)

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Error generating" in result
    assert "API timeout" in result
