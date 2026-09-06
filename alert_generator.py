"""
alert_generator.py

Turns a forecast + source classification into a short public-facing alert.

Default behaviour uses hand-written templates in English and Hindi -- good
enough to demo and to read out loud, and it means the whole pipeline works
with zero API keys. If a Gemini client is available (see gemini_bridge.py),
we hand it the same facts and let it write something a bit more natural,
falling back to the template on any failure.
"""

SEVERITY_LABELS = {
    "low": {"en": "moderate", "hi": "मध्यम"},
    "high": {"en": "severe", "hi": "गंभीर"},
}

TEMPLATES = {
    "en": (
        "Air quality alert for {city}: a {severity} pollution spike linked to "
        "{source} is expected within {hours} hours. Sensitive groups should "
        "limit outdoor activity and keep windows closed during peak hours."
    ),
    "hi": (
        "{city} के लिए वायु गुणवत्ता चेतावनी: {source} से जुड़ी एक {severity} प्रदूषण "
        "वृद्धि अगले {hours} घंटों में संभावित है। संवेदनशील लोग बाहर कम जाएं और "
        "पीक समय में खिड़कियां बंद रखें।"
    ),
}

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi"}


def _severity_bucket(forecast_pm25):
    return "high" if forecast_pm25 >= 200 else "low"


def generate_alert(forecast, source_info, language="en", gemini_client=None):
    """
    forecast: dict from federated_model.forecast()
    source_info: dict from source_classifier.classify_source()
    language: "en" or "hi"
    gemini_client: optional GeminiClient instance
    """
    severity_key = _severity_bucket(forecast["forecast_pm25"])
    severity_word = SEVERITY_LABELS[severity_key][language]

    if gemini_client is not None:
        try:
            text = gemini_client.write_alert(
                language=LANGUAGE_NAMES[language],
                city=forecast["city"],
                source_type=source_info["source"],
                forecast_hours=forecast["forecast_hours"],
                severity_label=severity_word,
            )
            if text:
                return {"language": language, "text": text, "source": "gemini"}
        except Exception:
            pass  # fall through to template

    template = TEMPLATES[language]
    text = template.format(
        city=forecast["city"],
        severity=severity_word,
        source=source_info["source"],
        hours=forecast["forecast_hours"],
    )
    return {"language": language, "text": text, "source": "template"}


def generate_all_languages(forecast, source_info, gemini_client=None):
    return {
        lang: generate_alert(forecast, source_info, language=lang, gemini_client=gemini_client)
        for lang in TEMPLATES
    }
