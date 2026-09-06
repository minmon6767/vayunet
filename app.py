"""
app.py

The API layer. Every route here is intentionally thin -- it just calls into
haze_detector / federated_model / source_classifier / alert_generator and
returns JSON. Keeping the logic out of the routes means each piece can be
unit tested (see tests/) without spinning up a server.

Run it with:
    python backend/app.py
and open frontend/index.html in a browser (or just visit http://localhost:5050
if you'd rather test the API directly).
"""

import os
import uuid

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from federated_model import build_demo_network
from source_classifier import classify_source
from alert_generator import generate_all_languages
from haze_detector import analyze_photo
from gemini_bridge import get_gemini_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB per photo upload

# One shared federated network for the life of the process. A real deployment
# would persist each city node's readings in BigQuery/Firestore; for the demo,
# an in-memory network seeded with realistic data is enough to show the whole
# pipeline working end to end.
network = build_demo_network()
gemini_client = get_gemini_client()

# Remembers the most recent photo analysis submitted for each city, so the
# Gemini briefing route can hand that context to Gemini alongside the
# forecast/source data instead of Gemini only ever seeing one field at a
# time. In-memory and best-effort -- a restart clears it, same as the
# federated network itself.
latest_photo_by_city = {}


@app.route("/")
def serve_frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def serve_frontend_assets(filename):
    # Lets index.html load style.css / app.js without a separate static server.
    if os.path.exists(os.path.join(FRONTEND_DIR, filename)):
        return send_from_directory(FRONTEND_DIR, filename)
    return jsonify({"error": "not found"}), 404


@app.route("/api/status")
def status():
    return jsonify({
        "service": "vayunet-backend",
        "cities_tracked": list(network.nodes.keys()),
        "gemini_enabled": gemini_client is not None,
    })


@app.route("/api/hotspots")
def hotspots():
    """
    Returns every tracked city with its forecast, likely source, and a
    ready-to-send alert in English + Hindi. This is the single call the
    dashboard map is built from.
    """
    results = []
    for name, node in network.nodes.items():
        forecast = network.forecast(name)
        source_info = classify_source(
            zone_type=node.zone_type,
            pm25_delta=forecast["delta"],
        )
        alerts = generate_all_languages(forecast, source_info, gemini_client=gemini_client)

        results.append({
            "city": name,
            "lat": node.lat,
            "lon": node.lon,
            "zone_type": node.zone_type,
            "forecast": forecast,
            "source": source_info,
            "alerts": alerts,
        })

    return jsonify({"hotspots": results})


@app.route("/api/forecast/<city>")
def forecast_city(city):
    if city not in network.nodes:
        return jsonify({"error": f"unknown city '{city}'"}), 404
    return jsonify(network.forecast(city))


@app.route("/api/simulate-reading", methods=["POST"])
def simulate_reading():
    """
    Lets the dashboard (or a curl command) push a new PM2.5 reading into a
    city node, so you can demo the forecast reacting to fresh data live
    instead of only showing the seeded numbers.
    """
    payload = request.get_json(force=True, silent=True) or {}
    city = payload.get("city")
    pm25 = payload.get("pm25")

    if city not in network.nodes:
        return jsonify({"error": f"unknown city '{city}'"}), 404
    if not isinstance(pm25, (int, float)):
        return jsonify({"error": "pm25 must be a number"}), 400

    node = network.nodes[city]
    # Age every existing reading by 12 hours and add the new one as "now" --
    # keeps a rolling window instead of growing forever during a live demo.
    node.readings = [(h + 12, v) for h, v in node.readings][-8:]
    node.add_reading(pm25, hours_ago=0)

    return jsonify(network.forecast(city))


@app.route("/api/upload-photo", methods=["POST"])
def upload_photo():
    """
    Accepts a citizen photo, runs the haze detector (and Gemini cross-check
    if configured), and returns the estimate. The city name is optional --
    this endpoint works standalone with any photo on hand -- but if you pass
    one, the result is remembered and gets folded into that city's Gemini
    briefing (see /api/gemini-briefing/<city>).
    """
    if "photo" not in request.files:
        return jsonify({"error": "no file under form field 'photo'"}), 400

    photo = request.files["photo"]
    if photo.filename == "":
        return jsonify({"error": "empty filename"}), 400

    city = request.form.get("city")

    filename = f"{uuid.uuid4().hex}_{secure_filename(photo.filename)}"
    save_path = os.path.join(UPLOAD_DIR, filename)
    photo.save(save_path)

    try:
        result = analyze_photo(save_path, gemini_client=gemini_client)
    except Exception as exc:
        return jsonify({"error": f"could not analyze image: {exc}"}), 400
    finally:
        # Demo instance -- don't accumulate uploaded photos on disk.
        if os.path.exists(save_path):
            os.remove(save_path)

    if city and city in network.nodes:
        latest_photo_by_city[city] = result

    return jsonify(result)


@app.route("/api/gemini-briefing/<city>")
def gemini_briefing(city):
    """
    The "let Gemini see everything and give an opinion" endpoint. Gathers
    every piece of data we have for a city -- current + forecast PM2.5, the
    trend, the rule-based source guess and its reasoning, and the latest
    citizen photo reading if one was submitted for this city -- and hands
    all of it to Gemini in one prompt, asking for a short analyst-style
    briefing rather than a single narrow answer.

    Returns the exact context dict that was sent, alongside Gemini's
    response, so nothing about what Gemini was shown is hidden.
    """
    if city not in network.nodes:
        return jsonify({"error": f"unknown city '{city}'"}), 404

    if gemini_client is None:
        return jsonify({
            "enabled": False,
            "message": (
                "Gemini isn't configured. Copy .env.example to .env, add a "
                "GEMINI_API_KEY from https://aistudio.google.com/apikey, "
                "pip install google-genai, and restart the server."
            ),
        }), 200

    node = network.nodes[city]
    forecast = network.forecast(city)
    source_info = classify_source(zone_type=node.zone_type, pm25_delta=forecast["delta"])

    context = {
        "city": city,
        "zone_type": node.zone_type,
        "current_pm25": forecast["current_pm25"],
        "forecast_pm25": forecast["forecast_pm25"],
        "forecast_hours": forecast["forecast_hours"],
        "trend": forecast["trend"],
        "is_spike_expected": forecast["is_spike_expected"],
        "source": source_info["source"],
        "source_confidence": source_info["confidence"],
        "source_reasoning": source_info["reasoning"],
        "latest_photo": latest_photo_by_city.get(city),
    }

    try:
        briefing_text = gemini_client.full_briefing(context)
    except Exception as exc:
        return jsonify({"error": f"Gemini request failed: {exc}"}), 502

    return jsonify({
        "enabled": True,
        "city": city,
        "context_sent_to_gemini": context,
        "briefing": briefing_text,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
