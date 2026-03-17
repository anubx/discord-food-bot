"""
Discord Food Tracker Bot
- Private channels per user for meal photo uploads + personal tracking
- Group channel with leaderboard, rankings, and daily summaries
- Claude Vision for food photo macro/kcal analysis
- Text and voice message meal logging
- 6 meal windows with 4am day boundary
"""

import os
import re
import io
import base64
import logging
import sqlite3
import threading
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests as http_requests
import discord
from discord.ext import commands
import anthropic
from openai import OpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from PIL import Image
from pyzbar.pyzbar import decode as decode_barcodes

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROUP_CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])  # shared group channel
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Berlin")
SERVER_ID = int(os.environ.get("DISCORD_SERVER_ID", "0"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("foodbot")

# ---------------------------------------------------------------------------
# Meal windows — (start_hour, end_hour, label, emoji)
# A "day" runs from 04:00 to 03:59 next day.
# ---------------------------------------------------------------------------
MEAL_WINDOWS = [
    (8,  11, "Breakfast",       "🌅"),   # 08:00 – 10:59
    (11, 14, "Morning Snack",   "🍎"),   # 11:00 – 13:59
    (14, 17, "Lunch",           "🥗"),   # 14:00 – 16:59
    (17, 20, "Afternoon Snack", "🍌"),   # 17:00 – 19:59
    (20, 23, "Dinner",          "🍽️"),   # 20:00 – 22:59
    (23, 4,  "Evening Snack",   "🌙"),   # 23:00 – 03:59
]

REMINDER_HOURS = [(w[0], w[2], w[3]) for w in MEAL_WINDOWS]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "/app/data/foodbot.db")

def _ensure_db_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_db() -> sqlite3.Connection:
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id         TEXT PRIMARY KEY,
            target_kcal     INTEGER NOT NULL DEFAULT 2000,
            display_name    TEXT,
            private_channel INTEGER,
            is_premium      INTEGER NOT NULL DEFAULT 0,
            premium_since   TEXT,
            trial_started   TEXT,
            photo_count_today INTEGER NOT NULL DEFAULT 0,
            photo_count_day  TEXT
        );
        CREATE TABLE IF NOT EXISTS meals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            day_key     TEXT NOT NULL,
            window_idx  INTEGER NOT NULL,
            timestamp   TEXT NOT NULL,
            kcal        INTEGER NOT NULL,
            protein_g   REAL NOT NULL DEFAULT 0,
            carbs_g     REAL NOT NULL DEFAULT 0,
            fat_g       REAL NOT NULL DEFAULT 0,
            description TEXT,
            raw_analysis TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_meals_user_day ON meals(user_id, day_key);
    """)
    # Migration: add premium columns if they don't exist yet
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_settings)").fetchall()}
    migrations = {
        "is_premium": "ALTER TABLE user_settings ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0",
        "premium_since": "ALTER TABLE user_settings ADD COLUMN premium_since TEXT",
        "trial_started": "ALTER TABLE user_settings ADD COLUMN trial_started TEXT",
        "photo_count_today": "ALTER TABLE user_settings ADD COLUMN photo_count_today INTEGER NOT NULL DEFAULT 0",
        "photo_count_day": "ALTER TABLE user_settings ADD COLUMN photo_count_day TEXT",
    }
    for col, sql in migrations.items():
        if col not in existing_cols:
            conn.execute(sql)
            log.info("Migrated: added column %s to user_settings", col)
    conn.commit()
    conn.close()
    log.info("Database initialized at %s", DB_PATH)

# ---------------------------------------------------------------------------
# Time / window helpers
# ---------------------------------------------------------------------------
def now_tz() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))

def get_food_day(dt: datetime) -> str:
    if dt.hour < 4:
        dt = dt - timedelta(days=1)
    return dt.strftime("%Y-%m-%d")

def get_current_window_idx(dt: datetime) -> int:
    h = dt.hour
    if 4 <= h < 8:
        return -1
    if 8 <= h < 11:
        return 0
    if 11 <= h < 14:
        return 1
    if 14 <= h < 17:
        return 2
    if 17 <= h < 20:
        return 3
    if 20 <= h < 23:
        return 4
    return 5

def get_remaining_windows(dt: datetime) -> list[int]:
    h = dt.hour
    if h < 4:
        return [5]
    if 4 <= h < 8:
        return [0, 1, 2, 3, 4, 5]
    remaining = []
    for i, (start, end, _, _) in enumerate(MEAL_WINDOWS):
        if i < 5:
            if h < end:
                remaining.append(i)
        else:
            remaining.append(i)
    return remaining

def is_last_window(dt: datetime) -> bool:
    return get_current_window_idx(dt) == 5

# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------
def get_target_kcal(user_id: str) -> int | None:
    conn = get_db()
    row = conn.execute("SELECT target_kcal FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row["target_kcal"] if row else None

def set_target_kcal(user_id: str, kcal: int):
    conn = get_db()
    conn.execute(
        "INSERT INTO user_settings (user_id, target_kcal) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET target_kcal = ?",
        (user_id, kcal, kcal),
    )
    conn.commit()
    conn.close()

def get_user_private_channel(user_id: str) -> int | None:
    conn = get_db()
    row = conn.execute("SELECT private_channel FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row and row["private_channel"]:
        return row["private_channel"]
    return None

def set_user_private_channel(user_id: str, channel_id: int, display_name: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO user_settings (user_id, private_channel, display_name) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET private_channel = ?, display_name = ?",
        (user_id, channel_id, display_name, channel_id, display_name),
    )
    conn.commit()
    conn.close()

def get_all_tracked_channel_ids() -> set[int]:
    conn = get_db()
    rows = conn.execute("SELECT private_channel FROM user_settings WHERE private_channel IS NOT NULL").fetchall()
    conn.close()
    return {row["private_channel"] for row in rows}

def get_all_users() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM user_settings WHERE private_channel IS NOT NULL").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_by_channel(channel_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM user_settings WHERE private_channel = ?", (channel_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_meal(user_id: str, day_key: str, window_idx: int, kcal: int,
             protein: float, carbs: float, fat: float,
             description: str, raw_analysis: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO meals (user_id, day_key, window_idx, timestamp, kcal, protein_g, carbs_g, fat_g, description, raw_analysis) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, day_key, window_idx, now_tz().isoformat(), kcal, protein, carbs, fat, description, raw_analysis),
    )
    conn.commit()
    conn.close()

def get_day_meals(user_id: str, day_key: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM meals WHERE user_id = ? AND day_key = ? ORDER BY timestamp",
        (user_id, day_key),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_last_meal(user_id: str, day_key: str) -> dict | None:
    """Get the most recent meal for a user on a given day."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM meals WHERE user_id = ? AND day_key = ? ORDER BY timestamp DESC LIMIT 1",
        (user_id, day_key),
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def update_meal_full(meal_id: int, user_id: str, kcal: int, protein: float,
                     carbs: float, fat: float, description: str, raw_analysis: str) -> bool:
    """Update a meal's nutrition values and analysis text. Returns True if updated."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE meals SET kcal = ?, protein_g = ?, carbs_g = ?, fat_g = ?, description = ?, raw_analysis = ? "
        "WHERE id = ? AND user_id = ?",
        (kcal, protein, carbs, fat, description, raw_analysis, meal_id, user_id),
    )
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

def delete_meal(meal_id: int, user_id: str) -> bool:
    """Delete a meal by ID. Returns True if deleted."""
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM meals WHERE id = ? AND user_id = ?",
        (meal_id, user_id),
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted

def delete_last_meal(user_id: str, day_key: str) -> dict | None:
    """Delete the most recent meal for a user on a given day. Returns the deleted meal or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM meals WHERE user_id = ? AND day_key = ? ORDER BY timestamp DESC LIMIT 1",
        (user_id, day_key),
    ).fetchone()
    if row:
        conn.execute("DELETE FROM meals WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()
        return dict(row)
    conn.close()
    return None

def update_meal(meal_id: int, user_id: str, kcal: int, protein: float, carbs: float, fat: float) -> bool:
    """Update a meal's nutrition values. Returns True if updated."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE meals SET kcal = ?, protein_g = ?, carbs_g = ?, fat_g = ? WHERE id = ? AND user_id = ?",
        (kcal, protein, carbs, fat, meal_id, user_id),
    )
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

def get_day_totals(user_id: str, day_key: str) -> dict:
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(kcal),0) as total_kcal, "
        "COALESCE(SUM(protein_g),0) as total_protein, "
        "COALESCE(SUM(carbs_g),0) as total_carbs, "
        "COALESCE(SUM(fat_g),0) as total_fat, "
        "COUNT(*) as meal_count "
        "FROM meals WHERE user_id = ? AND day_key = ?",
        (user_id, day_key),
    ).fetchone()
    conn.close()
    return dict(row)

# ---------------------------------------------------------------------------
# Premium / subscription helpers
# ---------------------------------------------------------------------------
PREMIUM_PRICE = "$2.99/month"
DAILY_PHOTO_CAP = 8
TRIAL_DAYS = 7

def is_premium(user_id: str) -> bool:
    """Check if a user has an active premium subscription or trial."""
    conn = get_db()
    row = conn.execute(
        "SELECT is_premium, trial_started FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return False
    if row["is_premium"]:
        return True
    # Check trial
    trial = row["trial_started"]
    if trial:
        trial_dt = datetime.fromisoformat(trial)
        if (now_tz() - trial_dt).days < TRIAL_DAYS:
            return True
    return False

def get_trial_days_left(user_id: str) -> int | None:
    """Return remaining trial days, or None if no trial / expired."""
    conn = get_db()
    row = conn.execute(
        "SELECT trial_started, is_premium FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row or row["is_premium"]:
        return None
    trial = row["trial_started"]
    if not trial:
        return None
    elapsed = (now_tz() - datetime.fromisoformat(trial)).days
    remaining = TRIAL_DAYS - elapsed
    return remaining if remaining > 0 else None

def start_trial(user_id: str):
    """Start the 7-day free trial for a user."""
    conn = get_db()
    conn.execute(
        "UPDATE user_settings SET trial_started = ? WHERE user_id = ?",
        (now_tz().isoformat(), user_id),
    )
    conn.commit()
    conn.close()

def set_premium(user_id: str, active: bool):
    """Set or remove premium status for a user."""
    conn = get_db()
    conn.execute(
        "UPDATE user_settings SET is_premium = ?, premium_since = ? WHERE user_id = ?",
        (1 if active else 0, now_tz().isoformat() if active else None, user_id),
    )
    conn.commit()
    conn.close()

def check_photo_cap(user_id: str) -> tuple[bool, int]:
    """Check if user is under the daily photo cap. Returns (allowed, remaining)."""
    day_key = get_food_day(now_tz())
    conn = get_db()
    row = conn.execute(
        "SELECT photo_count_today, photo_count_day FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        conn.close()
        return True, DAILY_PHOTO_CAP

    count = row["photo_count_today"] or 0
    count_day = row["photo_count_day"] or ""

    # Reset if it's a new day
    if count_day != day_key:
        count = 0
        conn.execute(
            "UPDATE user_settings SET photo_count_today = 0, photo_count_day = ? WHERE user_id = ?",
            (day_key, user_id),
        )
        conn.commit()

    conn.close()
    remaining = DAILY_PHOTO_CAP - count
    return count < DAILY_PHOTO_CAP, max(0, remaining)

def increment_photo_count(user_id: str):
    """Increment the daily photo analysis counter."""
    day_key = get_food_day(now_tz())
    conn = get_db()
    conn.execute(
        "UPDATE user_settings SET photo_count_today = photo_count_today + 1, photo_count_day = ? WHERE user_id = ?",
        (day_key, user_id),
    )
    conn.commit()
    conn.close()

PREMIUM_UPSELL = f"""✨ **This is a Premium feature!**

Photo analysis, voice messages, barcode scanning, and meal corrections are part of **FoodTracker Pro** ({PREMIUM_PRICE}).

**What you get with Pro:**
📸 AI photo analysis (up to {DAILY_PHOTO_CAP}/day)
🎤 Voice message meal logging
📦 Barcode scanning with quantity modifiers
✏️ Reply-based meal corrections
🔄 Photo reanalysis (`!analyze`)

**Free tier includes:**
✍️ Unlimited text-based meal logging
🎯 Calorie budget tracking
🏆 Leaderboard & daily summaries
⏰ 6x daily reminders

Type `!trial` to start your **free {TRIAL_DAYS}-day trial** — no payment needed!"""

# ---------------------------------------------------------------------------
# AI clients
# ---------------------------------------------------------------------------
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

ANALYSIS_SYSTEM_PROMPT = """You are a nutrition analysis assistant. When given a photo of food, provide:

1. **Identified foods** — list every item you can see
2. **Estimated macros per item** (protein, carbs, fat in grams)
3. **Estimated calories per item**
4. **Meal totals** — sum of protein, carbs, fat, and total kcal

Be concise. Use a clean table format. If you're uncertain about portion sizes, state your assumptions (e.g., "assuming ~200g chicken breast"). Always give your best estimate rather than refusing.

IMPORTANT: At the very end of your response, include a single line in this exact format:
$$TOTALS: kcal=NUMBER, protein=NUMBER, carbs=NUMBER, fat=NUMBER$$

For example:
$$TOTALS: kcal=650, protein=45, carbs=60, fat=22$$

This line must contain only integers (no decimals). This is used for automated tracking."""


def parse_totals(analysis: str) -> dict:
    match = re.search(r'\$\$TOTALS:\s*kcal=(\d+),\s*protein=(\d+),\s*carbs=(\d+),\s*fat=(\d+)\$\$', analysis)
    if match:
        return {
            "kcal": int(match.group(1)),
            "protein": float(match.group(2)),
            "carbs": float(match.group(3)),
            "fat": float(match.group(4)),
        }
    kcal_match = re.search(r'(\d[,\d]*)\s*(?:kcal|calories|cal)\b', analysis, re.IGNORECASE)
    if kcal_match:
        kcal_str = kcal_match.group(1).replace(",", "")
        return {"kcal": int(kcal_str), "protein": 0, "carbs": 0, "fat": 0}
    return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}


def strip_totals_line(analysis: str) -> str:
    return re.sub(r'\n?\$\$TOTALS:.*?\$\$\n?', '', analysis).strip()


async def analyze_food_image(image_bytes: bytes, media_type: str = "image/jpeg") -> str:
    """Send a food photo to OpenAI GPT-4o Vision and return the macro breakdown."""
    if not openai_client:
        raise ValueError("OpenAI API key not configured. Add OPENAI_API_KEY to env vars.")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this meal photo. Estimate macros (protein, carbs, fat) and total calories.",
                    },
                ],
            },
        ],
    )
    # --- COST LOGGING ---
    u = response.usage
    cost = (u.prompt_tokens * 2.50 + u.completion_tokens * 10.00) / 1_000_000
    log.info(f"[COST] photo_analysis | in={u.prompt_tokens} out={u.completion_tokens} | ${cost:.6f}")
    # --- END COST LOGGING ---
    return response.choices[0].message.content


TEXT_ANALYSIS_SYSTEM_PROMPT = """You are a nutrition analysis assistant. The user will describe what they ate in text. Provide:

1. **Identified foods** — list every item mentioned
2. **Estimated macros per item** (protein, carbs, fat in grams)
3. **Estimated calories per item**
4. **Meal totals** — sum of protein, carbs, fat, and total kcal

Be concise. Use a clean table format. If the user doesn't specify portion sizes, assume typical serving sizes and state your assumptions.

IMPORTANT: At the very end of your response, include a single line in this exact format:
$$TOTALS: kcal=NUMBER, protein=NUMBER, carbs=NUMBER, fat=NUMBER$$

This line must contain only integers (no decimals). This is used for automated tracking."""


async def analyze_food_text(description: str) -> str:
    """Send a text description of food to Claude and return the macro breakdown."""
    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=TEXT_ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"I ate: {description}\n\nEstimate macros (protein, carbs, fat) and total calories.",
            }
        ],
    )
    # --- COST LOGGING ---
    u = message.usage
    cost = (u.input_tokens * 3.00 + u.output_tokens * 15.00) / 1_000_000
    log.info(f"[COST] text_analysis | in={u.input_tokens} out={u.output_tokens} | ${cost:.6f}")
    # --- END COST LOGGING ---
    return message.content[0].text


CORRECTION_SYSTEM_PROMPT = """You are a nutrition analysis assistant. The user previously received a meal analysis but wants to correct it.
You will be given:
1. The ORIGINAL analysis (what the bot previously said)
2. The user's CORRECTIONS (what they want to change)

Apply the user's corrections to the original analysis. For example:
- If they say "the steak is 200g not 300g", recalculate macros for a 200g steak
- If they say "the radish are tomatoes", replace radish with tomatoes and adjust macros
- If they say "the bread is corn", replace bread with corn and adjust macros
- If they say "remove the rice", remove that item entirely

Provide the corrected full analysis with:
1. **Corrected foods** — updated list
2. **Estimated macros per item** (protein, carbs, fat in grams)
3. **Estimated calories per item**
4. **Meal totals** — updated sum of protein, carbs, fat, and total kcal

Be concise. Use a clean table format.

IMPORTANT: At the very end of your response, include a single line in this exact format:
$$TOTALS: kcal=NUMBER, protein=NUMBER, carbs=NUMBER, fat=NUMBER$$

This line must contain only integers (no decimals). This is used for automated tracking."""


async def reevaluate_meal(original_analysis: str, corrections: str) -> str:
    """Send original analysis + user corrections to Claude and return updated breakdown."""
    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=CORRECTION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"ORIGINAL ANALYSIS:\n{original_analysis}\n\n"
                    f"MY CORRECTIONS:\n{corrections}\n\n"
                    "Please apply my corrections and provide the updated nutrition breakdown."
                ),
            }
        ],
    )
    # --- COST LOGGING ---
    u = message.usage
    cost = (u.input_tokens * 3.00 + u.output_tokens * 15.00) / 1_000_000
    log.info(f"[COST] correction | in={u.input_tokens} out={u.output_tokens} | ${cost:.6f}")
    # --- END COST LOGGING ---
    return message.content[0].text


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Transcribe audio using OpenAI Whisper API."""
    if not openai_client:
        raise ValueError("OpenAI API key not configured. Add OPENAI_API_KEY to env vars for voice message support.")

    # Write to temp file (Whisper API needs a file-like object with a name)
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        # Estimate audio duration from file size for cost logging
        # Discord voice messages are Ogg/Opus ~6KB/sec on average
        audio_size_bytes = len(audio_bytes)
        est_duration_sec = audio_size_bytes / 6000  # rough estimate
        with open(tmp_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        # --- COST LOGGING ---
        est_minutes = est_duration_sec / 60
        cost = est_minutes * 0.006
        log.info(f"[COST] whisper_transcription | ~{est_duration_sec:.1f}s (~{est_minutes:.2f}min) | size={audio_size_bytes}B | ${cost:.6f}")
        # --- END COST LOGGING ---
        return transcript.text
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Barcode scanning + Open Food Facts
# ---------------------------------------------------------------------------
def try_decode_barcode(image_bytes: bytes) -> str | None:
    """Try to decode a barcode from an image. Returns barcode string or None."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        barcodes = decode_barcodes(img)
        if barcodes:
            code = barcodes[0].data.decode("utf-8")
            log.info("Barcode detected: %s", code)
            return code
    except Exception as e:
        log.warning("Barcode decode failed: %s", e)
    return None


def lookup_barcode(barcode: str) -> dict | None:
    """Look up a product on Open Food Facts by barcode. Returns product info or None."""
    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
    try:
        resp = http_requests.get(url, timeout=10)
        data = resp.json()
        if data.get("status") != 1:
            return None
        product = data.get("product", {})
        nutriments = product.get("nutriments", {})

        # Get per-serving values if available, otherwise per 100g
        serving_size = product.get("serving_size", "")
        has_serving = bool(nutriments.get("energy-kcal_serving"))

        if has_serving:
            kcal = int(nutriments.get("energy-kcal_serving", 0))
            protein = float(nutriments.get("proteins_serving", 0))
            carbs = float(nutriments.get("carbohydrates_serving", 0))
            fat = float(nutriments.get("fat_serving", 0))
            portion_note = f"per serving ({serving_size})" if serving_size else "per serving"
        else:
            kcal = int(nutriments.get("energy-kcal_100g", 0))
            protein = float(nutriments.get("proteins_100g", 0))
            carbs = float(nutriments.get("carbohydrates_100g", 0))
            fat = float(nutriments.get("fat_100g", 0))
            portion_note = "per 100g"

        return {
            "name": product.get("product_name", "Unknown product"),
            "brand": product.get("brands", ""),
            "kcal": kcal,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "portion_note": portion_note,
            "image_url": product.get("image_url", ""),
            "barcode": barcode,
        }
    except Exception as e:
        log.warning("Open Food Facts lookup failed for %s: %s", barcode, e)
        return None


def parse_quantity_modifier(text: str) -> float | None:
    """Parse a quantity modifier from the user's message text.
    Returns a multiplier (e.g. 0.5 for 'half', 2.0 for '2 servings', etc.)
    or None if no modifier is detected."""
    if not text:
        return None
    text = text.strip().lower()

    # "half" / "1/2"
    if text in ("half", "1/2", "halbe", "halb"):
        return 0.5
    # "quarter" / "1/4"
    if text in ("quarter", "1/4", "viertel"):
        return 0.25
    # "third" / "1/3"
    if text in ("third", "1/3", "drittel"):
        return 1/3
    # "double" / "2x"
    if text in ("double", "2x", "doppelt"):
        return 2.0

    # "X servings" / "X portions"
    m = re.match(r'(\d+(?:\.\d+)?)\s*(?:servings?|portions?|stück|stk)', text)
    if m:
        return float(m.group(1))

    # "Xg" / "X g" — scale relative to 100g base
    m = re.match(r'(\d+(?:\.\d+)?)\s*g(?:rams?|ramm)?$', text)
    if m:
        return float(m.group(1)) / 100.0

    # "X ml" — treat same as grams for liquids (rough approximation)
    m = re.match(r'(\d+(?:\.\d+)?)\s*ml$', text)
    if m:
        return float(m.group(1)) / 100.0

    # "X spoons" / "X tablespoons" / "X teaspoons" / "X löffel"
    m = re.match(r'(\d+(?:\.\d+)?)\s*(?:spoons?|tablespoons?|tbsp|löffel|el)', text)
    if m:
        # ~15g per tablespoon
        return float(m.group(1)) * 15 / 100.0

    m = re.match(r'(\d+(?:\.\d+)?)\s*(?:teaspoons?|tsp|tl)', text)
    if m:
        # ~5g per teaspoon
        return float(m.group(1)) * 5 / 100.0

    # Plain number (e.g. "2" = 2 servings)
    m = re.match(r'^(\d+(?:\.\d+)?)$', text)
    if m:
        return float(m.group(1))

    # Use Claude to interpret complex quantities
    return None


async def interpret_quantity_with_ai(text: str, product_name: str, portion_note: str) -> float:
    """Use Claude to interpret a complex quantity description and return a multiplier."""
    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        system=(
            "You help convert food quantity descriptions into a numeric multiplier. "
            "The base unit is: " + portion_note + " of " + product_name + ". "
            "Return ONLY a single decimal number representing the multiplier. "
            "Examples: 'half' → 0.5, '2 servings' → 2.0, '50g' (if base is per 100g) → 0.5, "
            "'one spoon' (if base is per 100g) → 0.15. "
            "Return just the number, nothing else."
        ),
        messages=[{"role": "user", "content": text}],
    )
    # --- COST LOGGING ---
    u = message.usage
    cost = (u.input_tokens * 3.00 + u.output_tokens * 15.00) / 1_000_000
    log.info(f"[COST] quantity_interpret | in={u.input_tokens} out={u.output_tokens} | ${cost:.6f}")
    # --- END COST LOGGING ---
    try:
        return float(message.content[0].text.strip())
    except ValueError:
        return 1.0


def build_barcode_analysis(product: dict, multiplier: float = 1.0, quantity_text: str = "") -> str:
    """Build a display string + $$TOTALS$$ line from a barcode product lookup."""
    kcal = int(product["kcal"] * multiplier)
    protein = product["protein"] * multiplier
    carbs = product["carbs"] * multiplier
    fat = product["fat"] * multiplier

    lines = []
    name = product["name"]
    brand = product["brand"]
    if brand:
        lines.append(f"**{name}** ({brand})")
    else:
        lines.append(f"**{name}**")

    lines.append(f"📦 Barcode: `{product['barcode']}`")

    if quantity_text and multiplier != 1.0:
        lines.append(f"📏 Quantity: **{quantity_text}** ({multiplier:.2g}x of {product['portion_note']})\n")
    else:
        lines.append(f"📏 Nutrition {product['portion_note']}:\n")

    lines.append(f"| Nutrient | Amount |")
    lines.append(f"|----------|--------|")
    lines.append(f"| Calories | {kcal} kcal |")
    lines.append(f"| Protein | {protein:.1f}g |")
    lines.append(f"| Carbs | {carbs:.1f}g |")
    lines.append(f"| Fat | {fat:.1f}g |")
    lines.append(f"\n$$TOTALS: kcal={kcal}, protein={int(protein)}, carbs={int(carbs)}, fat={int(fat)}$$")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Budget / tracking helpers
# ---------------------------------------------------------------------------
def build_budget_text(user_id: str, day_key: str, dt: datetime) -> str:
    target = get_target_kcal(user_id)
    if target is None:
        return "⚠️ No calorie target set. Use `!target <kcal>` to set one."

    totals = get_day_totals(user_id, day_key)
    consumed = totals["total_kcal"]
    remaining = target - consumed

    if is_last_window(dt):
        return _build_end_of_day_text(target, consumed, remaining, totals)

    remaining_windows = get_remaining_windows(dt)
    current_idx = get_current_window_idx(dt)
    future_windows = [i for i in remaining_windows if i >= current_idx] if current_idx >= 0 else remaining_windows

    num_windows = len(future_windows)
    per_window = remaining // num_windows if num_windows > 0 and remaining > 0 else 0

    lines = []
    if remaining > 0:
        lines.append(f"**🔥 {remaining} kcal remaining today** (of {target} kcal target)")
    elif remaining == 0:
        lines.append(f"**✅ You've hit your {target} kcal target exactly!**")
    else:
        lines.append(f"**⚠️ {abs(remaining)} kcal over target** ({consumed} / {target} kcal)")

    lines.append(f"📊 Today so far: {totals['total_protein']:.0f}g P / {totals['total_carbs']:.0f}g C / {totals['total_fat']:.0f}g F")

    if remaining > 0 and num_windows > 0:
        lines.append(f"\n📅 **Budget per remaining window** (~{per_window} kcal each):")
        for i in future_windows:
            w = MEAL_WINDOWS[i]
            emoji = w[3]
            label = w[2]
            start_h = w[0]
            end_h = w[1]
            if i == 5:
                time_range = f"{start_h:02d}:00 – 03:59"
            else:
                time_range = f"{start_h:02d}:00 – {end_h-1:02d}:59"
            marker = " ◀️ *now*" if i == current_idx else ""
            lines.append(f"  {emoji} {label} ({time_range}): ~{per_window} kcal{marker}")

    return "\n".join(lines)


def _build_end_of_day_text(target: int, consumed: int, remaining: int, totals: dict) -> str:
    lines = []
    if remaining > 0:
        lines.append(f"**🌙 Last window — {remaining} kcal remaining** (of {target} kcal)")
    elif remaining == 0:
        lines.append(f"**✅ You've hit your {target} kcal target exactly!**")
    else:
        lines.append(f"**⚠️ {abs(remaining)} kcal over target!** ({consumed} / {target} kcal)")

    lines.append(f"📊 Today: {consumed} kcal | {totals['total_protein']:.0f}g P / {totals['total_carbs']:.0f}g C / {totals['total_fat']:.0f}g F")

    deficit = target - consumed
    if deficit > 0:
        fat_g = (deficit / 7700) * 1000
        lines.append(f"\n🔥 On track to exhale **{fat_g:.0f}g of body fat** today! Keep going.")
    elif deficit < 0:
        fat_g = (abs(deficit) / 7700) * 1000
        lines.append(f"\n📈 Surplus of {abs(deficit)} kcal (~{fat_g:.0f}g potential fat storage).")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Welcome / overview message
# ---------------------------------------------------------------------------
WELCOME_TEXT = """**🍽️ Welcome to FoodTracker!**

Track your meals, hit your calorie goals, and compete with friends.

**How it works:**
Log meals in your private channel using any of these methods:
📸 **Photo** — snap a pic of your food
📦 **Barcode** — photograph a product barcode for exact nutrition data
✍️ **Text** — type what you ate (e.g. "two eggs and toast")
🎤 **Voice** — send a voice message describing your meal

The bot analyzes everything for macros and calories automatically.

**Corrections:**
Reply to any nutrition breakdown with text or voice to correct it!
e.g. *"the steak is 200g not 300g, the radish are tomatoes"*

**Commands:**
`!join` — Create your private food tracking channel
`!target <kcal>` — Set your daily calorie target (e.g. `!target 2000`)
`!budget` — View your remaining calories for today
`!today` — See all meals you've logged today
`!undo` — Remove your last logged meal
`!delete <#>` — Delete a specific meal by number (see numbers with `!today`)
`!edit <#> kcal=X protein=X` — Edit a meal's values
`!analyze` — Reply to a food photo to (re-)analyze it
`!leaderboard` — See today's group rankings
`!schedule` — View the reminder schedule
`!pro` — View Pro features and your subscription status
`!trial` — Start a free 7-day Pro trial
`!commands` — Show this list again"""


def build_welcome_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🍽️  FoodTracker",
        description=WELCOME_TEXT,
        color=discord.Color.green(),
        timestamp=now_tz(),
    )
    return embed


# ---------------------------------------------------------------------------
# Leaderboard / group summary
# ---------------------------------------------------------------------------
def build_leaderboard(day_key: str) -> str:
    users = get_all_users()
    if not users:
        return "No users have joined yet. Use `!join` to get started!"

    entries = []
    for u in users:
        totals = get_day_totals(u["user_id"], day_key)
        target = u.get("target_kcal") or 0
        consumed = totals["total_kcal"]
        name = u.get("display_name") or f"User {u['user_id'][:8]}"
        remaining = target - consumed if target else None
        entries.append({
            "name": name,
            "consumed": consumed,
            "target": target,
            "remaining": remaining,
            "protein": totals["total_protein"],
            "carbs": totals["total_carbs"],
            "fat": totals["total_fat"],
            "meal_count": totals["meal_count"],
        })

    # Sort: who's closest to target (smallest remaining %, positive = under target)
    def sort_key(e):
        if e["target"] and e["target"] > 0:
            return abs(e["consumed"] - e["target"]) / e["target"]
        return 999
    entries.sort(key=sort_key)

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, e in enumerate(entries):
        medal = medals[i] if i < len(medals) else f"#{i+1}"
        if e["target"]:
            pct = (e["consumed"] / e["target"] * 100) if e["target"] > 0 else 0
            status = f"{e['consumed']}/{e['target']} kcal ({pct:.0f}%)"
        else:
            status = f"{e['consumed']} kcal (no target)"
        lines.append(f"{medal} **{e['name']}** — {status} | {e['meal_count']} meals | {e['protein']:.0f}P/{e['carbs']:.0f}C/{e['fat']:.0f}F")

    return "\n".join(lines)


def build_daily_summary_group(day_key: str) -> str:
    users = get_all_users()
    if not users:
        return "No meals logged yesterday."

    lines = [f"**📋 Daily Summary — {day_key}**\n"]

    entries = []
    for u in users:
        totals = get_day_totals(u["user_id"], day_key)
        target = u.get("target_kcal") or 0
        consumed = totals["total_kcal"]
        name = u.get("display_name") or f"User {u['user_id'][:8]}"
        diff = target - consumed if target else 0
        entries.append({"name": name, "consumed": consumed, "target": target, "diff": diff, "totals": totals})

    # Sort by deficit (biggest deficit first = most fat burned)
    entries.sort(key=lambda e: e["diff"], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    for i, e in enumerate(entries):
        medal = medals[i] if i < len(medals) else f"#{i+1}"
        t = e["totals"]
        if e["target"]:
            if e["diff"] > 0:
                fat_g = (e["diff"] / 7700) * 1000
                result = f"✅ Deficit {e['diff']} kcal — exhaled ~{fat_g:.0f}g body fat"
            elif e["diff"] == 0:
                result = "✅ Hit target exactly"
            else:
                fat_g = (abs(e["diff"]) / 7700) * 1000
                result = f"⚠️ Surplus {abs(e['diff'])} kcal (~{fat_g:.0f}g storage)"
        else:
            result = "No target set"

        lines.append(f"{medal} **{e['name']}** — {e['consumed']} kcal | {t['total_protein']:.0f}P/{t['total_carbs']:.0f}C/{t['total_fat']:.0f}F")
        lines.append(f"    {result}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------------------------------------------------------------------
# Reminder messages
# ---------------------------------------------------------------------------
def build_reminder_embed(label: str, emoji: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{emoji}  Time to log your {label}!",
        description="Snap a photo of your meal and post it in your private channel.",
        color=discord.Color.green(),
        timestamp=now_tz(),
    )
    embed.set_footer(text="Post a food photo to get your breakdown")
    return embed


async def send_reminders(label: str, emoji: str):
    """Send reminders to each user's private channel."""
    users = get_all_users()
    embed = build_reminder_embed(label, emoji)
    for u in users:
        ch_id = u.get("private_channel")
        if ch_id:
            channel = bot.get_channel(ch_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    log.warning("Failed to send reminder to channel %s: %s", ch_id, e)
    log.info("Sent %s reminders to %d users", label, len(users))


async def send_daily_summary():
    """4am: send personal summaries to private channels + group summary to group channel."""
    dt = now_tz()
    prev_day = (dt - timedelta(days=1)).strftime("%Y-%m-%d")

    users = get_all_users()
    if not users:
        log.info("No users, skipping daily summary")
        return

    # Send personal summaries to private channels
    for u in users:
        ch_id = u.get("private_channel")
        if not ch_id:
            continue
        channel = bot.get_channel(ch_id)
        if not channel:
            continue

        user_id = u["user_id"]
        totals = get_day_totals(user_id, prev_day)
        meals = get_day_meals(user_id, prev_day)
        target = u.get("target_kcal")
        consumed = totals["total_kcal"]

        lines = [f"**📋 Your Daily Summary — {prev_day}**\n"]
        if target:
            diff = target - consumed
            lines.append(f"🎯 Target: {target} kcal | Consumed: {consumed} kcal")
            if diff > 0:
                fat_g = (diff / 7700) * 1000
                lines.append(f"✅ **Deficit: {diff} kcal**")
                lines.append(f"🔥 You exhaled approximately **{fat_g:.0f}g of body fat** yesterday!")
            elif diff == 0:
                lines.append(f"✅ **Hit your target exactly!**")
            else:
                fat_g = (abs(diff) / 7700) * 1000
                lines.append(f"⚠️ **Surplus: {abs(diff)} kcal** (~{fat_g:.0f}g potential fat storage)")
        else:
            lines.append(f"Total consumed: {consumed} kcal (no target set)")

        lines.append(f"\n📊 {totals['total_protein']:.0f}g P / {totals['total_carbs']:.0f}g C / {totals['total_fat']:.0f}g F")
        lines.append(f"🍽️ {totals['meal_count']} meals logged")

        if meals:
            lines.append("\n**Meals:**")
            for m in meals:
                w = MEAL_WINDOWS[m["window_idx"]]
                ts = datetime.fromisoformat(m["timestamp"]).strftime("%H:%M")
                lines.append(f"  {w[3]} {ts} — {m['kcal']} kcal")

        embed = discord.Embed(
            title="🌅  Daily Summary",
            description="\n".join(lines),
            color=discord.Color.purple(),
            timestamp=dt,
        )
        try:
            await channel.send(embed=embed)
        except Exception as e:
            log.warning("Failed to send summary to %s: %s", ch_id, e)

    # Send group leaderboard to the group channel
    group_channel = bot.get_channel(GROUP_CHANNEL_ID)
    if group_channel:
        group_text = build_daily_summary_group(prev_day)
        embed = discord.Embed(
            title="🏆  Yesterday's Leaderboard",
            description=group_text,
            color=discord.Color.gold(),
            timestamp=dt,
        )
        await group_channel.send(embed=embed)

    log.info("Sent daily summaries for %s", prev_day)


async def send_morning_overview():
    """8am: send welcome/overview to group channel."""
    group_channel = bot.get_channel(GROUP_CHANNEL_ID)
    if group_channel:
        await group_channel.send(embed=build_welcome_embed())
        log.info("Sent morning overview to group channel")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    init_db()

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Meal reminders to private channels
    for hour, label, emoji in REMINDER_HOURS:
        scheduler.add_job(
            send_reminders,
            CronTrigger(hour=hour, minute=0, timezone=TIMEZONE),
            args=[label, emoji],
            id=f"reminder_{hour}",
            replace_existing=True,
        )
        log.info("Scheduled %s reminder at %02d:00 %s", label, hour, TIMEZONE)

    # 4am daily summary
    scheduler.add_job(
        send_daily_summary,
        CronTrigger(hour=4, minute=0, timezone=TIMEZONE),
        id="daily_summary",
        replace_existing=True,
    )
    log.info("Scheduled daily summary at 04:00 %s", TIMEZONE)

    # 8am morning overview in group channel
    scheduler.add_job(
        send_morning_overview,
        CronTrigger(hour=8, minute=0, timezone=TIMEZONE),
        id="morning_overview",
        replace_existing=True,
    )
    log.info("Scheduled morning overview at 08:00 %s", TIMEZONE)

    scheduler.start()


@bot.event
async def on_member_join(member: discord.Member):
    """When someone joins the server, post the welcome overview in the group channel."""
    group_channel = bot.get_channel(GROUP_CHANNEL_ID)
    if group_channel:
        embed = build_welcome_embed()
        await group_channel.send(f"Welcome {member.mention}!", embed=embed)
        log.info("Sent welcome message for %s", member)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    log.info(
        "Message in #%s (id=%s) from %s | attachments=%s | content_len=%s",
        message.channel.name, message.channel.id, message.author,
        len(message.attachments), len(message.content),
    )

    # Check if this is a tracked private channel
    tracked_channels = get_all_tracked_channel_ids()
    is_private_channel = message.channel.id in tracked_channels

    if is_private_channel:
        # Skip if it looks like a command
        if message.content.startswith("!"):
            await bot.process_commands(message)
            return

        user_id = str(message.author.id)
        user_is_premium = is_premium(user_id)

        # --- REPLY-BASED CORRECTION (Premium) ---
        # If user replies to a bot's Nutrition Breakdown embed, treat as correction
        if message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            is_correction_reply = (
                ref_msg.author == bot.user
                and ref_msg.embeds
                and any("Nutrition Breakdown" in (e.title or "") for e in ref_msg.embeds)
            )
            if is_correction_reply:
                if not user_is_premium:
                    await _send_premium_upsell(message, "Meal corrections")
                    await bot.process_commands(message)
                    return
                await _handle_correction(message)
                await bot.process_commands(message)
                return

        # Determine input type
        image_attachments = []
        audio_attachments = []
        for att in message.attachments:
            fname = att.filename.lower()
            if any(fname.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                image_attachments.append(att)
            elif any(fname.endswith(ext) for ext in (".ogg", ".mp3", ".wav", ".m4a", ".mp4", ".webm")):
                audio_attachments.append(att)

        has_text = bool(message.content.strip())
        has_images = bool(image_attachments)
        has_audio = bool(audio_attachments)

        # --- IMAGE INPUT (Premium) ---
        if has_images:
            if not user_is_premium:
                await _send_premium_upsell(message, "Photo analysis")
                await bot.process_commands(message)
                return
            # Check daily photo cap
            allowed, remaining = check_photo_cap(user_id)
            if not allowed:
                await message.reply(f"📸 You've hit your daily photo limit ({DAILY_PHOTO_CAP}/day). Try logging via text instead, or wait until tomorrow!\n\n*Your limit resets at 4am.*")
                await bot.process_commands(message)
                return
            for attachment in image_attachments:
                log.info("Food photo from %s: %s", message.author, attachment.filename)
                async with message.channel.typing():
                    try:
                        image_bytes = await attachment.read()

                        # Try barcode first
                        barcode = try_decode_barcode(image_bytes)
                        if barcode:
                            product = lookup_barcode(barcode)
                            if product:
                                # Check for quantity modifier in the message text
                                qty_text = message.content.strip()
                                multiplier = 1.0
                                if qty_text:
                                    multiplier = parse_quantity_modifier(qty_text)
                                    if multiplier is None:
                                        # Complex text — use AI to interpret
                                        multiplier = await interpret_quantity_with_ai(
                                            qty_text, product["name"], product["portion_note"]
                                        )
                                    log.info("Quantity modifier: '%s' → %sx", qty_text, multiplier)

                                analysis = build_barcode_analysis(product, multiplier, qty_text)
                                thumb = product.get("image_url") or attachment.url
                                await _process_meal_analysis(
                                    message, analysis,
                                    f"barcode: {barcode} ({product['name']}) x{multiplier:.2g}",
                                    thumbnail_url=thumb,
                                )
                                increment_photo_count(user_id)
                                continue
                            else:
                                await message.reply(f"📦 Barcode `{barcode}` detected but not found in Open Food Facts. Analyzing the image instead...")

                        # No barcode (or barcode not found) — use OpenAI Vision
                        ext = attachment.filename.rsplit(".", 1)[-1].lower()
                        media_map = {
                            "png": "image/png", "jpg": "image/jpeg",
                            "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
                        }
                        media_type = media_map.get(ext, "image/jpeg")

                        analysis = await analyze_food_image(image_bytes, media_type)
                        await _process_meal_analysis(
                            message, analysis, attachment.filename,
                            thumbnail_url=attachment.url,
                        )
                        increment_photo_count(user_id)
                    except Exception as e:
                        log.exception("Error analyzing image")
                        await message.reply(f"⚠️ Couldn't analyze that image: {e}")

        # --- AUDIO / VOICE MESSAGE INPUT (Premium) ---
        elif has_audio:
            if not user_is_premium:
                await _send_premium_upsell(message, "Voice message logging")
                await bot.process_commands(message)
                return
            attachment = audio_attachments[0]
            log.info("Voice message from %s: %s", message.author, attachment.filename)
            async with message.channel.typing():
                try:
                    audio_bytes = await attachment.read()
                    transcript = await transcribe_audio(audio_bytes, attachment.filename)
                    log.info("Transcribed voice: %s", transcript)

                    # Show transcription
                    await message.reply(f"🎤 *\"{transcript}\"*")

                    # Analyze the transcribed text
                    analysis = await analyze_food_text(transcript)
                    await _process_meal_analysis(
                        message, analysis, f"voice: {transcript[:50]}",
                    )
                except Exception as e:
                    log.exception("Error processing voice message")
                    await message.reply(f"⚠️ Couldn't process voice message: {e}")

        # --- TEXT INPUT ---
        elif has_text:
            text = message.content.strip()
            # Only analyze if it looks like a food description (at least 3 chars)
            if len(text) >= 3:
                log.info("Text meal from %s: %s", message.author, text[:80])
                async with message.channel.typing():
                    try:
                        analysis = await analyze_food_text(text)
                        await _process_meal_analysis(
                            message, analysis, f"text: {text[:50]}",
                        )
                    except Exception as e:
                        log.exception("Error analyzing text meal")
                        await message.reply(f"⚠️ Couldn't analyze that: {e}")

    await bot.process_commands(message)


async def _process_meal_analysis(
    message: discord.Message,
    analysis: str,
    description: str,
    thumbnail_url: str | None = None,
):
    """Shared logic: parse totals, store meal, send embeds to private + group channel."""
    parsed = parse_totals(analysis)
    display_text = strip_totals_line(analysis)

    dt = now_tz()
    day_key = get_food_day(dt)
    window_idx = get_current_window_idx(dt)
    if window_idx < 0:
        window_idx = 0

    user_id = str(message.author.id)
    add_meal(
        user_id, day_key, window_idx,
        parsed["kcal"], parsed["protein"], parsed["carbs"], parsed["fat"],
        description, analysis,
    )
    log.info("Stored meal: %s kcal for user %s on %s (window %d)",
             parsed["kcal"], user_id, day_key, window_idx)

    # Nutrition breakdown in private channel
    embed = discord.Embed(
        title="📊  Nutrition Breakdown",
        description=display_text,
        color=discord.Color.blue(),
        timestamp=dt,
    )
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    embed.set_footer(text=f"Analyzed for {message.author.display_name}")
    await message.reply(embed=embed)

    # Budget update
    budget_text = build_budget_text(user_id, day_key, dt)
    budget_embed = discord.Embed(
        title="🎯  Daily Budget",
        description=budget_text,
        color=discord.Color.gold(),
        timestamp=dt,
    )
    await message.channel.send(embed=budget_embed)

    # Post to group channel
    group_channel = bot.get_channel(GROUP_CHANNEL_ID)
    if group_channel:
        totals = get_day_totals(user_id, day_key)
        target = get_target_kcal(user_id)
        summary_line = f"**{message.author.display_name}** logged a meal: **{parsed['kcal']} kcal** ({parsed['protein']:.0f}P / {parsed['carbs']:.0f}C / {parsed['fat']:.0f}F)"
        if target:
            remaining = target - totals["total_kcal"]
            if remaining > 0:
                summary_line += f"\n📊 {totals['total_kcal']}/{target} kcal today — {remaining} remaining"
            else:
                summary_line += f"\n⚠️ {totals['total_kcal']}/{target} kcal today — {abs(remaining)} over target"

        group_embed = discord.Embed(
            description=summary_line,
            color=discord.Color.blue(),
            timestamp=dt,
        )
        if thumbnail_url:
            group_embed.set_thumbnail(url=thumbnail_url)
        await group_channel.send(embed=group_embed)


async def _send_premium_upsell(message: discord.Message, feature_name: str):
    """Send a premium upsell embed when a free user tries a premium feature."""
    embed = discord.Embed(
        title=f"✨  {feature_name} — Premium Feature",
        description=PREMIUM_UPSELL,
        color=discord.Color.purple(),
        timestamp=now_tz(),
    )
    trial_left = get_trial_days_left(str(message.author.id))
    if trial_left is not None:
        embed.set_footer(text=f"Trial: {trial_left} days remaining")
    await message.reply(embed=embed)


async def _handle_correction(message: discord.Message):
    """Handle a reply-based correction to a previous meal analysis."""
    user_id = str(message.author.id)
    dt = now_tz()
    day_key = get_food_day(dt)

    # Get correction text from text or voice
    correction_text = ""
    audio_attachments = [
        a for a in message.attachments
        if any(a.filename.lower().endswith(ext) for ext in (".ogg", ".mp3", ".wav", ".m4a", ".mp4", ".webm"))
    ]

    if audio_attachments:
        # Transcribe voice correction
        async with message.channel.typing():
            try:
                audio_bytes = await audio_attachments[0].read()
                correction_text = await transcribe_audio(audio_bytes, audio_attachments[0].filename)
                await message.reply(f"🎤 *\"{correction_text}\"*")
            except Exception as e:
                log.exception("Error transcribing correction audio")
                await message.reply(f"⚠️ Couldn't transcribe voice message: {e}")
                return
    elif message.content.strip():
        correction_text = message.content.strip()
    else:
        await message.reply("Please include your corrections as text or a voice message when replying to a meal analysis.")
        return

    log.info("Correction from %s: %s", message.author, correction_text[:80])

    # Find the most recent meal to correct
    last_meal = get_last_meal(user_id, day_key)
    if not last_meal:
        # Try yesterday (in case near day boundary)
        prev_day = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        last_meal = get_last_meal(user_id, prev_day)

    if not last_meal:
        await message.reply("⚠️ No recent meal found to correct. Log a meal first!")
        return

    original_analysis = last_meal.get("raw_analysis", "")
    if not original_analysis:
        await message.reply("⚠️ No original analysis data found for the last meal. Try `!edit` instead.")
        return

    # Send to Claude for re-evaluation
    async with message.channel.typing():
        try:
            updated_analysis = await reevaluate_meal(original_analysis, correction_text)
            parsed = parse_totals(updated_analysis)
            display_text = strip_totals_line(updated_analysis)

            # Update the meal in the database
            old_kcal = last_meal["kcal"]
            meal_desc = last_meal.get("description", "")
            updated = update_meal_full(
                last_meal["id"], user_id,
                parsed["kcal"], parsed["protein"], parsed["carbs"], parsed["fat"],
                f"{meal_desc} (corrected: {correction_text[:100]})",
                updated_analysis,
            )

            if not updated:
                await message.reply("⚠️ Couldn't update the meal in the database.")
                return

            # Send corrected breakdown
            embed = discord.Embed(
                title="✏️  Corrected Nutrition Breakdown",
                description=display_text,
                color=discord.Color.orange(),
                timestamp=dt,
            )
            embed.set_footer(text=f"Corrected for {message.author.display_name} | was {old_kcal} kcal")
            await message.reply(embed=embed)

            # Updated budget
            budget_text = build_budget_text(user_id, day_key, dt)
            budget_embed = discord.Embed(
                title="🎯  Updated Daily Budget",
                description=budget_text,
                color=discord.Color.gold(),
                timestamp=dt,
            )
            await message.channel.send(embed=budget_embed)

            log.info("Corrected meal #%s: %s → %s kcal for user %s",
                     last_meal["id"], old_kcal, parsed["kcal"], user_id)

        except Exception as e:
            log.exception("Error processing correction")
            await message.reply(f"⚠️ Couldn't process correction: {e}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@bot.command(name="join")
async def cmd_join(ctx: commands.Context):
    """Create your private food tracking channel."""
    user_id = str(ctx.author.id)

    # Check if already has a channel
    existing = get_user_private_channel(user_id)
    if existing:
        channel = bot.get_channel(existing)
        if channel:
            await ctx.reply(f"You already have a private channel: {channel.mention}")
            return

    guild = ctx.guild
    if not guild:
        await ctx.reply("This command must be used in a server.")
        return

    # Create private channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.author: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, embed_links=True,
        ),
    }

    channel_name = f"food-{ctx.author.display_name.lower().replace(' ', '-')[:20]}"
    try:
        new_channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            reason=f"FoodTracker private channel for {ctx.author}",
        )
    except discord.Forbidden:
        await ctx.reply("⚠️ I don't have permission to create channels. Please give me the **Manage Channels** permission.")
        return

    set_user_private_channel(user_id, new_channel.id, ctx.author.display_name)

    # Set default target if not set
    if get_target_kcal(user_id) is None:
        set_target_kcal(user_id, 2000)

    # Send welcome in the new private channel
    welcome = discord.Embed(
        title=f"🍽️  Welcome, {ctx.author.display_name}!",
        description=(
            "This is your private food tracking channel.\n\n"
            "**Post a food photo** here and I'll analyze it for macros & calories.\n\n"
            f"Your daily target is **2000 kcal** (change with `!target <kcal>`).\n\n"
            "Reminders will appear here at each meal window. Let's go!"
        ),
        color=discord.Color.green(),
        timestamp=now_tz(),
    )
    await new_channel.send(embed=welcome)

    # Confirm in group channel
    await ctx.reply(f"✅ Your private channel is ready: {new_channel.mention}\nPost food photos there to start tracking!")

    # Send updated overview to group channel
    group_channel = bot.get_channel(GROUP_CHANNEL_ID)
    if group_channel and group_channel.id != ctx.channel.id:
        await group_channel.send(
            f"🎉 **{ctx.author.display_name}** joined FoodTracker!",
            embed=build_welcome_embed(),
        )


@bot.command(name="target")
async def cmd_target(ctx: commands.Context, kcal: int = None):
    """Set or view your daily calorie target."""
    user_id = str(ctx.author.id)
    if kcal is None:
        current = get_target_kcal(user_id)
        if current:
            await ctx.reply(f"🎯 Your daily target is **{current} kcal**. Use `!target <number>` to change it.")
        else:
            await ctx.reply("No target set yet. Use `!target <number>` to set your daily calorie goal.")
        return

    if kcal < 500 or kcal > 10000:
        await ctx.reply("Please set a target between 500 and 10,000 kcal.")
        return

    set_target_kcal(user_id, kcal)
    await ctx.reply(f"✅ Daily calorie target set to **{kcal} kcal**.")


@bot.command(name="budget")
async def cmd_budget(ctx: commands.Context):
    """Show your remaining calorie budget for today."""
    user_id = str(ctx.author.id)
    dt = now_tz()
    day_key = get_food_day(dt)
    budget_text = build_budget_text(user_id, day_key, dt)
    embed = discord.Embed(
        title="🎯  Daily Budget",
        description=budget_text,
        color=discord.Color.gold(),
        timestamp=dt,
    )
    await ctx.reply(embed=embed)


@bot.command(name="today")
async def cmd_today(ctx: commands.Context):
    """Show a summary of everything you've eaten today."""
    user_id = str(ctx.author.id)
    dt = now_tz()
    day_key = get_food_day(dt)
    meals = get_day_meals(user_id, day_key)
    totals = get_day_totals(user_id, day_key)
    target = get_target_kcal(user_id)

    if not meals:
        await ctx.reply("No meals logged today yet. Post a food photo to get started!")
        return

    lines = [f"**📋 Today's meals ({day_key})**\n"]
    for m in meals:
        window = MEAL_WINDOWS[m["window_idx"]]
        ts = datetime.fromisoformat(m["timestamp"]).strftime("%H:%M")
        lines.append(f"{window[3]} {ts} — {m['kcal']} kcal ({m['protein_g']:.0f}P / {m['carbs_g']:.0f}C / {m['fat_g']:.0f}F)")

    lines.append(f"\n**Total**: {totals['total_kcal']} kcal | {totals['total_protein']:.0f}g P / {totals['total_carbs']:.0f}g C / {totals['total_fat']:.0f}g F")
    if target:
        remaining = target - totals["total_kcal"]
        if remaining > 0:
            lines.append(f"**Remaining**: {remaining} kcal of {target} kcal target")
        else:
            lines.append(f"**Over target**: {abs(remaining)} kcal over {target} kcal target")

    embed = discord.Embed(
        title="🍽️  Today's Log",
        description="\n".join(lines),
        color=discord.Color.green(),
        timestamp=dt,
    )
    await ctx.reply(embed=embed)


@bot.command(name="leaderboard")
async def cmd_leaderboard(ctx: commands.Context):
    """Show today's group rankings."""
    dt = now_tz()
    day_key = get_food_day(dt)
    text = build_leaderboard(day_key)
    embed = discord.Embed(
        title="🏆  Today's Leaderboard",
        description=text,
        color=discord.Color.gold(),
        timestamp=dt,
    )
    await ctx.reply(embed=embed)


@bot.command(name="undo")
async def cmd_undo(ctx: commands.Context):
    """Remove your last logged meal for today."""
    user_id = str(ctx.author.id)
    dt = now_tz()
    day_key = get_food_day(dt)
    deleted = delete_last_meal(user_id, day_key)
    if deleted:
        w = MEAL_WINDOWS[deleted["window_idx"]]
        ts = datetime.fromisoformat(deleted["timestamp"]).strftime("%H:%M")
        await ctx.reply(
            f"🗑️ Removed last meal: **{deleted['kcal']} kcal** ({deleted['protein_g']:.0f}P / {deleted['carbs_g']:.0f}C / {deleted['fat_g']:.0f}F) logged at {ts}."
        )
    else:
        await ctx.reply("No meals to undo today.")


@bot.command(name="delete")
async def cmd_delete(ctx: commands.Context, meal_num: int = None):
    """Delete a specific meal by its number from !today. Usage: !delete 2"""
    user_id = str(ctx.author.id)
    dt = now_tz()
    day_key = get_food_day(dt)
    meals = get_day_meals(user_id, day_key)

    if not meals:
        await ctx.reply("No meals logged today.")
        return

    if meal_num is None:
        lines = ["Which meal do you want to delete? Use `!delete <number>`\n"]
        for i, m in enumerate(meals, 1):
            w = MEAL_WINDOWS[m["window_idx"]]
            ts = datetime.fromisoformat(m["timestamp"]).strftime("%H:%M")
            lines.append(f"**{i}.** {w[3]} {ts} — {m['kcal']} kcal ({m['protein_g']:.0f}P / {m['carbs_g']:.0f}C / {m['fat_g']:.0f}F)")
        await ctx.reply("\n".join(lines))
        return

    if meal_num < 1 or meal_num > len(meals):
        await ctx.reply(f"Invalid meal number. Use a number between 1 and {len(meals)}.")
        return

    meal = meals[meal_num - 1]
    deleted = delete_meal(meal["id"], user_id)
    if deleted:
        ts = datetime.fromisoformat(meal["timestamp"]).strftime("%H:%M")
        await ctx.reply(f"🗑️ Deleted meal #{meal_num}: **{meal['kcal']} kcal** logged at {ts}.")
    else:
        await ctx.reply("Couldn't delete that meal.")


@bot.command(name="edit")
async def cmd_edit(ctx: commands.Context, meal_num: int = None, *, values: str = None):
    """Edit a meal's nutrition. Usage: !edit 2 kcal=500 protein=30 carbs=50 fat=15"""
    user_id = str(ctx.author.id)
    dt = now_tz()
    day_key = get_food_day(dt)
    meals = get_day_meals(user_id, day_key)

    if not meals:
        await ctx.reply("No meals logged today.")
        return

    if meal_num is None or values is None:
        lines = ["Edit a meal's values. Usage: `!edit <number> kcal=X protein=X carbs=X fat=X`\n"]
        lines.append("You can include any combination of values (only specified ones change).\n")
        for i, m in enumerate(meals, 1):
            w = MEAL_WINDOWS[m["window_idx"]]
            ts = datetime.fromisoformat(m["timestamp"]).strftime("%H:%M")
            lines.append(f"**{i}.** {w[3]} {ts} — {m['kcal']} kcal ({m['protein_g']:.0f}P / {m['carbs_g']:.0f}C / {m['fat_g']:.0f}F)")
        await ctx.reply("\n".join(lines))
        return

    if meal_num < 1 or meal_num > len(meals):
        await ctx.reply(f"Invalid meal number. Use a number between 1 and {len(meals)}.")
        return

    meal = meals[meal_num - 1]

    # Parse key=value pairs
    new_kcal = meal["kcal"]
    new_protein = meal["protein_g"]
    new_carbs = meal["carbs_g"]
    new_fat = meal["fat_g"]

    for pair in values.split():
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        try:
            num = float(val)
        except ValueError:
            await ctx.reply(f"Invalid value for `{key}`: `{val}`. Use a number.")
            return

        key = key.lower().strip()
        if key in ("kcal", "cal", "calories"):
            new_kcal = int(num)
        elif key in ("protein", "p"):
            new_protein = num
        elif key in ("carbs", "c", "carbohydrates"):
            new_carbs = num
        elif key in ("fat", "f"):
            new_fat = num
        else:
            await ctx.reply(f"Unknown field: `{key}`. Use: kcal, protein, carbs, fat.")
            return

    updated = update_meal(meal["id"], user_id, new_kcal, new_protein, new_carbs, new_fat)
    if updated:
        await ctx.reply(
            f"✏️ Updated meal #{meal_num}: **{new_kcal} kcal** ({new_protein:.0f}P / {new_carbs:.0f}C / {new_fat:.0f}F)"
        )
    else:
        await ctx.reply("Couldn't update that meal.")


@bot.command(name="analyze")
async def cmd_analyze(ctx: commands.Context):
    """Reply to a message with a food photo using !analyze to re-analyze it."""
    user_id = str(ctx.author.id)
    if not is_premium(user_id):
        embed = discord.Embed(
            title="✨  Photo Reanalysis — Premium Feature",
            description=PREMIUM_UPSELL,
            color=discord.Color.purple(),
        )
        await ctx.reply(embed=embed)
        return
    ref = ctx.message.reference
    if ref is None or ref.resolved is None:
        await ctx.reply("Reply to a message that contains a food photo with `!analyze`.")
        return

    target = ref.resolved
    images = [a for a in target.attachments if any(a.filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))]
    if not images:
        await ctx.reply("That message doesn't contain any food photos.")
        return

    async with ctx.typing():
        for attachment in images:
            image_bytes = await attachment.read()
            ext = attachment.filename.rsplit(".", 1)[-1].lower()
            media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
            media_type = media_map.get(ext, "image/jpeg")

            analysis = await analyze_food_image(image_bytes, media_type)
            display_text = strip_totals_line(analysis)
            embed = discord.Embed(
                title="📊  Nutrition Breakdown",
                description=display_text,
                color=discord.Color.blue(),
                timestamp=now_tz(),
            )
            embed.set_thumbnail(url=attachment.url)
            await ctx.reply(embed=embed)


@bot.command(name="schedule")
async def cmd_schedule(ctx: commands.Context):
    """Show the current reminder schedule."""
    lines = [f"{emoji} **{label}** — {hour:02d}:00 {TIMEZONE}" for hour, label, emoji in REMINDER_HOURS]
    lines.append(f"📋 **Daily Summary** — 04:00 {TIMEZONE}")
    lines.append(f"📢 **Morning Overview** — 08:00 {TIMEZONE}")
    embed = discord.Embed(
        title="🗓️  Schedule",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    await ctx.reply(embed=embed)


@bot.command(name="ping")
async def cmd_ping(ctx: commands.Context):
    """Health check."""
    await ctx.reply(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")


@bot.command(name="commands")
async def cmd_commands(ctx: commands.Context):
    """Show all available commands."""
    await ctx.reply(embed=build_welcome_embed())


@bot.command(name="pro")
async def cmd_pro(ctx: commands.Context):
    """Show premium features and upgrade info."""
    user_id = str(ctx.author.id)
    if is_premium(user_id):
        trial_left = get_trial_days_left(user_id)
        if trial_left is not None:
            status = f"🎁 You're on a free trial — **{trial_left} days remaining**"
        else:
            status = "✅ You're a **Pro** member! All features unlocked."
        allowed, remaining = check_photo_cap(user_id)
        status += f"\n📸 Photo analyses today: {DAILY_PHOTO_CAP - remaining}/{DAILY_PHOTO_CAP}"
        embed = discord.Embed(
            title="✨  FoodTracker Pro",
            description=status,
            color=discord.Color.green(),
            timestamp=now_tz(),
        )
    else:
        embed = discord.Embed(
            title="✨  FoodTracker Pro",
            description=PREMIUM_UPSELL,
            color=discord.Color.purple(),
            timestamp=now_tz(),
        )
    await ctx.reply(embed=embed)


@bot.command(name="trial")
async def cmd_trial(ctx: commands.Context):
    """Start a free 7-day trial of FoodTracker Pro."""
    user_id = str(ctx.author.id)

    if is_premium(user_id):
        trial_left = get_trial_days_left(user_id)
        if trial_left is not None:
            await ctx.reply(f"🎁 You're already on a trial — **{trial_left} days remaining**. Enjoy!")
        else:
            await ctx.reply("✅ You already have Pro! All features are unlocked.")
        return

    # Check if trial was already used (trial_started exists but expired)
    conn = get_db()
    row = conn.execute("SELECT trial_started FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row and row["trial_started"]:
        await ctx.reply(
            f"Your free trial has expired. Upgrade to **FoodTracker Pro** for {PREMIUM_PRICE} to keep using photo analysis, voice logging, barcode scanning, and corrections!\n\n"
            "*(Discord Premium App subscriptions coming soon — for now, ask a server admin to activate your Pro status with `!setpremium @user`)*"
        )
        return

    start_trial(user_id)
    embed = discord.Embed(
        title="🎉  Free Trial Activated!",
        description=(
            f"You now have **{TRIAL_DAYS} days** of full FoodTracker Pro access!\n\n"
            "**Unlocked features:**\n"
            f"📸 AI photo analysis (up to {DAILY_PHOTO_CAP}/day)\n"
            "🎤 Voice message meal logging\n"
            "📦 Barcode scanning with quantity modifiers\n"
            "✏️ Reply-based meal corrections\n"
            "🔄 Photo reanalysis\n\n"
            "Start by snapping a photo of your next meal!"
        ),
        color=discord.Color.green(),
        timestamp=now_tz(),
    )
    await ctx.reply(embed=embed)


@bot.command(name="setpremium")
async def cmd_setpremium(ctx: commands.Context, member: discord.Member = None):
    """Admin command: activate Pro for a user. Usage: !setpremium @user"""
    # Only allow server admins
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("⚠️ Only server admins can use this command.")
        return
    if member is None:
        await ctx.reply("Usage: `!setpremium @user` to activate Pro for someone.")
        return
    set_premium(str(member.id), True)
    await ctx.reply(f"✅ **{member.display_name}** is now a FoodTracker Pro member!")


@bot.command(name="removepremium")
async def cmd_removepremium(ctx: commands.Context, member: discord.Member = None):
    """Admin command: remove Pro from a user. Usage: !removepremium @user"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("⚠️ Only server admins can use this command.")
        return
    if member is None:
        await ctx.reply("Usage: `!removepremium @user` to remove Pro from someone.")
        return
    set_premium(str(member.id), False)
    await ctx.reply(f"🔒 **{member.display_name}** has been removed from FoodTracker Pro.")


# ---------------------------------------------------------------------------
# HTTP health server for Railway
# ---------------------------------------------------------------------------
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *args):
        pass

def _start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Health server listening on port %s", port)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _start_health_server()
    bot.run(DISCORD_BOT_TOKEN)
