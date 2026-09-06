"""
federated_model.py

Simulates the part of VayuNet that's hardest to show in a demo: federated
learning across cities, where every city keeps its raw sensor data local and
only shares a small model summary.

Real VayuNet would run a small forecasting model (e.g. an LSTM or gradient
boosted model on Vertex AI) per city, and average model *weights* across
cities on some schedule. For a prototype, we make the same trade-off with a
much simpler model so the mechanics are visible and auditable end to end:

  - Each CityNode holds its own recent PM2.5 readings (its "raw data" --
    never leaves the node).
  - Each node fits a tiny linear trend (slope + intercept) to its own
    readings. That trend IS the "model weights" in this simulation.
  - The federated step averages slopes across nodes, weighted by how much
    data each node has, and blends a little of that shared trend back into
    each node's own forecast. Only the two numbers (slope, intercept) are
    ever exchanged -- never a single raw reading.

This mirrors real federated averaging (FedAvg) closely enough to be an
honest simulation of the idea, not just a label slapped on an unrelated
computation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class CityNode:
    name: str
    lat: float
    lon: float
    readings: list = field(default_factory=list)  # list of (hours_ago, pm25) tuples, most recent last
    zone_type: str = "mixed"  # industrial | agricultural | traffic | mixed

    def add_reading(self, pm25, hours_ago=0):
        self.readings.append((hours_ago, pm25))

    def local_trend(self):
        """
        Fits y = slope * x + intercept to this node's own readings using
        ordinary least squares. This never looks at any other node's data.
        """
        if len(self.readings) < 2:
            last_value = self.readings[-1][1] if self.readings else 50.0
            return 0.0, last_value

        xs = [-h for h, _ in self.readings]  # earlier readings are more negative
        ys = [v for _, v in self.readings]
        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs) or 1e-6
        slope = numerator / denominator
        intercept = mean_y - slope * mean_x
        return slope, intercept


class FederatedCoordinator:
    """
    Holds every city node and runs the "federated round": collect each
    node's local trend, average the slopes weighted by data volume, and
    hand back a blended forecast per node. This class stands in for the
    model-registry / aggregation step that would otherwise run on Vertex AI.
    """

    def __init__(self):
        self.nodes = {}

    def register_node(self, node: CityNode):
        self.nodes[node.name] = node

    def federated_round(self, blend_weight=0.25):
        """
        Returns {city_name: (slope, intercept)} where each node's own trend
        has been nudged toward the data-weighted average slope across all
        nodes. blend_weight controls how much cross-city signal leaks in --
        higher means faster-spreading regional smog patterns dominate more,
        lower means each city trusts its own recent data more.
        """
        local_trends = {}
        weights = {}
        for name, node in self.nodes.items():
            slope, intercept = node.local_trend()
            local_trends[name] = (slope, intercept)
            weights[name] = max(len(node.readings), 1)

        total_weight = sum(weights.values()) or 1
        shared_slope = sum(
            local_trends[name][0] * weights[name] for name in local_trends
        ) / total_weight

        blended = {}
        for name, (slope, intercept) in local_trends.items():
            blended_slope = (1 - blend_weight) * slope + blend_weight * shared_slope
            blended[name] = (blended_slope, intercept)
        return blended

    def forecast(self, city_name, hours_ahead=36, blend_weight=0.25):
        """
        Projects a single node's PM2.5 level `hours_ahead` hours out using
        its federated-blended trend, clipped to a sane range.
        """
        blended = self.federated_round(blend_weight=blend_weight)
        if city_name not in blended:
            raise KeyError(f"No node registered for '{city_name}'")

        slope, intercept = blended[city_name]
        projected = intercept + slope * hours_ahead
        projected = max(5.0, min(projected, 500.0))  # PM2.5 sanity bounds

        node = self.nodes[city_name]
        current = node.readings[-1][1] if node.readings else intercept
        delta = projected - current

        return {
            "city": city_name,
            "current_pm25": round(current, 1),
            "forecast_pm25": round(projected, 1),
            "forecast_hours": hours_ahead,
            "trend": "rising" if delta > 3 else ("falling" if delta < -3 else "steady"),
            "delta": round(delta, 1),
            "is_spike_expected": projected >= 150 and delta > 0,
        }


def build_demo_network():
    """
    Populates a coordinator with a handful of Indian cities and plausible
    synthetic readings so the API has something real to compute over out of
    the box, with no external data source required.
    """
    coordinator = FederatedCoordinator()

    seed_data = [
        # name, lat, lon, zone_type, readings (hours_ago, pm25) oldest->newest
        ("Indore", 22.7196, 75.8577, "mixed",
            [(48, 92), (36, 101), (24, 118), (12, 126), (0, 134)]),
        ("Delhi-NCR", 28.6139, 77.2090, "traffic",
            [(48, 210), (36, 225), (24, 240), (12, 265), (0, 288)]),
        ("Raipur", 21.2514, 81.6296, "industrial",
            [(48, 88), (36, 95), (24, 103), (12, 109), (0, 112)]),
        ("Ludhiana", 30.9010, 75.8573, "agricultural",
            [(48, 95), (36, 130), (24, 172), (12, 205), (0, 231)]),
        ("Bengaluru", 12.9716, 77.5946, "mixed",
            [(48, 58), (36, 60), (24, 61), (12, 59), (0, 57)]),
    ]

    for name, lat, lon, zone_type, readings in seed_data:
        node = CityNode(name=name, lat=lat, lon=lon, zone_type=zone_type)
        for hours_ago, pm25 in readings:
            node.add_reading(pm25, hours_ago=hours_ago)
        coordinator.register_node(node)

    return coordinator
