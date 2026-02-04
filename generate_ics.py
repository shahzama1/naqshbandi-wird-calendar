#!/usr/bin/env python3
"""
Generate an iCalendar (.ics) feed for the Naqshbandi Wird schedule.

Fetches prayer times from AthanPlus for the next 6 months and produces
a subscribable .ics file with Pre-Fajr + 5 daily prayer/wird events.
"""

import os
import re
import sys
from datetime import datetime, timedelta

import pytz
import requests
from bs4 import BeautifulSoup

MASJID_ID = "RKxwV5dO"
BASE_URL = "https://timing.athanplus.com/masjid/widgets/monthly"
TIMEZONE = "America/Detroit"
TZ = pytz.timezone(TIMEZONE)
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "naqshbandi_wird.ics")
DAYS_AHEAD = 180

# Event definitions: (key, summary, offset_minutes_before_prayer, duration_minutes, alarm_minutes, prayer_key)
EVENTS = [
    ("prefajr",  "Pre-Fajr Programme",   60, 60, 10, "fajr"),
    ("fajr",     "Fajr + Wird Bite A",    0, 20,  5, "fajr"),
    ("dhuhr",    "Dhuhr + Wird Bite B",    0, 15,  5, "dhuhr"),
    ("asr",      "Asr + Wird Bite C",      0, 15,  5, "asr"),
    ("maghrib",  "Maghrib + Wird Bite D",  0, 15,  5, "maghrib"),
    ("isha",     "Isha + Wird Bite E",     0, 25,  5, "isha"),
]

WIRD_BITE_A = (
    "Wird Bite A (Post-Fajr):\\n"
    "- Ayat al-Kursi x1\\n"
    "- Tasbih Fatimi: SubhanAllah x33, Alhamdulillah x33, Allahu Akbar x34\\n"
    "- Istighfar x100: Astaghfirullah\\n"
    "- Salawat target: {salawat}x — Allahumma salli ala Sayyidina Muhammad"
)

WIRD_BITE_B = (
    "Wird Bite B (Post-Dhuhr):\\n"
    "- La ilaha illAllah x100\\n"
    "- Salawat x100: Allahumma salli ala Sayyidina Muhammad"
)

WIRD_BITE_C = (
    "Wird Bite C (Post-Asr):\\n"
    "- Surah Ya-Sin (recite or listen)\\n"
    "- Salawat x100: Allahumma salli ala Sayyidina Muhammad"
)

WIRD_BITE_D = (
    "Wird Bite D (Post-Maghrib):\\n"
    "- Surah al-Waqi'ah (recite or listen)\\n"
    "- Salawat x100: Allahumma salli ala Sayyidina Muhammad"
)

WIRD_BITE_E = (
    "Wird Bite E (Post-Isha):\\n"
    "- Surah al-Mulk (recite or listen)\\n"
    "- Khatm Khwajagan (weekly on Thursday night)\\n"
    "- Salawat x100: Allahumma salli ala Sayyidina Muhammad\\n"
    "- Muraqaba / Tafakkur 5-15 min"
)

PREFAJR_DESC = (
    "Pre-Fajr Programme:\\n"
    "- Tahajjud: 2-8 rakat\\n"
    "- Istighfar / Tawba\\n"
    "- Du'a — last third of the night"
)


def get_description(event_key, salawat):
    """Return the DESCRIPTION text for a given event key."""
    if event_key == "prefajr":
        return PREFAJR_DESC
    elif event_key == "fajr":
        return WIRD_BITE_A.format(salawat=salawat)
    elif event_key == "dhuhr":
        return WIRD_BITE_B
    elif event_key == "asr":
        return WIRD_BITE_C
    elif event_key == "maghrib":
        return WIRD_BITE_D
    elif event_key == "isha":
        return WIRD_BITE_E
    return ""


def fetch_month(year, month):
    """Fetch and parse prayer times for a given month from AthanPlus."""
    date_str = f"{year}-{month:02d}-01"
    url = f"{BASE_URL}?masjid_id={MASJID_ID}&theme=1&date={date_str}"
    print(f"  Fetching {year}-{month:02d} ...", end=" ")

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"FAILED: {e}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.find_all("tr")

    days = {}
    for row in rows:
        cells = row.find_all("td", class_="regCell")
        if len(cells) < 9:
            continue

        spans = []
        for cell in cells:
            span = cell.find("span")
            spans.append(span.get_text(strip=True) if span else cell.get_text(strip=True))

        # Columns: Day#, Hijri, Weekday, Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha
        try:
            day_num = int(spans[0])
        except (ValueError, IndexError):
            continue

        times = {}
        time_keys = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
        for i, key in enumerate(time_keys):
            raw = spans[3 + i].strip()
            times[key] = parse_prayer_time(raw, key)

        if all(v is not None for v in times.values()):
            days[day_num] = times

    print(f"OK ({len(days)} days)")
    return days


def parse_prayer_time(raw, prayer_key):
    """Parse a time string like '6:15' into (hour24, minute)."""
    match = re.match(r"(\d{1,2}):(\d{2})", raw)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))

    # Fajr and Sunrise are AM — no adjustment needed.
    # Dhuhr at 12:xx stays as-is.
    # Asr, Maghrib, Isha with hour < 12 need +12 for PM.
    if prayer_key in ("asr", "maghrib", "isha") and hour < 12:
        hour += 12

    return (hour, minute)


def collect_prayer_times():
    """Collect prayer times for today through today+DAYS_AHEAD."""
    today = datetime.now(TZ).date()
    end_date = today + timedelta(days=DAYS_AHEAD)

    # Determine which months to fetch
    months_to_fetch = set()
    d = today.replace(day=1)
    while d <= end_date:
        months_to_fetch.add((d.year, d.month))
        # Move to next month
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)

    # Fetch all months
    all_days = {}
    for year, month in sorted(months_to_fetch):
        month_days = fetch_month(year, month)
        for day_num, times in month_days.items():
            try:
                dt = datetime(year, month, day_num).date()
            except ValueError:
                continue
            if today <= dt <= end_date:
                all_days[dt] = times

    return all_days


def fmt_dt(dt):
    """Format a datetime as ICS local time string: YYYYMMDDTHHMMSS"""
    return dt.strftime("%Y%m%dT%H%M%S")


def fmt_utc(dt):
    """Format a datetime as ICS UTC time string."""
    utc_dt = dt.astimezone(pytz.utc)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


def fold_line(line):
    """Fold a content line per RFC 5545 (max 75 octets per line)."""
    result = []
    while len(line.encode("utf-8")) > 75:
        # Find a safe split point
        cut = 75
        while cut > 0 and len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        if cut == 0:
            cut = 1
        result.append(line[:cut])
        line = " " + line[cut:]
    result.append(line)
    return "\r\n".join(result)


def build_vtimezone():
    """Build a VTIMEZONE component for America/Detroit (EST/EDT)."""
    return (
        "BEGIN:VTIMEZONE\r\n"
        "TZID:America/Detroit\r\n"
        "X-LIC-LOCATION:America/Detroit\r\n"
        "BEGIN:DAYLIGHT\r\n"
        "TZOFFSETFROM:-0500\r\n"
        "TZOFFSETTO:-0400\r\n"
        "TZNAME:EDT\r\n"
        "DTSTART:19700308T020000\r\n"
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU\r\n"
        "END:DAYLIGHT\r\n"
        "BEGIN:STANDARD\r\n"
        "TZOFFSETFROM:-0400\r\n"
        "TZOFFSETTO:-0500\r\n"
        "TZNAME:EST\r\n"
        "DTSTART:19701101T020000\r\n"
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\r\n"
        "END:STANDARD\r\n"
        "END:VTIMEZONE"
    )


def build_vevent(date, event_key, summary, prayer_hour, prayer_min,
                 offset_min, duration_min, alarm_min, salawat):
    """Build a single VEVENT string."""
    # Compute start time
    start_dt = TZ.localize(datetime(date.year, date.month, date.day,
                                     prayer_hour, prayer_min))
    start_dt = start_dt - timedelta(minutes=offset_min)
    end_dt = start_dt + timedelta(minutes=duration_min)

    now_utc = datetime.now(pytz.utc)
    uid = f"{date.strftime('%Y%m%d')}-{event_key}@mcws-naqshbandi"
    description = get_description(event_key, salawat)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{fmt_utc(now_utc)}",
        f"DTSTART;TZID={TIMEZONE}:{fmt_dt(start_dt)}",
        f"DTEND;TZID={TIMEZONE}:{fmt_dt(end_dt)}",
        f"SUMMARY:{summary}",
    ]

    if description:
        lines.append(f"DESCRIPTION:{description}")

    # Alarm
    lines.extend([
        "BEGIN:VALARM",
        "TRIGGER:-PT{}M".format(alarm_min),
        "ACTION:DISPLAY",
        f"DESCRIPTION:Reminder: {summary}",
        "END:VALARM",
        "END:VEVENT",
    ])

    # Fold long lines
    folded = []
    for line in lines:
        folded.append(fold_line(line))

    return "\r\n".join(folded)


def generate_ics(all_days):
    """Generate the full ICS content."""
    header = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//MCWS//Naqshbandi Wird Schedule//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "X-WR-CALNAME:Naqshbandi Wird Schedule\r\n"
        "X-WR-TIMEZONE:America/Detroit"
    )

    parts = [header, build_vtimezone()]

    for date in sorted(all_days.keys()):
        times = all_days[date]
        # Mon=0, Thu=3, Fri=4 → salawat 300; else 100
        weekday = date.weekday()
        salawat = 300 if weekday in (0, 3, 4) else 100

        for event_key, summary, offset, duration, alarm, prayer_key in EVENTS:
            prayer_time = times.get(prayer_key)
            if prayer_time is None:
                continue
            hour, minute = prayer_time

            vevent = build_vevent(
                date, event_key, summary,
                hour, minute, offset, duration, alarm, salawat
            )
            parts.append(vevent)

    parts.append("END:VCALENDAR")
    return "\r\n".join(parts)


def main():
    print("Naqshbandi Wird ICS Generator")
    print("=" * 40)

    print("\nFetching prayer times...")
    all_days = collect_prayer_times()

    if not all_days:
        print("ERROR: No prayer times collected. Check network or URL.")
        sys.exit(1)

    print(f"\nCollected {len(all_days)} days of prayer times.")
    print(f"Date range: {min(all_days.keys())} to {max(all_days.keys())}")

    print("\nGenerating ICS...")
    ics_content = generate_ics(all_days)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(ics_content)

    total_events = len(all_days) * 6
    print(f"Written {OUTPUT_FILE}")
    print(f"Total events: {total_events}")

    # Quick sanity check
    first_date = min(all_days.keys())
    times = all_days[first_date]
    fajr = times["fajr"]
    print(f"\nSanity check — {first_date}:")
    print(f"  Fajr: {fajr[0]:02d}:{fajr[1]:02d}")
    print(f"  Pre-Fajr starts: {fajr[0]:02d}:{fajr[1]:02d} minus 60min")
    wd = first_date.weekday()
    sal = 300 if wd in (0, 3, 4) else 100
    print(f"  Day of week: {first_date.strftime('%A')} -> salawat target: {sal}")
    print("\nDone!")


if __name__ == "__main__":
    main()
