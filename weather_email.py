import os
import requests
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from zoneinfo import ZoneInfo
import math

# =============================================================================
# CONFIGURATION
# Reads credentials from environment variables (for GitHub Actions/security)
# or a local .env file.
# =============================================================================
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "godwin7776@gmail.com")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "msaranmuthu17@gmail.com")

# =============================================================================
# CONSTANTS
# =============================================================================
API_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=78.2232&longitude=15.6469"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
    "weather_code,wind_speed_10m,wind_direction_10m"
    "&hourly=temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,"
    "snowfall,weather_code,visibility,wind_speed_10m,wind_direction_10m"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
    "sunrise,sunset,wind_speed_10m_max"
    "&timezone=Europe/Oslo&forecast_days=2"
)

LOCATION_NAME = "Longyearbyen, Svalbard, Norway"
TIMEZONE_NAME = "Europe/Oslo"
NOT_AVAILABLE = "Not available"

# Transparent thresholds used for the analysis
STRONG_WIND_KMH = 40.0          # strong wind: >= 40 km/h (as specified)
POOR_VISIBILITY_KM = 1.0        # poor visibility: < 1 km (as specified)
TEMP_TREND_THRESHOLD_C = 2.0    # a temperature change of >= 2 °C counts as "meaningful"
VERY_COLD_C = -10.0             # "very low" temperature for the clothing tip
WIND_SHIFT_DEGREES = 90.0       # wind direction change of >= 90° counts as a shift

STABLE_TEXT = ("The weather remains relatively stable over the next 24 hours "
               "based on the available forecast.")
NO_CONCERN_TEXT = "No significant weather concerns from the available forecast."

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}
FREEZING_CODES = {56, 57, 66, 67}
THUNDER_CODES = {95, 96, 99}

try:
    OSLO_TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    OSLO_TZ = None
    print("Warning: Europe/Oslo time zone data not found. "
          "Falling back to the local time supplied by the API.")


# =============================================================================
# SMALL HELPERS
# =============================================================================
def is_number(value):
    """True only for real, finite numeric values (never None/bool/NaN)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and not math.isnan(value) and not math.isinf(value))


def safe_value(value, decimals=None, suffix=""):
    """Return a display string, or 'Not available' for missing/invalid values."""
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, str):
        return (value + suffix) if value.strip() else NOT_AVAILABLE
    if is_number(value):
        if decimals is None:
            text = str(value)
        else:
            if round(value, decimals) == 0:
                value = 0  # avoid "-0.0"
            text = f"{value:.{decimals}f}"
        return text + suffix
    return NOT_AVAILABLE


def get_value(data, section, key, index=None):
    """Safely read data[section][key] (optionally list item `index`)."""
    try:
        block = data.get(section)
        if not isinstance(block, dict):
            return None
        value = block.get(key)
        if index is None:
            return value
        if isinstance(value, list) and 0 <= index < len(value):
            return value[index]
        return None
    except Exception:
        return None


def parse_local(value):
    """Parse an API ISO timestamp as Europe/Oslo local time."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if OSLO_TZ is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=OSLO_TZ)
    return dt


def esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_snowfall(total):
    if not is_number(total):
        return NOT_AVAILABLE
    if total <= 0:
        return "0 cm"
    return f"{total:.1f} cm" if total >= 0.1 else f"{total:.2f} cm"


# =============================================================================
# REQUIRED FUNCTIONS
# =============================================================================
def get_weather_data():
    """Call Open-Meteo. Returns parsed JSON (dict) or None on failure."""
    try:
        response = requests.get(API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected API response format.")
        if not any(isinstance(data.get(k), dict) and data.get(k)
                   for k in ("current", "daily", "hourly")):
            raise ValueError("API response contains no weather data.")
        return data
    except requests.exceptions.Timeout:
        print("Error: The weather API request timed out.")
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the weather API. Check your internet connection.")
    except requests.exceptions.HTTPError as exc:
        print(f"Error: The weather API returned an HTTP error: {exc}")
    except requests.exceptions.RequestException as exc:
        print(f"Error: Weather API request failed: {exc}")
    except ValueError as exc:
        print(f"Error: Invalid or unusable weather API response: {exc}")
    except Exception as exc:
        print(f"Error: Unexpected problem while retrieving weather data: {exc}")
    return None


def weather_code_to_description(code):
    if is_number(code) and int(code) == code:
        return WEATHER_CODES.get(int(code), NOT_AVAILABLE)
    return NOT_AVAILABLE


def compass_point(degrees):
    if not is_number(degrees):
        return None
    d = degrees % 360
    if d < 22.5 or d >= 337.5:
        return "N"
    if d < 67.5:
        return "NE"
    if d < 112.5:
        return "E"
    if d < 157.5:
        return "SE"
    if d < 202.5:
        return "S"
    if d < 247.5:
        return "SW"
    if d < 292.5:
        return "W"
    return "NW"


def degrees_to_direction(degrees):
    point = compass_point(degrees)
    if point is None:
        return NOT_AVAILABLE
    return f"{point} ({round(degrees % 360):.0f}°)"


def format_time(value):
    """Format an ISO timestamp as HH:MM."""
    dt = parse_local(value)
    if dt is None:
        return NOT_AVAILABLE
    return dt.strftime("%H:%M")


def calculate_next_24_hours(data):
    """Analyse hourly data for the 24 hours starting at the current Oslo hour."""
    result = {
        "available": False, "count": 0,
        "temp_min": None, "temp_max": None, "temp_start": None, "temp_end": None,
        "trend": None,
        "precip_total": None, "precip_any": False, "max_prob": None,
        "snow_total": None,
        "max_wind": None, "strong_wind": False, "wind_shift": None,
        "min_vis_km": None, "poor_vis": False, "start_vis_km": None,
        "sequence": [], "codes": [],
    }

    times = get_value(data, "hourly", "time")
    if not isinstance(times, list) or not times:
        return result

    if OSLO_TZ is not None:
        now = datetime.now(OSLO_TZ)
    else:
        now = parse_local(get_value(data, "current", "time"))
    if now is None:
        return result

    start_ts = now.replace(minute=0, second=0, microsecond=0).timestamp()
    idx = []
    for i, t in enumerate(times):
        dt = parse_local(t)
        if dt is None:
            continue
        delta = dt.timestamp() - start_ts
        if 0 <= delta < 24 * 3600:
            idx.append(i)
    if not idx:
        return result

    def series(key):
        return [get_value(data, "hourly", key, i) for i in idx]

    def numbers(values):
        return [v for v in values if is_number(v)]

    result["available"] = True
    result["count"] = len(idx)

    # Temperature
    temps = numbers(series("temperature_2m"))
    if temps:
        result["temp_min"] = min(temps)
        result["temp_max"] = max(temps)
        result["temp_start"] = temps[0]
        result["temp_end"] = temps[-1]
        if len(temps) >= 2:
            diff = temps[-1] - temps[0]
            if diff >= TEMP_TREND_THRESHOLD_C:
                result["trend"] = "rise"
            elif diff <= -TEMP_TREND_THRESHOLD_C:
                result["trend"] = "fall"
            else:
                result["trend"] = "stable"

    # Precipitation
    precip = numbers(series("precipitation"))
    if precip:
        result["precip_total"] = sum(precip)
        result["precip_any"] = any(v > 0 for v in precip)
    probs = numbers(series("precipitation_probability"))
    if probs:
        result["max_prob"] = max(probs)

    # Snowfall (cm)
    snow = numbers(series("snowfall"))
    if snow:
        result["snow_total"] = sum(snow)

    # Wind
    winds = numbers(series("wind_speed_10m"))
    if winds:
        result["max_wind"] = max(winds)
        result["strong_wind"] = max(winds) >= STRONG_WIND_KMH
    dirs = numbers(series("wind_direction_10m"))
    if len(dirs) >= 2:
        diff = abs(dirs[0] - dirs[-1]) % 360
        diff = min(diff, 360 - diff)
        if diff >= WIND_SHIFT_DEGREES:
            result["wind_shift"] = f"{compass_point(dirs[0])} to {compass_point(dirs[-1])}"

    # Visibility (metres -> km)
    vis_raw = series("visibility")
    vis_nums = numbers(vis_raw)
    if vis_nums:
        result["min_vis_km"] = min(vis_nums) / 1000
        result["poor_vis"] = result["min_vis_km"] < POOR_VISIBILITY_KM
    if vis_raw and is_number(vis_raw[0]):
        result["start_vis_km"] = vis_raw[0] / 1000

    # Weather codes
    codes = [int(c) for c in series("weather_code") if is_number(c) and int(c) == c]
    result["codes"] = codes
    sequence = []
    for c in codes:
        desc = weather_code_to_description(c)
        if desc == NOT_AVAILABLE:
            continue
        if not sequence or sequence[-1] != desc:
            sequence.append(desc)
    result["sequence"] = sequence

    return result


# =============================================================================
# ANALYSIS TEXT GENERATORS
# =============================================================================
def generate_outlook_bullets(a):
    if not a["available"]:
        return ["Hourly forecast data is not available for the next 24 hours."]

    events, fillers = [], []

    if a["strong_wind"]:
        events.append("Strong winds are possible, with maximum forecast wind speeds "
                      f"reaching approximately {a['max_wind']:.1f} km/h.")
    if a["poor_vis"]:
        events.append(f"Visibility may become poor, reaching approximately {a['min_vis_km']:.2f} km.")
    if is_number(a["snow_total"]) and a["snow_total"] > 0:
        events.append("Snowfall is forecast during the next 24 hours, with approximately "
                      f"{format_snowfall(a['snow_total'])} accumulated across the available hourly forecast.")
    if a["precip_any"]:
        text = ("Precipitation is forecast during the next 24 hours "
                f"(approximately {a['precip_total']:.2f} mm in total)")
        if is_number(a["max_prob"]):
            text += f", with the highest hourly probability reaching {a['max_prob']:.0f}%"
        events.append(text + ".")

    seq = a["sequence"]
    if len(seq) == 2:
        events.append(f"Conditions are forecast to change from {seq[0].lower()} to {seq[1].lower()}.")
    elif len(seq) > 2:
        shown = [s.lower() for s in seq[:4]]
        events.append("Conditions are forecast to change from " + shown[0]
                      + " to " + ", then ".join(shown[1:]) + ".")

    if a["trend"] in ("rise", "fall"):
        word = "rise" if a["trend"] == "rise" else "fall"
        events.append(f"The temperature is expected to {word} from approximately "
                      f"{a['temp_start']:.1f} °C to {a['temp_end']:.1f} °C.")
    if a["wind_shift"]:
        events.append(f"Wind direction is forecast to shift from {a['wind_shift']}.")

    # Factual fill-ins (only from available data)
    if a["trend"] == "stable":
        fillers.append("The temperature is expected to remain relatively stable.")
    if is_number(a["temp_min"]) and is_number(a["temp_max"]):
        fillers.append(f"Temperatures are forecast to range from {a['temp_min']:.1f} °C "
                       f"to {a['temp_max']:.1f} °C.")
    if is_number(a["max_wind"]) and not a["strong_wind"]:
        fillers.append(f"Wind speeds are forecast to reach up to {a['max_wind']:.1f} km/h.")
    if not a["precip_any"]:
        if is_number(a["max_prob"]) and a["max_prob"] > 0:
            fillers.append("Precipitation is possible during the forecast period, with the highest "
                           f"hourly probability reaching {a['max_prob']:.0f}%.")
        elif is_number(a["precip_total"]):
            fillers.append("No precipitation is forecast in the hourly data.")
    if is_number(a["min_vis_km"]) and not a["poor_vis"]:
        fillers.append(f"The lowest forecast visibility is approximately {a['min_vis_km']:.2f} km.")
    if is_number(a["snow_total"]) and a["snow_total"] == 0:
        fillers.append("No snowfall is forecast in the hourly data.")
    if len(seq) == 1:
        fillers.append(f"The forecast condition remains {seq[0].lower()} throughout the period.")

    bullets = ([STABLE_TEXT] + fillers) if not events else (events + fillers)
    bullets = bullets[:6]
    return bullets if bullets else ["Hourly forecast data is not available for the next 24 hours."]


def generate_tip(a):
    """Exactly one practical recommendation based strictly on the data."""
    if not a["available"]:
        return "Check the latest local conditions before travelling."
    if is_number(a["temp_min"]) and a["temp_min"] <= VERY_COLD_C:
        return "Warm, insulated clothing is recommended due to the low temperatures."
    if is_number(a["snow_total"]) and a["snow_total"] > 0:
        return "Winter footwear and warm outerwear are recommended due to forecast snowfall."
    if a["precip_any"]:
        return "Water-resistant outerwear is recommended due to the forecast precipitation."
    if a["strong_wind"]:
        return "Wind-resistant outerwear is recommended due to the forecast wind."
    if (is_number(a["temp_min"]) and is_number(a["precip_total"])
            and is_number(a["max_wind"])):
        return "Normal outdoor clothing should be suitable based on the available forecast."
    return "Check the latest local conditions before travelling."


def generate_weather_note(a, current_code):
    notes = []
    codes = list(a["codes"]) if a["available"] else []
    if is_number(current_code) and int(current_code) == current_code:
        codes.append(int(current_code))

    if a["available"]:
        if is_number(a["snow_total"]) and a["snow_total"] > 0:
            notes.append("Snowfall is forecast during the next 24 hours.")
        if a["precip_any"]:
            notes.append("Precipitation is forecast during the next 24 hours.")
        if a["strong_wind"]:
            notes.append(f"Strong winds are possible (up to approximately {a['max_wind']:.1f} km/h).")
        if a["poor_vis"]:
            notes.append(f"Visibility may become poor (down to approximately {a['min_vis_km']:.2f} km).")
        if len(a["sequence"]) >= 3:
            notes.append("Conditions are forecast to change several times during the period.")
    if any(c in FREEZING_CODES for c in codes):
        notes.append("Freezing drizzle or freezing rain appears in the forecast.")
    if any(c in THUNDER_CODES for c in codes):
        notes.append("Thunderstorm conditions appear in the forecast.")

    return " ".join(notes) if notes else NO_CONCERN_TEXT


def get_report_date(data):
    for value in (get_value(data, "current", "time"), get_value(data, "daily", "time", 0)):
        dt = parse_local(value)
        if dt is not None:
            return dt.strftime("%Y-%m-%d")
    if OSLO_TZ is not None:
        return datetime.now(OSLO_TZ).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def build_report(data, a, report_date):
    cur = lambda k: get_value(data, "current", k)
    day = lambda k: get_value(data, "daily", k, 0)   # FIRST daily entry = today
    return {
        "date": report_date,
        "temperature": safe_value(cur("temperature_2m"), 1, " °C"),
        "feels_like": safe_value(cur("apparent_temperature"), 1, " °C"),
        "condition": weather_code_to_description(cur("weather_code")),
        "humidity": safe_value(cur("relative_humidity_2m"), 0, "%"),
        "precipitation": safe_value(cur("precipitation"), 2, " mm"),
        "f_condition": weather_code_to_description(day("weather_code")),
        "high": safe_value(day("temperature_2m_max"), 1, " °C"),
        "low": safe_value(day("temperature_2m_min"), 1, " °C"),
        "precip_chance": safe_value(day("precipitation_probability_max"), 0, "%"),
        "snowfall": format_snowfall(a["snow_total"]),
        "max_wind": safe_value(day("wind_speed_10m_max"), 1, " km/h"),
        "wind_speed": safe_value(cur("wind_speed_10m"), 1, " km/h"),
        "wind_direction": degrees_to_direction(cur("wind_direction_10m")),
        "visibility": safe_value(a["start_vis_km"], 2, " km"),
        "sunrise": format_time(day("sunrise")),
        "sunset": format_time(day("sunset")),
        "bullets": generate_outlook_bullets(a),
        "tip": generate_tip(a),
        "note": generate_weather_note(a, cur("weather_code")),
    }


# =============================================================================
# EMAIL GENERATION
# =============================================================================
def generate_plain_text_email(r):
    lines = [
        "Good Morning,",
        "",
        "Here is today's weather update for Longyearbyen, Svalbard, Norway.",
        "",
        f"Date: {r['date']}",
        "",
        "📍 LOCATION",
        "",
        "Longyearbyen, Svalbard, Norway",
        "",
        "🌡️ CURRENT WEATHER",
        "",
        f"Temperature: {r['temperature']}",
        f"Feels Like: {r['feels_like']}",
        f"Condition: {r['condition']}",
        f"Humidity: {r['humidity']}",
        f"Precipitation: {r['precipitation']}",
        "",
        "🌤️ TODAY'S FORECAST",
        "",
        f"Condition: {r['f_condition']}",
        f"High: {r['high']}",
        f"Low: {r['low']}",
        f"Precipitation Chance: {r['precip_chance']}",
        f"Snowfall (next 24 hours): {r['snowfall']}",
        f"Maximum Wind: {r['max_wind']}",
        "",
        "💨 WIND",
        "",
        f"Speed: {r['wind_speed']}",
        f"Direction: {r['wind_direction']}",
        "",
        "👁️ VISIBILITY",
        "",
        r["visibility"],
        "",
        "🌅 SUN",
        "",
        f"Sunrise: {r['sunrise']}",
        f"Sunset: {r['sunset']}",
        "",
        "🔮 NEXT 24 HOURS",
        "",
    ]
    lines += [f"- {b}" for b in r["bullets"]]
    lines += [
        "",
        "🧥 CLOTHING / TRAVEL TIP",
        "",
        r["tip"],
        "",
        "📝 WEATHER NOTE",
        "",
        r["note"],
        "",
        "Data source: Open-Meteo. This report does not include official weather warnings.",
        "",
        "Have a great day! 🌍",
    ]
    return "\n".join(lines)


def _card(title, inner):
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;background-color:#f2f9fd;border:1px solid #cfe6f5;'
        'border-radius:12px;margin:0 0 14px 0;">'
        '<tr><td style="padding:14px 16px;">'
        f'<div style="font-size:13px;font-weight:bold;letter-spacing:0.6px;color:#2a6f97;'
        f'margin-bottom:8px;">{title}</div>{inner}</td></tr></table>'
    )


def _rows(pairs):
    body = "".join(
        '<tr><td style="padding:5px 0;color:#52606d;font-size:14px;">' + esc(label) + '</td>'
        '<td align="right" style="padding:5px 0;color:#1f2933;font-size:14px;font-weight:bold;">'
        + esc(value) + '</td></tr>'
        for label, value in pairs
    )
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            + body + '</table>')


def _text_block(text):
    return f'<div style="font-size:14px;line-height:1.5;color:#1f2933;">{esc(text)}</div>'


def generate_html_email(r):
    bullets_html = "".join(
        f'<li style="margin:0 0 6px 0;">{esc(b)}</li>' for b in r["bullets"]
    )
    outlook = ('<ul style="margin:0;padding-left:20px;font-size:14px;line-height:1.5;color:#1f2933;">'
               + bullets_html + '</ul>')

    cards = [
        _card("📍 LOCATION", _text_block("Longyearbyen, Svalbard, Norway")),
        _card("🌡️ CURRENT WEATHER", _rows([
            ("Temperature", r["temperature"]),
            ("Feels Like", r["feels_like"]),
            ("Condition", r["condition"]),
            ("Humidity", r["humidity"]),
            ("Precipitation", r["precipitation"]),
        ])),
        _card("🌤️ TODAY'S FORECAST", _rows([
            ("Condition", r["f_condition"]),
            ("High", r["high"]),
            ("Low", r["low"]),
            ("Precipitation Chance", r["precip_chance"]),
            ("Snowfall (next 24 hours)", r["snowfall"]),
            ("Maximum Wind", r["max_wind"]),
        ])),
        _card("💨 WIND", _rows([
            ("Speed", r["wind_speed"]),
            ("Direction", r["wind_direction"]),
        ])),
        _card("👁️ VISIBILITY", _text_block(r["visibility"])),
        _card("🌅 SUN", _rows([
            ("Sunrise", r["sunrise"]),
            ("Sunset", r["sunset"]),
        ])),
        _card("🔮 NEXT 24 HOURS", outlook),
        _card("🧥 CLOTHING / TRAVEL TIP", _text_block(r["tip"])),
        _card("📝 WEATHER NOTE", _text_block(r["note"])),
    ]

    header = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;background-color:#dff1fb;border-radius:14px;margin:0 0 16px 0;">'
        '<tr><td align="center" style="padding:22px 16px;">'
        '<div style="font-size:28px;">🌨️</div>'
        '<div style="font-size:22px;font-weight:bold;color:#12324a;margin-top:4px;">Daily Weather Update</div>'
        '<div style="font-size:15px;color:#2a6f97;margin-top:4px;">Longyearbyen, Svalbard, Norway</div>'
        f'<div style="font-size:13px;color:#52606d;margin-top:2px;">{esc(r["date"])}</div>'
        '</td></tr></table>'
    )

    greeting = (
        '<p style="margin:0 0 6px 0;font-size:15px;color:#1f2933;">Good Morning,</p>'
        '<p style="margin:0 0 16px 0;font-size:15px;line-height:1.5;color:#1f2933;">'
        "Here is today's weather update for Longyearbyen, Svalbard, Norway.</p>"
    )

    footer = (
        '<div style="text-align:center;padding:8px 0 0 0;">'
        '<div style="font-size:12px;color:#7b8794;line-height:1.5;">'
        'Data source: Open-Meteo. This report does not include official weather warnings.</div>'
        '<div style="font-size:15px;color:#12324a;margin-top:10px;font-weight:bold;">'
        'Have a great day! 🌍</div></div>'
    )

    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Daily Weather Update – Longyearbyen – {esc(r["date"])}</title></head>'
        '<body style="margin:0;padding:0;background-color:#ffffff;'
        'font-family:Arial,Helvetica,sans-serif;color:#1f2933;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#ffffff;"><tr><td align="center" style="padding:16px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:600px;"><tr><td>'
        + header + greeting + "".join(cards) + footer +
        '</td></tr></table></td></tr></table></body></html>'
    )


# =============================================================================
# SMTP
# =============================================================================
def smtp_config_is_valid():
    problems = []
    if (not isinstance(SENDER_EMAIL, str) or "@" not in SENDER_EMAIL
            or SENDER_EMAIL == "YOUR_GMAIL@gmail.com"):
        problems.append("SENDER_EMAIL has not been set to your real Gmail address.")
    if (not isinstance(SENDER_PASSWORD, str) or not SENDER_PASSWORD.strip()
            or SENDER_PASSWORD == "YOUR_GMAIL_APP_PASSWORD"):
        problems.append("SENDER_PASSWORD has not been set to your Gmail App Password.")
    if (not isinstance(RECIPIENT_EMAIL, str) or "@" not in RECIPIENT_EMAIL
            or RECIPIENT_EMAIL == "RECIPIENT_EMAIL@gmail.com"):
        problems.append("RECIPIENT_EMAIL has not been set to a real recipient address.")
    if not SMTP_SERVER or not isinstance(SMTP_PORT, int):
        problems.append("SMTP_SERVER / SMTP_PORT are invalid.")
    if problems:
        print("Error: Invalid SMTP configuration:")
        for p in problems:
            print(f" - {p}")
        return False
    return True


def send_email(subject, plain_text, html_content):
    """Send the multipart email through Gmail SMTP (SSL). Returns True on success."""
    def scrub(text):
        try:
            return str(text).replace(SENDER_PASSWORD, "********")
        except Exception:
            return "unknown error"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECIPIENT_EMAIL
        msg.attach(MIMEText(plain_text, "plain", "utf-8"))   # plain text first
        msg.attach(MIMEText(html_content, "html", "utf-8"))  # HTML second

        context = ssl.create_default_context()

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context, timeout=30) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(
                SENDER_EMAIL,
                RECIPIENT_EMAIL,
                msg.as_string()
            )
        return True
    except smtplib.SMTPAuthenticationError:
        print("Error: SMTP authentication failed. Check SENDER_EMAIL and that "
              "SENDER_PASSWORD is a valid Gmail App Password.")
    except smtplib.SMTPRecipientsRefused:
        print("Error: The recipient address was refused by the SMTP server.")
    except smtplib.SMTPConnectError as exc:
        print(f"Error: Could not connect to the SMTP server: {scrub(exc)}")
    except smtplib.SMTPException as exc:
        print(f"Error: SMTP error: {scrub(exc)}")
    except ssl.SSLError as exc:
        print(f"Error: SSL error while contacting the SMTP server: {scrub(exc)}")
    except TimeoutError:
        print("Error: The SMTP connection timed out.")
    except OSError as exc:
        print(f"Error: Network error while contacting the SMTP server: {scrub(exc)}")
    except Exception as exc:
        print(f"Error: Unexpected problem while sending the email: {scrub(exc)}")
    return False


# =============================================================================
# MAIN
# =============================================================================
def main():
    print("Longyearbyen Daily Weather Email Automation")

    if not smtp_config_is_valid():
        print("No email was sent.")
        return

    data = get_weather_data()
    if data is None:
        print("Weather data could not be retrieved. No email was sent.")
        return

    try:
        report_date = get_report_date(data)
        analysis = calculate_next_24_hours(data)
        report = build_report(data, analysis, report_date)
        subject = f"🌨️ Daily Weather Update – Longyearbyen, Svalbard – {report_date}"
        plain_text = generate_plain_text_email(report)
        html_content = generate_html_email(report)
    except Exception as exc:
        print(f"Error: Failed to prepare the weather email: {exc}")
        print("No email was sent.")
        return

    if not send_email(subject, plain_text, html_content):
        print("The email could not be sent.")
        return

    print(f"Weather email sent successfully to {RECIPIENT_EMAIL}")
    print(f"Location: {LOCATION_NAME}")
    print(f"Date: {report_date}")
    print(f"Current temperature: {report['temperature']}")
    print(f"Condition: {report['condition']}")
    print(f"Email recipient: {RECIPIENT_EMAIL}")


if __name__ == "__main__":
    main()
