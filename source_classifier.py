"""
source_classifier.py

Guesses whether a pollution spike is industrial, agricultural (stubble
burning), or traffic-linked using simple, explainable rules -- the kind of
logic a domain expert could sanity-check on a whiteboard, rather than a
black-box model. Real VayuNet would train this against satellite fire-hotspot
layers and time-series NO2/PM ratios; here the same signals are approximated
with the fields already sitting on our CityNode objects plus the time of day.

Keeping this rule-based (rather than another simulated model) is deliberate:
source attribution is exactly the kind of decision a pollution board wants to
be able to explain to the public, so a transparent rule set is a feature, not
a shortcut.
"""

from datetime import datetime

AGRI_BURNING_MONTHS = {10, 11, 4, 5}  # Oct-Nov (paddy) and Apr-May (wheat) in India
TRAFFIC_RUSH_HOURS = {7, 8, 9, 18, 19, 20, 21}


def classify_source(zone_type, pm25_delta, current_hour=None, current_month=None):
    """
    zone_type: the CityNode's declared land-use context ("industrial",
               "agricultural", "traffic", "mixed")
    pm25_delta: how much PM2.5 has risen recently (forecast delta or recent slope)
    current_hour: 0-23, defaults to now
    current_month: 1-12, defaults to now
    """
    now = datetime.now()
    hour = current_hour if current_hour is not None else now.hour
    month = current_month if current_month is not None else now.month

    if zone_type == "agricultural" and month in AGRI_BURNING_MONTHS and pm25_delta > 10:
        return {
            "source": "agricultural burning",
            "confidence": "high",
            "reasoning": (
                f"Zone is agricultural, month {month} falls in a known crop-burning "
                f"window, and PM2.5 is rising sharply (+{pm25_delta:.0f})."
            ),
        }

    if zone_type == "traffic" and hour in TRAFFIC_RUSH_HOURS and pm25_delta > 5:
        return {
            "source": "traffic",
            "confidence": "medium",
            "reasoning": (
                f"Zone is traffic-dominant and the spike lines up with rush hour "
                f"({hour}:00)."
            ),
        }

    if zone_type == "industrial" and pm25_delta > 3:
        return {
            "source": "industrial",
            "confidence": "medium" if pm25_delta < 20 else "high",
            "reasoning": (
                "Zone is industrial and PM2.5 is climbing steadily rather than "
                "spiking in a rush-hour or seasonal pattern."
            ),
        }

    if pm25_delta > 15:
        return {
            "source": "mixed / undetermined",
            "confidence": "low",
            "reasoning": (
                "A significant spike is forecast but doesn't cleanly match any "
                "single known pattern -- flag for manual review."
            ),
        }

    return {
        "source": "no significant spike",
        "confidence": "n/a",
        "reasoning": "PM2.5 trend doesn't currently indicate a specific source.",
    }
