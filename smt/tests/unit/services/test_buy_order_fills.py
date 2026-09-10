from decimal import Decimal

from smt.services.steam import _paid_from_purchases


class TestPaidFromPurchases:
    def test_nothing_bought_yet(self):
        assert _paid_from_purchases([]) is None

    def test_a_single_fill_as_steam_reports_it(self):
        purchases = [
            {
                "listingid": "615459033302831321",
                "price_subtotal": 139,
                "price_fee": 170,
                "price_total": 309,
                "assetid": "17523581047",
            }
        ]

        assert _paid_from_purchases(purchases) == Decimal("3.09")

    def test_several_fills_add_up(self):
        purchases = [{"price_total": 309}, {"price_total": 315}]

        assert _paid_from_purchases(purchases) == Decimal("6.24")

    def test_the_total_can_be_rebuilt_from_its_parts(self):
        purchases = [{"price_subtotal": 139, "price_fee": 170}]

        assert _paid_from_purchases(purchases) == Decimal("3.09")

    def test_junk_entries_are_ignored(self):
        purchases = ["nonsense", {"listingid": "1"}, {"price_total": 309}]

        assert _paid_from_purchases(purchases) == Decimal("3.09")
