"""Reading a printed price from the PDF text layer (used to pair medicine symbols and photos with cards)."""

import pytest

from flyer_agent.adapters.pdf import read_price


@pytest.mark.parametrize(("text", "price"), [
    ("€12,99 €14,2", "12,99"),
    ("€9,69€12,9", "9,69"),
    ("€12,9925%", "12,99"),
    ("€1.299,00", "1.299,00"),
    ("€ 4,09", "4,09"),
])
def test_two_decimal_prices(text, price):
    assert read_price(text) == price


@pytest.mark.parametrize(("text", "price"), [
    ("€12,9\r\n24%", "12,90"),  # February 2026: old price, discount on the next line (was read as "12,92")
    ("€12,5\r\n24%", "12,50"),
    ("€18,9\n24%", "18,90"),
    ("€14,2", "14,20"),
])
def test_one_decimal_price_is_not_joined_to_the_next_line(text, price):
    assert read_price(text) == price


def test_no_price():
    assert read_price("€ offerta") is None
