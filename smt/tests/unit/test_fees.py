from decimal import Decimal

import pytest

from smt.utils.steam import FeeSchedule, calculate_fees, get_fee_schedule, net_received, set_fee_schedule


CURRENT = FeeSchedule(minimum=86)
BEFORE_2025 = FeeSchedule(minimum=1)


@pytest.fixture(autouse=True)
def restore_schedule():
    original = get_fee_schedule()
    yield
    set_fee_schedule(original)


class TestAgainstRealTransactions:
    @pytest.mark.parametrize(
        "gross, net",
        [(612, 440), (955, 783), (1736, 1500)],
        ids=["minimum on both fees", "minimum on both fees again", "publisher fee goes proportional"],
    )
    def test_todays_listings(self, gross, net):
        """Prices Steam actually set for listings made on 2026-09-06."""
        assert calculate_fees(gross, CURRENT)["net_received"] == net

    @pytest.mark.parametrize("gross, net", [(5, 3), (16, 14), (733, 639), (13400, 11653)])
    def test_history_from_before_the_minimum_rose(self, gross, net):
        assert calculate_fees(gross, BEFORE_2025)["net_received"] == net


class TestTheMinimum:
    def test_it_applies_to_both_fees(self):
        fees = calculate_fees(612, CURRENT)

        assert fees["steam_fee"] == 86
        assert fees["publisher_fee"] == 86

    def test_it_dominates_cheap_sales(self):
        """Below a net of 8.60 the fee is flat, so the cheaper the item the worse the ratio."""
        cheap = calculate_fees(272, CURRENT)
        dearer = calculate_fees(672, CURRENT)

        assert cheap["total_fees"] == dearer["total_fees"] == 172
        assert cheap["net_received"] == 100
        assert dearer["net_received"] == 500

    def test_it_stops_mattering_once_the_percentage_is_larger(self):
        fees = calculate_fees(11500, CURRENT)

        assert fees["steam_fee"] == 500
        assert fees["publisher_fee"] == 1000
        assert fees["net_received"] == 10000


class TestTheModuleSchedule:
    def test_net_received_follows_the_current_schedule(self):
        set_fee_schedule(CURRENT)
        assert net_received(Decimal("6.12")) == Decimal("4.40")

        set_fee_schedule(BEFORE_2025)
        assert net_received(Decimal("6.12")) == Decimal("5.33")

    def test_calculate_fees_defaults_to_it(self):
        set_fee_schedule(CURRENT)

        assert calculate_fees(612) == calculate_fees(612, CURRENT)
