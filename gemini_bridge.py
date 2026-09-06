"""
gemini_bridge.py

Thin wrapper around the Gemini API, using Google's current unified SDK
(`google-genai`) -- not the older `google-generativeai` package, which
Google has deprecated and stopped updating. Everything in this project runs
without a Gemini key at all -- this file exists so that dropping a
GEMINI_API_KEY into .env upgrades the demo from "rule-based haze scoring +
template alerts" to "rule-based haze scoring cross-checked by Gemini Vision,
Gemini-written alerts, and a full Gemini-read situational briefing", with no
other code changes.

We keep this isolated on purpose: the rest of the backend never imports
google.genai directly, so a missing package or a missing key never crashes
the app, it just quietly falls back to the deterministic path.
"""

import os

MODEL_NAME = "gemini-flash-latest"  # always resolves to Google's current default Flash model


class GeminiClient:
    def __init__(self, api_key):
        # Imported lazily so the package only needs to exist if someone
        # actually sets an API key.
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.genai = genai

    def describe_haze(self, image_path):
        """
        Asks Gemini to look at a citizen photo and describe visible haze/smoke,
        plus give a rough 0-1 severity number we can blend with our own score.
        """
        from google.genai import types

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        mime_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

        prompt = (
            "You are looking at a photo submitted by a citizen for air quality "
            "monitoring. In one short sentence, describe visible haze, smoke, or "
            "smog if present. Then on a new line write 'SCORE: x.xx' where x.xx "
            "is your estimate of haze severity from 0.00 (perfectly clear) to "
            "1.00 (severe, visibility badly reduced). If the image doesn't show "
            "an outdoor scene, say so and give SCORE: 0.00."
        )

        response = self.client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
        )
        text = response.text.strip()

        score = None
        description = text
        for line in text.splitlines():
            if line.upper().startswith("SCORE"):
                try:
                    score = float(line.split(":")[1].strip())
                except (IndexError, ValueError):
                    score = None
            else:
                description = line.strip() or description

        return {"description": description, "score": score}

    def full_briefing(self, context):
        """
        The "let Gemini see everything and give an opinion" mode. Unlike
        describe_haze (one photo) or write_alert (one short message), this
        hands Gemini the whole situational picture we've assembled for a
        city -- current + forecast PM2.5, the trend, the zone type, the
        rule-based source guess and its reasoning, and the latest citizen
        photo reading if one exists -- and asks it to reason across all of
        it, the way a human analyst reading a dashboard would.

        context is a plain dict (see app.py's /api/gemini-briefing route for
        exactly what goes in it). Keeping this as one flat dict, returned
        alongside the response, means you can always see precisely what
        Gemini was shown -- nothing is hidden from the person reading the
        API response.
        """
        photo_line = "No citizen photo submitted for this city yet."
        if context.get("latest_photo"):
            p = context["latest_photo"]
            photo_line = (
                f"Latest citizen photo scored {p['haze_score']} ({p['label']}) "
                f"via {p['source']}."
            )

        prompt = (
            "You are an air-quality analyst reviewing one city's live monitoring "
            "data. Read every field below and write a short briefing a busy "
            "pollution-control officer could act on immediately.\n\n"
            f"City: {context['city']}\n"
            f"Zone type: {context['zone_type']}\n"
            f"Current PM2.5: {context['current_pm25']} µg/m³\n"
            f"Forecast PM2.5 in {context['forecast_hours']}h: {context['forecast_pm25']} µg/m³\n"
            f"Trend: {context['trend']}\n"
            f"Spike expected: {context['is_spike_expected']}\n"
            f"Rule-based source guess: {context['source']} (confidence: {context['source_confidence']})\n"
            f"Reasoning behind that guess: {context['source_reasoning']}\n"
            f"{photo_line}\n\n"
            "Structure your answer as exactly three short paragraphs, no "
            "headers or markdown:\n"
            "1) What's actually happening, in plain language.\n"
            "2) Whether you agree with the rule-based source guess, and why "
            "or why not, given everything above.\n"
            "3) One concrete, specific recommended action for the next few "
            "hours.\n"
            "Keep the whole thing under 150 words."
        )

        response = self.client.models.generate_content(model=MODEL_NAME, contents=prompt)
        return response.text.strip()

    def write_alert(self, language, city, source_type, forecast_hours, severity_label):
        """
        Generates a natural-language public alert in the requested language.
        Used by alert_generator.py when a Gemini key is available; otherwise
        that module falls back to its own templates.
        """
        prompt = (
            f"Write a short public air-quality alert in {language} for residents "
            f"of {city}. A {severity_label} pollution spike linked to "
            f"{source_type} is forecast within {forecast_hours} hours. Keep it "
            f"to 2 short sentences, practical, no alarmist tone, suitable for "
            f"WhatsApp/SMS."
        )
        response = self.client.models.generate_content(model=MODEL_NAME, contents=prompt)
        return response.text.strip()


def get_gemini_client():
    """
    Returns a configured GeminiClient if GEMINI_API_KEY is set and the
    google-genai package is installed, otherwise None. Every caller in this
    project is written to handle None gracefully.
    """
    api_key = os.environ.get("AIzaSyA52I8E6oql95yZl_hx3nz_vuBONBEz5r8")
    if not api_key:
        return None
    try:
        return GeminiClient(api_key)
    except ImportError:
        return None
