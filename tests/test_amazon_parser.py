from __future__ import annotations

from pathlib import Path

from src.amazon_probe import detect_amazon_block, parse_amazon_response


FIXTURES = Path(__file__).parent / "fixtures"


def test_amazon_html_parsing() -> None:
    html = (FIXTURES / "amazon_review.html").read_text(encoding="utf-8")

    reviews = parse_amazon_response(html, source_url="https://www.amazon.com/product-reviews/B000000001/")

    assert len(reviews) == 1
    review = reviews[0]
    assert review.source == "amazon"
    assert review.item_id == "B000000001"
    assert review.review_id == "R1ABC"
    assert review.review_title == "Solid product"
    assert review.rating == 4.0
    assert review.verified_purchase is True
    assert review.helpful_votes == 2


def test_amazon_json_wrapped_html_parsing() -> None:
    wrapped = (FIXTURES / "amazon_wrapped.json").read_text(encoding="utf-8")

    reviews = parse_amazon_response(wrapped)

    assert len(reviews) == 1
    assert reviews[0].review_id == "R2DEF"
    assert reviews[0].review_text == "Wrapped body text."


def test_amazon_ajax_delimited_response_parsing() -> None:
    ajax = (
        '["append", "#cm_cr-review_list", '
        '"<ul><li id=\\"R4AJAX\\" data-hook=\\"review\\"><span class=\\"a-profile-name\\">Ajax Reviewer</span>'
        '<a data-hook=\\"review-title\\"><span>Ajax title</span></a>'
        '<i data-hook=\\"review-star-rating\\"><span>3.0 out of 5 stars</span></i>'
        '<span data-hook=\\"review-body\\"><span>Ajax body.</span></span></li></ul>"]'
        "&&&"
        '["update", "#cm_cr-pagination_bar", "<div>next</div>"]'
    )

    reviews = parse_amazon_response(ajax)

    assert len(reviews) == 1
    assert reviews[0].review_id == "R4AJAX"
    assert reviews[0].rating == 3.0
    assert reviews[0].helpful_votes == 0


def test_amazon_ajax_asin_extraction_from_response_links() -> None:
    ajax = (
        '["append", "#cm_cr-review_list", '
        '"<ul><li id=\\"R5ASIN\\" data-hook=\\"review\\">'
        '<a data-hook=\\"format-strip\\" href=\\"/portal/customer-reviews/B00TTD9BRC/ref=cm_cr_test\\">Size</a>'
        '<a data-hook=\\"review-title\\"><span>Asin title</span></a>'
        '<span data-hook=\\"review-body\\"><span>Asin body.</span></span></li></ul>"]'
    )

    reviews = parse_amazon_response(ajax)

    assert reviews[0].item_id == "B00TTD9BRC"


def test_amazon_block_page_detection() -> None:
    assert detect_amazon_block("Sorry, we just need to make sure you're not a robot") is True
    assert detect_amazon_block("Access Denied", 403) is True


def test_amazon_missing_fields_are_none() -> None:
    html = '<div id="customer_review-R3" data-hook="review"></div>'

    review = parse_amazon_response(html)[0]

    assert review.review_id == "R3"
    assert review.review_text is None
    assert review.rating is None
