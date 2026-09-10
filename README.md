# VayuNet

City-level AQI numbers hide the stuff that actually matters — a factory
running overnight, a farmer burning stubble two villages over, a smog pocket
that settles over one neighborhood and not the next. By the time an official
average shows a spike, people have already been breathing it for hours.

VayuNet is an attempt at fixing that: turn ordinary smartphones into a
distributed sensor network, fuse that with satellite data, and forecast
pollution spikes 24–48 hours before they peak instead of just reporting them
after the fact — without ever centralizing anyone's raw data.

This repo is a working prototype of the core loop, built for a hackathon.
It's not hooked up to real satellites or real citizen traffic yet, but every
piece of logic in it is real: the haze detector actually analyzes pixels, the
forecasting actually fits trends to data, the federated averaging actually
averages model weights instead of raw readings.

## What's actually running here

| Piece | What it does | How real vs. simulated |
|---|---|---|
| **Haze detector** | Estimates smoke/haze density from any photo using the dark channel prior (a real single-image dehazing technique, not a stub) | Fully real, runs offline |
| **Federated forecasting** | Each city fits its own PM2.5 trend locally; only the trend (2 numbers) gets shared and averaged across cities, never raw readings | Real algorithm (a simplified FedAvg), running over seeded synthetic sensor data |
| **Source classifier** | Rule-based guess at whether a spike is industrial, agricultural, or traffic-linked, using zone type + time of day/year | Real rules, deliberately transparent rather than a black box |
| **Alert generator** | Produces a public alert in English and Hindi from the forecast + source | Template-based by default; if you add a Gemini key, it writes the alert instead |
| **Gemini briefing** | Hands Gemini *everything* known about a city at once — current + forecast PM2.5, trend, the rule-based source guess and its reasoning, and the latest citizen photo reading if there is one — and asks it to read all of it and write a short analyst-style briefing with a recommended action | Only runs if a Gemini key is set; the dashboard shows exactly why if it isn't |
| **Satellite data (NO2, AOD, fire hotspots)** | Not in this repo yet | Would plug in via Google Earth Engine — the CityNode structure is already shaped to receive it |

That last row is the honest caveat: this prototype proves the pipeline and
the federated-averaging idea with synthetic sensor data standing in for real
ground stations and satellite feeds. Swapping in real data sources means
writing readings into the same `CityNode.add_reading()` calls — the
forecasting and alerting logic downstream doesn't change.

## Running it

You need Python 3.10+ and nothing else installed globally.

```bash
./run_demo.sh
```

This creates a virtual environment on first run, installs the three
dependencies (Flask, NumPy, Pillow), and starts the server. Then open:

```
http://localhost:5050
```

That's it — the Flask backend serves the frontend directly, so there's no
separate build step or second server to start.

If you'd rather do it by hand:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 backend/app.py
```

### Turning on Gemini (optional)

By default everything runs offline with rule-based logic. To let Gemini
cross-check the haze score, write the alerts, and generate the full
situational briefing described below:

```bash
cp .env.example .env
# then edit .env and paste in a key from https://aistudio.google.com/apikey
pip install google-genai
```

Restart the server and the dashboard's status line will say `Gemini enabled`.
Nothing else needs to change — `gemini_bridge.py` is the only file that
touches the Gemini SDK, and every other module already handles it being
absent.

**Important:** install `google-genai`, not the older `google-generativeai`
package. Google deprecated and stopped updating the old one — this project
is written against the current SDK from the start.

If you skip this step entirely, the "Ask Gemini" button on the dashboard
still works — it just tells you exactly which two steps above are missing
instead of failing silently.

### The Gemini briefing, specifically

Every other Gemini call in this repo answers one narrow question (how hazy
is this photo, write this one alert). The briefing is different: click "Ask
Gemini" on any city in the dashboard, and the backend assembles the full
picture for that city — current PM2.5, the forecast, the trend, the
rule-based source guess *and its reasoning*, and the latest citizen photo
analysis if one was uploaded and tagged to that city — into a single prompt,
and asks Gemini to read all of it and respond with:

1. what's actually happening, in plain language
2. whether it agrees with the rule-based source guess, and why
3. one concrete recommended action

The API response also returns the exact context sentto Gemini dict, so it's never a mystery what Gemini was shown.

## What you'll see on the dashboard

- A map of five Indian city nodes (Indore, Delhi-NCR, Raipur, Ludhiana,
  Bengaluru), each seeded with a short PM2.5 history and colored by whether a
  spike is forecast.
- Click a city to see its current reading, 36-hour forecast, likely
  pollution source with the reasoning behind it, and the exact alert text
  that would go out — in English or Hindi.
- A box to push a new PM2.5 reading into a city live, so you can watch the
  federated forecast react in real time during a demo instead of only
  showing static numbers.
- An "Ask Gemini" button per city that requests the full briefing described
  above (only active once a Gemini key is set — otherwise it tells you how
  to enable it).
- A photo upload widget that runs the real haze detector on any photo you
  give it, with an optional city dropdown so that reading feeds into that
  city's Gemini briefing too.

## Project layout

```
vayunet/
├── backend/
│   ├── app.py                 # Flask API — thin routes, all logic lives in the modules below
│   ├── haze_detector.py       # Dark channel prior haze estimation
│   ├── federated_model.py     # City nodes + federated averaging + forecasting
│   ├── source_classifier.py   # Rule-based spike source attribution
│   ├── alert_generator.py     # English/Hindi alert templates (+ optional Gemini)
│   └── gemini_bridge.py       # Isolated Gemini wrapper, only loads if a key is set
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js                 # Vanilla JS, talks to the Flask API, renders the Leaflet map
├── tests/
│   ├── test_haze_detector.py
│   └── test_federated_model.py
├── run_demo.sh
├── requirements.txt
└── .env.example
```

## Running the tests

```bash
source .venv/bin/activate   # if you haven't already
python3 tests/test_haze_detector.py
python3 tests/test_federated_model.py
```

Both scripts print `all ... tests passed` and exit non-zero on failure, so
they work fine in a CI step too if you add one.

## Where this goes next

- Swap the seeded synthetic readings for a real low-cost sensor feed and
  Google Earth Engine's Sentinel-5P/MODIS layers — `CityNode` is already
  shaped to take them.
- Move the in-memory `FederatedCoordinator` to Firestore/BigQuery so nodes
  persist across restarts and can scale past five cities.
- Replace the dark channel prior with Gemini Vision as the primary haze
  signal once photo volume is high enough to justify the API cost, keeping
  the offline estimate as a fallback for low-bandwidth regions.
- Add drone-based spot checks for industrial zones and extend the same
  federated-node pattern to water quality.

## Team

Built by Team SuperNova for GDG Indore hackathon submission.
