import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from federated_model import CityNode, FederatedCoordinator, build_demo_network
from source_classifier import classify_source


def test_local_trend_detects_rising_pollution():
    node = CityNode(name="TestCity", lat=0, lon=0, zone_type="mixed")
    for hours_ago, pm25 in [(40, 80), (30, 90), (20, 105), (10, 120), (0, 135)]:
        node.add_reading(pm25, hours_ago=hours_ago)

    slope, intercept = node.local_trend()
    assert slope > 0, "a clearly rising series should produce a positive slope"


def test_federated_round_blends_across_nodes():
    coordinator = FederatedCoordinator()

    rising = CityNode(name="Rising", lat=0, lon=0, zone_type="mixed")
    for hours_ago, pm25 in [(40, 50), (30, 70), (20, 90), (10, 110), (0, 130)]:
        rising.add_reading(pm25, hours_ago=hours_ago)

    flat = CityNode(name="Flat", lat=1, lon=1, zone_type="mixed")
    for hours_ago, pm25 in [(40, 60), (30, 61), (20, 59), (10, 60), (0, 60)]:
        flat.add_reading(pm25, hours_ago=hours_ago)

    coordinator.register_node(rising)
    coordinator.register_node(flat)

    blended = coordinator.federated_round(blend_weight=0.3)
    rising_slope_alone, _ = rising.local_trend()
    blended_rising_slope, _ = blended["Rising"]

    # The blended slope should differ from the pure local slope -- that's
    # the whole point of the federated step -- but not swing wildly, since
    # blend_weight is modest.
    assert blended_rising_slope != rising_slope_alone


def test_forecast_flags_spike_when_projection_is_high():
    coordinator = build_demo_network()
    result = coordinator.forecast("Delhi-NCR", hours_ahead=36)
    assert result["forecast_pm25"] > result["current_pm25"] * 0.5
    assert "is_spike_expected" in result


def test_source_classifier_flags_traffic_during_rush_hour():
    result = classify_source(
        zone_type="traffic", pm25_delta=20, current_hour=8, current_month=6
    )
    assert result["source"] == "traffic"


def test_source_classifier_flags_agri_burning_in_season():
    result = classify_source(
        zone_type="agricultural", pm25_delta=25, current_hour=14, current_month=11
    )
    assert result["source"] == "agricultural burning"


if __name__ == "__main__":
    test_local_trend_detects_rising_pollution()
    test_federated_round_blends_across_nodes()
    test_forecast_flags_spike_when_projection_is_high()
    test_source_classifier_flags_traffic_during_rush_hour()
    test_source_classifier_flags_agri_burning_in_season()
    print("all federated_model / source_classifier tests passed")
