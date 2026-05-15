import os
import sys
import ssl
import smtplib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

IL_TZ = ZoneInfo("Asia/Jerusalem")

LAT, LON = 32.0853, 34.7818

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,"
    "precipitation_probability,precipitation,windspeed_10m,winddirection_10m,weathercode"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "precipitation_probability_max,windspeed_10m_max,winddirection_10m_dominant,weathercode"
    "&current_weather=true"
    "&timezone=Asia%2FJerusalem"
    "&forecast_days=1"
    "&wind_speed_unit=kmh"
)

AIR_QUALITY_URL = (
    "https://air-quality-api.open-meteo.com/v1/air-quality"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=us_aqi,pm2_5"
    "&timezone=Asia%2FJerusalem"
    "&forecast_days=1"
)

# WMO weather interpretation codes
WMO_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light rain showers", 81: "Moderate rain showers", 82: "Heavy rain showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

WMO_EMOJIS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    66: "🌧️", 67: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}

US_AQI_LEVELS = [
    (0, 50, "Good", "😊"),
    (51, 100, "Moderate", "😐"),
    (101, 150, "Unhealthy for Sensitive Groups", "😷"),
    (151, 200, "Unhealthy", "🤢"),
    (201, 300, "Very Unhealthy", "☠️"),
    (301, 500, "Hazardous", "☠️"),
]


# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)
    cfg = {
        "gmail_addr": os.getenv("GMAIL_ADDRESS"),
        "gmail_pass": os.getenv("GMAIL_APP_PASSWORD"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        print(f"[ERROR] Missing env vars: {', '.join(missing)}")
        print("        Copy .env.example to .env and fill in real values.")
        sys.exit(1)
    return cfg


# ── Helpers ───────────────────────────────────────────────────────────────────

def degrees_to_compass(deg):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(float(deg) / 22.5) % 16]


def wmo_to_description(code):
    return WMO_DESCRIPTIONS.get(int(code), "Unknown")


def wmo_to_emoji(code):
    return WMO_EMOJIS.get(int(code), "🌤️")


def us_aqi_to_level(aqi):
    aqi_val = int(aqi)
    for low, high, label, emoji in US_AQI_LEVELS:
        if low <= aqi_val <= high:
            return {"label": label, "emoji": emoji}
    return {"label": "Unknown", "emoji": "❓"}


# ── Weather fetching ──────────────────────────────────────────────────────────

def fetch_weather():
    r = requests.get(WEATHER_URL, timeout=10)
    r.raise_for_status()
    data = r.json()

    now_il    = datetime.now(IL_TZ)
    today_str = now_il.date().isoformat()
    now_hour  = now_il.hour

    h = data["hourly"]
    hourly_times = h["time"]  # e.g. ["2026-03-10T00:00", ...]

    # Find index of the current hour
    current_hour_str = f"{today_str}T{now_hour:02d}:00"
    try:
        cur_idx = hourly_times.index(current_hour_str)
    except ValueError:
        cur_idx = next((i for i, t in enumerate(hourly_times) if t.startswith(today_str)), 0)

    # Current conditions
    cw      = data["current_weather"]
    wmo_cur = int(cw["weathercode"])
    current = {
        "temp":        round(float(cw["temperature"]), 1),
        "feels_like":  round(float(h["apparent_temperature"][cur_idx]), 1),
        "humidity":    int(h["relative_humidity_2m"][cur_idx]),
        "description": wmo_to_description(wmo_cur),
        "emoji":       wmo_to_emoji(wmo_cur),
        "wind_kmh":    round(float(cw["windspeed"]), 1),
        "wind_dir":    degrees_to_compass(cw["winddirection"]),
    }

    # Daily summary (pre-aggregated by Open-Meteo)
    d        = data["daily"]
    wmo_day  = int(d["weathercode"][0])
    daily = {
        "temp_min":    round(float(d["temperature_2m_min"][0]), 1),
        "temp_max":    round(float(d["temperature_2m_max"][0]), 1),
        "max_pop_pct": int(d["precipitation_probability_max"][0]),
        "total_rain":  round(float(d["precipitation_sum"][0]), 1),
        "max_wind_kmh": round(float(d["windspeed_10m_max"][0]), 1),
        "wind_dir":    degrees_to_compass(d["winddirection_10m_dominant"][0]),
        "description": wmo_to_description(wmo_day),
    }

    # Today's hourly slots
    slots = []
    for i, time_str in enumerate(hourly_times):
        if not time_str.startswith(today_str):
            continue
        hour = int(time_str[11:13])
        wc   = int(h["weathercode"][i])
        slots.append({
            "hour_il":     hour,
            "time_label":  time_str[11:16],
            "temp":        round(float(h["temperature_2m"][i]), 1),
            "humidity":    int(h["relative_humidity_2m"][i]),
            "description": wmo_to_description(wc),
            "emoji":       wmo_to_emoji(wc),
            "wind_kmh":    round(float(h["windspeed_10m"][i]), 1),
            "wind_dir":    degrees_to_compass(h["winddirection_10m"][i]),
            "pop_pct":     int(h["precipitation_probability"][i]),   # 0–100
            "rain_mm":     round(float(h["precipitation"][i]), 1),   # mm/hr
        })

    return current, daily, slots


def fetch_air_quality():
    r = requests.get(AIR_QUALITY_URL, timeout=10)
    r.raise_for_status()
    data = r.json()

    now_il    = datetime.now(IL_TZ)
    today_str = now_il.date().isoformat()
    now_hour  = now_il.hour

    h = data["hourly"]
    hourly_times = h["time"]

    current_hour_str = f"{today_str}T{now_hour:02d}:00"
    try:
        cur_idx = hourly_times.index(current_hour_str)
    except ValueError:
        cur_idx = next((i for i, t in enumerate(hourly_times) if t.startswith(today_str)), 0)

    us_aqi = int(h["us_aqi"][cur_idx])
    level  = us_aqi_to_level(us_aqi)

    return {
        "us_aqi": us_aqi,
        "pm2_5": round(float(h["pm2_5"][cur_idx]), 1),
        "level_label": level["label"],
        "level_emoji": level["emoji"],
    }


# ── Hourly bucketing ──────────────────────────────────────────────────────────

def build_hourly_rows(slots):
    buckets = [
        ("Morning",   6,  12, "🌅"),
        ("Afternoon", 12, 18, "☀️"),
        ("Evening",   18, 24, "🌆"),
    ]
    rows = []
    for label, start, end, bucket_emoji in buckets:
        group = [s for s in slots if start <= s["hour_il"] < end]
        if not group:
            continue
        mid = (start + end) // 2
        rep = min(group, key=lambda s: abs(s["hour_il"] - mid))
        rows.append({
            "label":      label,
            "emoji":      bucket_emoji,
            "time_range": f"{start:02d}:00–{end:02d}:00",
            **rep,
        })
    return rows


# ── Email building ────────────────────────────────────────────────────────────

def build_html_email(current, daily, hourly_rows, date_str, air_quality):
    # Hourly table rows
    hr_html = ""
    for i, row in enumerate(hourly_rows):
        bg = "#ffffff" if i % 2 == 0 else "#f8f9fa"
        rain_cell = f"{row['pop_pct']}%"
        if row["rain_mm"] > 0:
            rain_cell += f" ({row['rain_mm']}mm)"
        hr_html += f"""
        <tr style="background:{bg};">
          <td style="padding:12px 14px;font-weight:600;white-space:nowrap;font-size:13px;color:#202124;">
            {row['emoji']} {row['label']}<br>
            <span style="font-weight:normal;color:#9aa0a6;font-size:11px;">{row['time_range']}</span>
          </td>
          <td style="padding:12px 14px;text-align:center;font-size:18px;font-weight:bold;color:#202124;">{row['temp']}°C</td>
          <td style="padding:12px 14px;text-align:center;font-size:13px;color:#5f6368;">
            {row['emoji']} {row['description']}
          </td>
          <td style="padding:12px 14px;text-align:center;font-size:13px;color:#1565c0;font-weight:600;">{rain_cell}</td>
          <td style="padding:12px 14px;text-align:center;font-size:13px;color:#6a1b9a;">{row['wind_kmh']} km/h {row['wind_dir']}</td>
        </tr>"""

    timestamp    = datetime.now(IL_TZ).strftime("%H:%M")
    rain_bar_pct = max(1, daily["max_pop_pct"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:20px;background:#f0f4f8;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center">
    <table width="600" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.12);" cellpadding="0" cellspacing="0">

      <!-- HEADER -->
      <tr>
        <td style="background:linear-gradient(135deg,#1a73e8,#0d47a1);color:#ffffff;padding:28px 32px;">
          <div style="font-size:24px;font-weight:700;margin:0;">🌍 Tel Aviv Weather Forecast</div>
          <div style="margin:6px 0 0;opacity:0.85;font-size:14px;">{date_str} &nbsp;·&nbsp; Generated at {timestamp} local time</div>
        </td>
      </tr>

      <!-- CURRENT CONDITIONS -->
      <tr>
        <td style="padding:24px 32px 8px;">
          <div style="font-size:15px;font-weight:700;color:#1a73e8;border-bottom:2px solid #e8f0fe;padding-bottom:8px;margin-bottom:16px;">
            🌡️ Current Conditions
          </div>
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr>
              <td style="width:70px;font-size:52px;vertical-align:middle;">{current['emoji']}</td>
              <td style="vertical-align:middle;">
                <div style="font-size:42px;font-weight:700;color:#202124;line-height:1;">{current['temp']}°C</div>
                <div style="color:#5f6368;font-size:14px;margin-top:4px;">
                  Feels like {current['feels_like']}°C &nbsp;·&nbsp; {current['description']}
                </div>
                <div style="color:#9aa0a6;font-size:13px;margin-top:2px;">
                  Humidity {current['humidity']}% &nbsp;·&nbsp; Wind {current['wind_kmh']} km/h {current['wind_dir']}
                </div>
                <div style="color:#5f6368;font-size:13px;margin-top:4px;">
                  Air quality {air_quality['level_emoji']} {air_quality['level_label']} &nbsp;·&nbsp;
                  US AQI {air_quality['us_aqi']} &nbsp;·&nbsp; PM2.5 {air_quality['pm2_5']} µg/m³
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- DAILY SUMMARY CARDS -->
      <tr>
        <td style="padding:16px 32px;">
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr>
              <!-- TEMPERATURE CARD -->
              <td width="31%" style="background:#e8f0fe;border-radius:10px;padding:16px;text-align:center;vertical-align:top;">
                <div style="font-size:11px;color:#5f6368;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Temperature</div>
                <div style="font-size:28px;font-weight:700;color:#202124;margin:8px 0 2px;">{daily['temp_max']}°</div>
                <div style="font-size:14px;color:#5f6368;">Low {daily['temp_min']}°</div>
                <div style="font-size:12px;color:#9aa0a6;margin-top:4px;">{daily['description']}</div>
              </td>
              <td width="4%"></td>
              <!-- RAIN CARD -->
              <td width="31%" style="background:#e3f2fd;border-radius:10px;padding:16px;text-align:center;vertical-align:top;">
                <div style="font-size:11px;color:#5f6368;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Rain</div>
                <div style="font-size:28px;font-weight:700;color:#1565c0;margin:8px 0 2px;">{daily['max_pop_pct']}%</div>
                <div style="font-size:14px;color:#5f6368;">{daily['total_rain']} mm expected</div>
                <div style="background:#bbdefb;border-radius:4px;height:6px;margin-top:10px;">
                  <div style="background:#1565c0;border-radius:4px;height:6px;width:{rain_bar_pct}%;"></div>
                </div>
              </td>
              <td width="4%"></td>
              <!-- WIND CARD -->
              <td width="31%" style="background:#f3e5f5;border-radius:10px;padding:16px;text-align:center;vertical-align:top;">
                <div style="font-size:11px;color:#5f6368;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Wind</div>
                <div style="font-size:28px;font-weight:700;color:#6a1b9a;margin:8px 0 2px;">{daily['max_wind_kmh']}</div>
                <div style="font-size:14px;color:#5f6368;">km/h max &nbsp;·&nbsp; {daily['wind_dir']}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- HOURLY BREAKDOWN -->
      <tr>
        <td style="padding:8px 32px 28px;">
          <div style="font-size:15px;font-weight:700;color:#1a73e8;border-bottom:2px solid #e8f0fe;padding-bottom:8px;margin-bottom:12px;">
            🕐 Hourly Breakdown
          </div>
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
            <thead>
              <tr style="background:#f8f9fa;">
                <th style="text-align:left;padding:10px 14px;font-size:11px;color:#9aa0a6;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #e0e0e0;">Period</th>
                <th style="text-align:center;padding:10px 14px;font-size:11px;color:#9aa0a6;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #e0e0e0;">Temp</th>
                <th style="text-align:center;padding:10px 14px;font-size:11px;color:#9aa0a6;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #e0e0e0;">Conditions</th>
                <th style="text-align:center;padding:10px 14px;font-size:11px;color:#9aa0a6;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #e0e0e0;">Rain</th>
                <th style="text-align:center;padding:10px 14px;font-size:11px;color:#9aa0a6;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #e0e0e0;">Wind</th>
              </tr>
            </thead>
            <tbody>
              {hr_html}
            </tbody>
          </table>
        </td>
      </tr>

      <!-- FOOTER -->
      <tr>
        <td style="background:#f8f9fa;border-top:1px solid #e0e0e0;padding:14px 32px;font-size:12px;color:#9aa0a6;text-align:center;">
          Data from Open-Meteo (open-meteo.com) &nbsp;·&nbsp; Tel Aviv (32.09°N, 34.78°E)
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


# ── Email sending ─────────────────────────────────────────────────────────────

def send_email(html, subject, cfg):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg["gmail_addr"]
    msg["To"]      = cfg["gmail_addr"]
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(cfg["gmail_addr"], cfg["gmail_pass"])
        smtp.sendmail(cfg["gmail_addr"], cfg["gmail_addr"], msg.as_string())
    print(f"[OK] Email sent to {cfg['gmail_addr']}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[INFO] Weather agent starting at {datetime.now(IL_TZ).isoformat()}")
    cfg = load_config()

    current, daily, slots = fetch_weather()
    air_quality = fetch_air_quality()

    if not slots:
        print("[ERROR] No hourly forecast data available for today. Exiting.")
        sys.exit(1)

    hourly_rows = build_hourly_rows(slots)
    date_str    = datetime.now(IL_TZ).strftime("%A, %B %-d %Y")
    html        = build_html_email(current, daily, hourly_rows, date_str, air_quality)
    subject     = (
        f"Tel Aviv Weather — {date_str} "
        f"| {daily['temp_min']}°/{daily['temp_max']}° "
        f"| Rain {daily['max_pop_pct']}% "
        f"| Wind {daily['max_wind_kmh']} km/h"
    )

    send_email(html, subject, cfg)


if __name__ == "__main__":
    main()
