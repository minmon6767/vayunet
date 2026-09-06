// app.js
// Talks to the Flask backend at the same origin (http://localhost:5050 by
// default) and renders the map + detail panel. No build step, no framework --
// this is meant to run by opening index.html served from the backend itself.

const API_BASE = ""; // same-origin, since Flask serves this file directly

let map;
let markers = {};
let hotspotData = {};
let selectedCity = null;
let currentLang = "en";

function severityColor(hotspot) {
  if (hotspot.forecast.is_spike_expected) return "#d1584a"; // spike
  if (hotspot.forecast.trend === "rising") return "#d9a441"; // watch
  return "#4fb6a6"; // steady
}

async function loadHotspots() {
  const res = await fetch(`${API_BASE}/api/hotspots`);
  const data = await res.json();
  hotspotData = {};
  data.hotspots.forEach((h) => (hotspotData[h.city] = h));
  return data.hotspots;
}

function initMap() {
  map = L.map("map", { zoomControl: true }).setView([22.5, 79.5], 5);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    maxZoom: 18,
  }).addTo(map);
}

function renderMarkers(hotspots) {
  hotspots.forEach((h) => {
    const color = severityColor(h);
    const marker = L.circleMarker([h.lat, h.lon], {
      radius: 10,
      color,
      fillColor: color,
      fillOpacity: 0.75,
      weight: 1,
    }).addTo(map);

    marker.bindTooltip(h.city, { direction: "top" });
    marker.on("click", () => selectCity(h.city));
    markers[h.city] = marker;
  });
}

function selectCity(city) {
  selectedCity = city;
  const h = hotspotData[city];
  if (!h) return;

  document.getElementById("detailEmpty").hidden = true;
  document.getElementById("detailContent").hidden = false;

  document.getElementById("detailCity").textContent = h.city;
  document.getElementById("detailZone").textContent = `${h.zone_type} zone`;

  document.getElementById("readingNow").textContent = `${h.forecast.current_pm25} µg/m³`;
  document.getElementById("readingLaterLabel").textContent = `+${h.forecast.forecast_hours}h`;
  document.getElementById("readingLater").textContent = `${h.forecast.forecast_pm25} µg/m³`;
  document.getElementById("readingArrow").textContent =
    h.forecast.trend === "rising" ? "↑" : h.forecast.trend === "falling" ? "↓" : "→";

  document.getElementById("sourceTag").textContent = h.source.source;
  document.getElementById("sourceReasoning").textContent = h.source.reasoning;

  const briefingResult = document.getElementById("briefingResult");
  briefingResult.hidden = true;
  briefingResult.textContent = "";

  renderAlert();
}

function renderAlert() {
  if (!selectedCity) return;
  const h = hotspotData[selectedCity];
  const alert = h.alerts[currentLang];
  document.getElementById("alertText").textContent = alert.text;
}

function setupLangToggle() {
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".lang-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentLang = btn.dataset.lang;
      renderAlert();
    });
  });
}

async function refreshAfterSimUpdate(city) {
  const hotspots = await loadHotspots();
  Object.values(markers).forEach((m) => map.removeLayer(m));
  markers = {};
  renderMarkers(hotspots);
  selectCity(city);
}

function setupBriefingButton() {
  document.getElementById("briefingButton").addEventListener("click", async () => {
    if (!selectedCity) return;

    const resultBox = document.getElementById("briefingResult");
    const button = document.getElementById("briefingButton");

    button.disabled = true;
    button.textContent = "Asking Gemini…";
    resultBox.hidden = false;
    resultBox.textContent = "";

    try {
      const res = await fetch(`${API_BASE}/api/gemini-briefing/${encodeURIComponent(selectedCity)}`);
      const data = await res.json();

      if (data.enabled === false) {
        resultBox.textContent = data.message;
      } else if (data.error) {
        resultBox.textContent = `Gemini request failed: ${data.error}`;
      } else {
        resultBox.textContent = data.briefing;
      }
    } catch (err) {
      resultBox.textContent = "Couldn't reach the backend for a briefing.";
    } finally {
      button.disabled = false;
      button.textContent = "Ask Gemini";
    }
  });
}

function setupSimButton() {
  document.getElementById("simButton").addEventListener("click", async () => {
    if (!selectedCity) return;
    const input = document.getElementById("simInput");
    const pm25 = parseFloat(input.value);
    if (Number.isNaN(pm25)) return;

    await fetch(`${API_BASE}/api/simulate-reading`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ city: selectedCity, pm25 }),
    });
    input.value = "";
    await refreshAfterSimUpdate(selectedCity);
  });
}

function populateCitySelect(hotspots) {
  const select = document.getElementById("photoCitySelect");
  hotspots.forEach((h) => {
    const option = document.createElement("option");
    option.value = h.city;
    option.textContent = h.city;
    select.appendChild(option);
  });
}

function setupPhotoUpload() {
  const input = document.getElementById("photoInput");
  const dropLabel = document.getElementById("photoDropLabel");
  const citySelect = document.getElementById("photoCitySelect");

  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;

    dropLabel.textContent = `Analyzing ${file.name}…`;

    const form = new FormData();
    form.append("photo", file);
    if (citySelect.value) form.append("city", citySelect.value);

    try {
      const res = await fetch(`${API_BASE}/api/upload-photo`, { method: "POST", body: form });
      const data = await res.json();

      if (data.error) {
        dropLabel.textContent = `Couldn't read that photo — try another`;
        return;
      }

      document.getElementById("photoResult").hidden = false;
      document.getElementById("hazeScore").textContent = data.haze_score.toFixed(2);
      document.getElementById("hazeLabel").textContent = data.label;
      document.getElementById("hazeSource").textContent =
        data.source === "dark_channel_prior+gemini" ? "cross-checked with Gemini" : "offline estimate";

      dropLabel.textContent = "Choose or drop another photo";
    } catch (err) {
      dropLabel.textContent = "Backend unreachable — is app.py running?";
    }
  });
}

async function boot() {
  const statusLine = document.getElementById("statusLine");
  try {
    const res = await fetch(`${API_BASE}/api/status`);
    const status = await res.json();
    statusLine.textContent = status.gemini_enabled
      ? `live · ${status.cities_tracked.length} city nodes · Gemini enabled`
      : `live · ${status.cities_tracked.length} city nodes · offline mode`;
  } catch (err) {
    statusLine.textContent = "backend unreachable — start it with: python backend/app.py";
    return;
  }

  initMap();
  const hotspots = await loadHotspots();
  renderMarkers(hotspots);
  populateCitySelect(hotspots);
  setupLangToggle();
  setupSimButton();
  setupBriefingButton();
  setupPhotoUpload();

  // Auto-select the first city so the panel isn't empty on first load.
  if (hotspots.length) selectCity(hotspots[0].city);
}

boot();
