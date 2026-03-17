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
from google import genai
from google.genai import types as genai_types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import calendar
from PIL import Image
from pyzbar.pyzbar import decode as decode_barcodes

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROUP_CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])  # shared group channel
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Berlin")
SERVER_ID = int(os.environ.get("DISCORD_SERVER_ID", "0"))
PRO_SKU_ID = int(os.environ.get("PRO_SKU_ID", "1483496066660700252"))

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
            photo_count_day  TEXT,
            interaction_count INTEGER NOT NULL DEFAULT 0,
            interaction_period TEXT,
            protein_target INTEGER,
            fat_target    INTEGER NOT NULL DEFAULT 50
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
            raw_analysis TEXT,
            photo_url   TEXT,
            water_ml    INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_meals_user_day ON meals(user_id, day_key);
        CREATE TABLE IF NOT EXISTS weight_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT NOT NULL,
            day_key   TEXT NOT NULL,
            weight_kg REAL NOT NULL,
            timestamp TEXT NOT NULL,
            UNIQUE(user_id, day_key)
        );
        CREATE TABLE IF NOT EXISTS water_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT NOT NULL,
            day_key   TEXT NOT NULL,
            amount_ml INTEGER NOT NULL,
            source    TEXT,
            timestamp TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_water_user_day ON water_log(user_id, day_key);
    """)
    # Migration: add premium columns if they don't exist yet
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_settings)").fetchall()}
    migrations = {
        "is_premium": "ALTER TABLE user_settings ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0",
        "premium_since": "ALTER TABLE user_settings ADD COLUMN premium_since TEXT",
        "trial_started": "ALTER TABLE user_settings ADD COLUMN trial_started TEXT",
        "photo_count_today": "ALTER TABLE user_settings ADD COLUMN photo_count_today INTEGER NOT NULL DEFAULT 0",
        "photo_count_day": "ALTER TABLE user_settings ADD COLUMN photo_count_day TEXT",
        "interaction_count": "ALTER TABLE user_settings ADD COLUMN interaction_count INTEGER NOT NULL DEFAULT 0",
        "interaction_period": "ALTER TABLE user_settings ADD COLUMN interaction_period TEXT",
        "protein_target": "ALTER TABLE user_settings ADD COLUMN protein_target INTEGER",
        "fat_target": "ALTER TABLE user_settings ADD COLUMN fat_target INTEGER NOT NULL DEFAULT 50",
    }
    for col, sql in migrations.items():
        if col not in existing_cols:
            conn.execute(sql)
            log.info("Migrated: added column %s to user_settings", col)
    # Meals table migrations
    meal_cols = {row[1] for row in conn.execute("PRAGMA table_info(meals)").fetchall()}
    meal_migrations = {
        "photo_url": "ALTER TABLE meals ADD COLUMN photo_url TEXT",
        "water_ml": "ALTER TABLE meals ADD COLUMN water_ml INTEGER NOT NULL DEFAULT 0",
    }
    for col, sql in meal_migrations.items():
        if col not in meal_cols:
            conn.execute(sql)
            log.info("Migrated: added column %s to meals", col)
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

def get_macro_targets(user_id: str) -> dict | None:
    """Return {'kcal': int, 'protein': int|None, 'fat': int, 'carbs': int|None} or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT target_kcal, protein_target, fat_target FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    kcal = row["target_kcal"]
    protein = row["protein_target"]  # may be None
    fat = row["fat_target"] or 50
    carbs = None
    if protein is not None:
        # carbs = (remaining kcal after protein + fat) / 4
        carbs_kcal = kcal - (protein * 4) - (fat * 9)
        carbs = max(0, int(carbs_kcal / 4))
    return {"kcal": kcal, "protein": protein, "fat": fat, "carbs": carbs}


def set_macro_targets(user_id: str, protein: int | None = None, fat: int | None = None):
    """Set protein and/or fat targets. Fat minimum is 30g."""
    conn = get_db()
    if protein is not None and fat is not None:
        conn.execute(
            "UPDATE user_settings SET protein_target = ?, fat_target = ? WHERE user_id = ?",
            (protein, max(30, fat), user_id),
        )
    elif protein is not None:
        conn.execute(
            "UPDATE user_settings SET protein_target = ? WHERE user_id = ?",
            (protein, user_id),
        )
    elif fat is not None:
        conn.execute(
            "UPDATE user_settings SET fat_target = ? WHERE user_id = ?",
            (max(30, fat), user_id),
        )
    conn.commit()
    conn.close()


def get_streak(user_id: str) -> int:
    """Count consecutive days (ending today or yesterday) where the user logged meals
    and stayed at or under their kcal target. Returns 0 if no streak."""
    conn = get_db()
    row = conn.execute(
        "SELECT target_kcal FROM user_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row or not row["target_kcal"]:
        conn.close()
        return 0
    target = row["target_kcal"]

    dt = now_tz()
    today = get_food_day(dt)
    streak = 0

    # Check today first — if meals logged and on target, count it
    # Then check backwards day by day
    check_date = datetime.strptime(today, "%Y-%m-%d")
    while True:
        day_key = check_date.strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COALESCE(SUM(kcal),0) as total, COUNT(*) as cnt "
            "FROM meals WHERE user_id = ? AND day_key = ?",
            (user_id, day_key),
        ).fetchone()
        if row["cnt"] == 0:
            # No meals logged — streak broken (unless it's today and just not logged yet)
            if day_key == today:
                check_date -= timedelta(days=1)
                continue
            break
        if row["total"] > target:
            # Over target — streak broken
            break
        streak += 1
        check_date -= timedelta(days=1)

    conn.close()
    return streak


def get_period_totals(user_id: str, start_date: str, end_date: str) -> dict:
    """Get aggregated totals for a date range (inclusive). Returns dict with
    total_kcal, total_protein, total_carbs, total_fat, meal_count, days_logged, daily_breakdown."""
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(kcal),0) as total_kcal, "
        "COALESCE(SUM(protein_g),0) as total_protein, "
        "COALESCE(SUM(carbs_g),0) as total_carbs, "
        "COALESCE(SUM(fat_g),0) as total_fat, "
        "COUNT(*) as meal_count, "
        "COUNT(DISTINCT day_key) as days_logged "
        "FROM meals WHERE user_id = ? AND day_key >= ? AND day_key <= ?",
        (user_id, start_date, end_date),
    ).fetchone()

    # Daily breakdown for fat warning check
    daily_rows = conn.execute(
        "SELECT day_key, SUM(fat_g) as day_fat, SUM(kcal) as day_kcal, "
        "SUM(protein_g) as day_protein, SUM(carbs_g) as day_carbs "
        "FROM meals WHERE user_id = ? AND day_key >= ? AND day_key <= ? "
        "GROUP BY day_key ORDER BY day_key",
        (user_id, start_date, end_date),
    ).fetchall()
    conn.close()

    result = dict(row)
    result["daily_breakdown"] = [dict(r) for r in daily_rows]
    return result


# ---------------------------------------------------------------------------
# Weight tracking helpers
# ---------------------------------------------------------------------------
def log_weight(user_id: str, weight_kg: float) -> bool:
    """Log weight for today. Returns True if inserted, False if updated."""
    day_key = get_food_day(now_tz())
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO weight_log (user_id, day_key, weight_kg, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, day_key, weight_kg, now_tz().isoformat()),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE weight_log SET weight_kg = ?, timestamp = ? WHERE user_id = ? AND day_key = ?",
            (weight_kg, now_tz().isoformat(), user_id, day_key),
        )
        conn.commit()
        conn.close()
        return False


def get_weight_history(user_id: str, limit: int = 30) -> list[dict]:
    """Get recent weight entries, newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM weight_log WHERE user_id = ? ORDER BY day_key DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_weight_for_period(user_id: str, start_date: str, end_date: str) -> list[dict]:
    """Get weight entries for a date range."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM weight_log WHERE user_id = ? AND day_key >= ? AND day_key <= ? ORDER BY day_key",
        (user_id, start_date, end_date),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Water tracking helpers
# ---------------------------------------------------------------------------
DAILY_WATER_TARGET_ML = 2500  # default recommended daily intake

def add_water(user_id: str, amount_ml: int, source: str = "manual") -> int:
    """Log water intake. Returns total water for today."""
    day_key = get_food_day(now_tz())
    conn = get_db()
    conn.execute(
        "INSERT INTO water_log (user_id, day_key, amount_ml, source, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, day_key, amount_ml, source, now_tz().isoformat()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_ml), 0) as total FROM water_log WHERE user_id = ? AND day_key = ?",
        (user_id, day_key),
    ).fetchone()
    conn.close()
    return row["total"]


def get_day_water(user_id: str, day_key: str) -> int:
    """Get total water intake in ml for a given day."""
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_ml), 0) as total FROM water_log WHERE user_id = ? AND day_key = ?",
        (user_id, day_key),
    ).fetchone()
    conn.close()
    return row["total"]


def get_period_water(user_id: str, start_date: str, end_date: str) -> dict:
    """Get water totals for a period. Returns {total_ml, days_logged, daily_avg}."""
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_ml), 0) as total_ml, COUNT(DISTINCT day_key) as days_logged "
        "FROM water_log WHERE user_id = ? AND day_key >= ? AND day_key <= ?",
        (user_id, start_date, end_date),
    ).fetchone()
    conn.close()
    result = dict(row)
    result["daily_avg"] = result["total_ml"] / result["days_logged"] if result["days_logged"] else 0
    return result


def get_day_photo_urls(user_id: str, day_key: str) -> list[str]:
    """Get all photo URLs for a user's meals on a given day."""
    conn = get_db()
    rows = conn.execute(
        "SELECT photo_url FROM meals WHERE user_id = ? AND day_key = ? AND photo_url IS NOT NULL ORDER BY timestamp",
        (user_id, day_key),
    ).fetchall()
    conn.close()
    return [row["photo_url"] for row in rows]


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
             description: str, raw_analysis: str,
             photo_url: str | None = None, water_ml: int = 0) -> int:
    """Insert a meal and return the new meal ID."""
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO meals (user_id, day_key, window_idx, timestamp, kcal, protein_g, carbs_g, fat_g, description, raw_analysis, photo_url, water_ml) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, day_key, window_idx, now_tz().isoformat(), kcal, protein, carbs, fat, description, raw_analysis, photo_url, water_ml),
    )
    meal_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return meal_id

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
DAILY_PHOTO_CAP = 8  # legacy — kept for photo-specific cap on premium users
TRIAL_DAYS = 7
FREE_DAILY_CAP = 3       # free users: 3 interactions/day (any modality)
PREMIUM_MONTHLY_CAP = 500  # premium users: 500 interactions/month

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

def check_interaction_cap(user_id: str) -> tuple[bool, int]:
    """Check if user is within their interaction cap.
    Free users: FREE_DAILY_CAP per day. Premium users: PREMIUM_MONTHLY_CAP per month.
    Returns (allowed, remaining).
    """
    premium = is_premium(user_id)
    conn = get_db()
    row = conn.execute(
        "SELECT interaction_count, interaction_period FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        conn.close()
        cap = PREMIUM_MONTHLY_CAP if premium else FREE_DAILY_CAP
        return True, cap

    count = row["interaction_count"] or 0
    period = row["interaction_period"] or ""

    if premium:
        # Monthly cap — period key is YYYY-MM
        current_period = now_tz().strftime("%Y-%m")
        cap = PREMIUM_MONTHLY_CAP
    else:
        # Daily cap — period key is the food day
        current_period = get_food_day(now_tz())
        cap = FREE_DAILY_CAP

    # Reset if new period
    if period != current_period:
        count = 0
        conn.execute(
            "UPDATE user_settings SET interaction_count = 0, interaction_period = ? WHERE user_id = ?",
            (current_period, user_id),
        )
        conn.commit()

    conn.close()
    remaining = cap - count
    return count < cap, max(0, remaining)

def increment_interaction_count(user_id: str):
    """Increment the interaction counter for a user."""
    premium = is_premium(user_id)
    current_period = now_tz().strftime("%Y-%m") if premium else get_food_day(now_tz())
    conn = get_db()
    conn.execute(
        "UPDATE user_settings SET interaction_count = interaction_count + 1, interaction_period = ? WHERE user_id = ?",
        (current_period, user_id),
    )
    conn.commit()
    conn.close()

PREMIUM_UPSELL = f"""⚡ **You've hit your daily limit!**

Free users get **{FREE_DAILY_CAP} interactions/day** (any type — photos, voice, text, barcodes).

Upgrade to **FoodTracker Pro** ({PREMIUM_PRICE}) for up to **{PREMIUM_MONTHLY_CAP} interactions/month**:
📸 AI photo analysis
🎤 Voice message meal logging
📦 Barcode scanning with quantity modifiers
✏️ Reply-based meal corrections
🔄 Photo reanalysis (`!analyze`)

🎯 Calorie budget tracking, leaderboards & reminders are always free.

Type `!trial` to start your **free {TRIAL_DAYS}-day trial** — no payment needed!"""

# ---------------------------------------------------------------------------
# AI clients — Gemini 2.5 Flash Lite is primary; OpenAI/Anthropic are fallbacks
# ---------------------------------------------------------------------------
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
GEMINI_MODEL = "gemini-2.5-flash-lite"
# Gemini 2.5 Flash Lite pricing: $0.10/1M input, $0.40/1M output
GEMINI_INPUT_PRICE = 0.10   # per 1M tokens
GEMINI_OUTPUT_PRICE = 0.40  # per 1M tokens

# Fallback clients (used if Gemini is not configured)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

ANALYSIS_SYSTEM_PROMPT = """You are a nutrition analysis assistant. When given a photo of food, provide:

A table with these columns using EXACTLY these emoji headers:
| 🍽️ Food Item | ⚖️ Weight | 💪 Protein | 🍞 Carbs | 🧈 Fat | 🔥 Calories | 💧 Water |

Rules:
- Each food item MUST start with a relevant food emoji (e.g. 🥚 Scrambled Eggs, 🥓 Bacon, 🍗 Chicken, 🍚 Rice, 🥗 Salad, 🍞 Bread, 🧀 Cheese, 🥩 Steak, 🍝 Pasta, 🥛 Milk, 🍌 Banana, etc.)
- Weight column: include ⚖️ before the value (e.g. ⚖️ ~200g)
- Protein column: include 💪 before the value (e.g. 💪 25g)
- Carbs column: include 🍞 before the value (e.g. 🍞 30g)
- Fat column: include 🧈 before the value (e.g. 🧈 12g)
- Calories column: include 🔥 before the value (e.g. 🔥 350)
- Water column: include 💧 before the value (e.g. 💧 120ml) — water content IN the food
- Last row: **Meal Totals** with sums (also with emojis)
- Water examples: soup ~300ml, salad ~150ml, rice ~80ml, dry snack ~5ml

Be concise. If you're uncertain about portion sizes, state your assumptions briefly. Always give your best estimate rather than refusing.

IMPORTANT: At the very end of your response, include a single line in this exact format:
$$TOTALS: kcal=NUMBER, protein=NUMBER, carbs=NUMBER, fat=NUMBER, water=NUMBER$$

The water value is estimated ml of water contained IN the food itself.

For example:
$$TOTALS: kcal=650, protein=45, carbs=60, fat=22, water=180$$

This line must contain only integers (no decimals). This is used for automated tracking."""


def parse_totals(analysis: str) -> dict:
    # Try new format with water first
    match = re.search(r'\$\$TOTALS:\s*kcal=(\d+),\s*protein=(\d+),\s*carbs=(\d+),\s*fat=(\d+),\s*water=(\d+)\$\$', analysis)
    if match:
        return {
            "kcal": int(match.group(1)),
            "protein": float(match.group(2)),
            "carbs": float(match.group(3)),
            "fat": float(match.group(4)),
            "water_ml": int(match.group(5)),
        }
    # Fallback: old format without water
    match = re.search(r'\$\$TOTALS:\s*kcal=(\d+),\s*protein=(\d+),\s*carbs=(\d+),\s*fat=(\d+)\$\$', analysis)
    if match:
        return {
            "kcal": int(match.group(1)),
            "protein": float(match.group(2)),
            "carbs": float(match.group(3)),
            "fat": float(match.group(4)),
            "water_ml": 0,
        }
    kcal_match = re.search(r'(\d[,\d]*)\s*(?:kcal|calories|cal)\b', analysis, re.IGNORECASE)
    if kcal_match:
        kcal_str = kcal_match.group(1).replace(",", "")
        return {"kcal": int(kcal_str), "protein": 0, "carbs": 0, "fat": 0, "water_ml": 0}
    return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0, "water_ml": 0}


def strip_totals_line(analysis: str) -> str:
    return re.sub(r'\n?\$\$TOTALS:.*?\$\$\n?', '', analysis).strip()


def _log_gemini_cost(label: str, usage):
    """Log cost from a Gemini response's usage_metadata."""
    inp = getattr(usage, "prompt_token_count", 0) or 0
    out = getattr(usage, "candidates_token_count", 0) or 0
    cost = (inp * GEMINI_INPUT_PRICE + out * GEMINI_OUTPUT_PRICE) / 1_000_000
    log.info(f"[COST] {label} | in={inp} out={out} | ${cost:.6f}")
    return cost


async def analyze_food_image(image_bytes: bytes, media_type: str = "image/jpeg") -> str:
    """Send a food photo to Gemini 2.5 Flash Lite and return the macro breakdown."""
    if gemini_client:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                ANALYSIS_SYSTEM_PROMPT + "\n\nAnalyze this meal photo. Estimate macros (protein, carbs, fat) and total calories.",
                genai_types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            ],
            config=genai_types.GenerateContentConfig(max_output_tokens=1024),
        )
        _log_gemini_cost("photo_analysis", response.usage_metadata)
        return response.text
    # Fallback: OpenAI GPT-4o
    if not openai_client:
        raise ValueError("No AI API key configured. Add GEMINI_API_KEY or OPENAI_API_KEY to env vars.")
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                    {"type": "text", "text": "Analyze this meal photo. Estimate macros (protein, carbs, fat) and total calories."},
                ],
            },
        ],
    )
    u = response.usage
    cost = (u.prompt_tokens * 2.50 + u.completion_tokens * 10.00) / 1_000_000
    log.info(f"[COST] photo_analysis_fallback | in={u.prompt_tokens} out={u.completion_tokens} | ${cost:.6f}")
    return response.choices[0].message.content


TEXT_ANALYSIS_SYSTEM_PROMPT = """You are a nutrition analysis assistant. The user will describe what they ate in text. Provide:

A table with these columns using EXACTLY these emoji headers:
| 🍽️ Food Item | ⚖️ Weight | 💪 Protein | 🍞 Carbs | 🧈 Fat | 🔥 Calories | 💧 Water |

Rules:
- Each food item MUST start with a relevant food emoji (e.g. 🥚 Scrambled Eggs, 🥓 Bacon, 🍗 Chicken, 🍚 Rice, 🥗 Salad, 🍞 Bread, 🧀 Cheese, 🥩 Steak, 🍝 Pasta, 🥛 Milk, 🍌 Banana, etc.)
- Weight column: include ⚖️ before the value (e.g. ⚖️ ~200g)
- Protein column: include 💪 before the value (e.g. 💪 25g)
- Carbs column: include 🍞 before the value (e.g. 🍞 30g)
- Fat column: include 🧈 before the value (e.g. 🧈 12g)
- Calories column: include 🔥 before the value (e.g. 🔥 350)
- Water column: include 💧 before the value (e.g. 💧 120ml) — water content IN the food
- Last row: **Meal Totals** with sums (also with emojis)
- If the user doesn't specify portion sizes, assume typical serving sizes and state your assumptions briefly.
- Water examples: soup ~300ml, salad ~150ml, rice ~80ml, dry snack ~5ml

Be concise.

IMPORTANT: At the very end of your response, include a single line in this exact format:
$$TOTALS: kcal=NUMBER, protein=NUMBER, carbs=NUMBER, fat=NUMBER, water=NUMBER$$

The water value is estimated ml of water contained IN the food itself.

This line must contain only integers (no decimals). This is used for automated tracking."""


async def analyze_food_text(description: str) -> str:
    """Send a text description of food to Gemini and return the macro breakdown."""
    if gemini_client:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=TEXT_ANALYSIS_SYSTEM_PROMPT + f"\n\nI ate: {description}\n\nEstimate macros (protein, carbs, fat) and total calories.",
            config=genai_types.GenerateContentConfig(max_output_tokens=1024),
        )
        _log_gemini_cost("text_analysis", response.usage_metadata)
        return response.text
    # Fallback: Claude Sonnet
    if not claude:
        raise ValueError("No AI API key configured. Add GEMINI_API_KEY or ANTHROPIC_API_KEY to env vars.")
    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=TEXT_ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"I ate: {description}\n\nEstimate macros (protein, carbs, fat) and total calories."}],
    )
    u = message.usage
    cost = (u.input_tokens * 3.00 + u.output_tokens * 15.00) / 1_000_000
    log.info(f"[COST] text_analysis_fallback | in={u.input_tokens} out={u.output_tokens} | ${cost:.6f}")
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

Provide the corrected full analysis as a table with these columns using EXACTLY these emoji headers:
| 🍽️ Food Item | ⚖️ Weight | 💪 Protein | 🍞 Carbs | 🧈 Fat | 🔥 Calories | 💧 Water |

Each food item MUST start with a relevant food emoji. Each value MUST include its column emoji (e.g. 💪 25g, 🧈 12g, 🔥 350, 💧 80ml).
Last row: **Meal Totals** with sums. Be concise.

IMPORTANT: At the very end of your response, include a single line in this exact format:
$$TOTALS: kcal=NUMBER, protein=NUMBER, carbs=NUMBER, fat=NUMBER, water=NUMBER$$

This line must contain only integers (no decimals). This is used for automated tracking."""


async def reevaluate_meal(original_analysis: str, corrections: str) -> str:
    """Send original analysis + user corrections to Gemini and return updated breakdown."""
    prompt = (
        CORRECTION_SYSTEM_PROMPT + "\n\n"
        f"ORIGINAL ANALYSIS:\n{original_analysis}\n\n"
        f"MY CORRECTIONS:\n{corrections}\n\n"
        "Please apply my corrections and provide the updated nutrition breakdown."
    )
    if gemini_client:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(max_output_tokens=1024),
        )
        _log_gemini_cost("correction", response.usage_metadata)
        return response.text
    # Fallback: Claude Sonnet
    if not claude:
        raise ValueError("No AI API key configured. Add GEMINI_API_KEY or ANTHROPIC_API_KEY to env vars.")
    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=CORRECTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"ORIGINAL ANALYSIS:\n{original_analysis}\n\nMY CORRECTIONS:\n{corrections}\n\nPlease apply my corrections and provide the updated nutrition breakdown."}],
    )
    u = message.usage
    cost = (u.input_tokens * 3.00 + u.output_tokens * 15.00) / 1_000_000
    log.info(f"[COST] correction_fallback | in={u.input_tokens} out={u.output_tokens} | ${cost:.6f}")
    return message.content[0].text


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Transcribe audio using Gemini (or Whisper as fallback)."""
    # Determine MIME type from filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "ogg"
    mime_map = {"ogg": "audio/ogg", "mp3": "audio/mp3", "wav": "audio/wav", "m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm"}
    mime_type = mime_map.get(ext, "audio/ogg")

    if gemini_client:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                "Transcribe the following audio. Return ONLY the transcription text, nothing else.",
                genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            ],
            config=genai_types.GenerateContentConfig(max_output_tokens=256),
        )
        _log_gemini_cost("audio_transcription", response.usage_metadata)
        return response.text.strip()

    # Fallback: OpenAI Whisper
    if not openai_client:
        raise ValueError("No AI API key configured. Add GEMINI_API_KEY or OPENAI_API_KEY to env vars.")
    suffix = "." + ext
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        audio_size_bytes = len(audio_bytes)
        est_duration_sec = audio_size_bytes / 6000
        with open(tmp_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        est_minutes = est_duration_sec / 60
        cost = est_minutes * 0.006
        log.info(f"[COST] whisper_fallback | ~{est_duration_sec:.1f}s (~{est_minutes:.2f}min) | size={audio_size_bytes}B | ${cost:.6f}")
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
    """Use Gemini to interpret a complex quantity description and return a multiplier."""
    prompt = (
        "You help convert food quantity descriptions into a numeric multiplier. "
        f"The base unit is: {portion_note} of {product_name}. "
        "Return ONLY a single decimal number representing the multiplier. "
        "Examples: 'half' → 0.5, '2 servings' → 2.0, '50g' (if base is per 100g) → 0.5, "
        "'one spoon' (if base is per 100g) → 0.15. "
        f"Return just the number, nothing else.\n\nUser input: {text}"
    )
    if gemini_client:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(max_output_tokens=20),
        )
        _log_gemini_cost("quantity_interpret", response.usage_metadata)
        try:
            return float(response.text.strip())
        except ValueError:
            return 1.0
    # Fallback: Claude
    if not claude:
        return 1.0
    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        system=prompt,
        messages=[{"role": "user", "content": text}],
    )
    u = message.usage
    cost = (u.input_tokens * 3.00 + u.output_tokens * 15.00) / 1_000_000
    log.info(f"[COST] quantity_interpret_fallback | in={u.input_tokens} out={u.output_tokens} | ${cost:.6f}")
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


async def read_nutrition_label(image_bytes: bytes, media_type: str = "image/jpeg",
                               product_name: str = "", barcode: str = "") -> dict | None:
    """Try to read a nutrition label/table from an image using Gemini.
    Returns dict with kcal, protein, carbs, fat, portion_note or None if no label visible."""
    if not gemini_client:
        return None

    prompt = (
        "Look at this product image carefully. Is there a visible nutrition facts table / "
        "nutrition information label?\n\n"
        "If YES — extract the EXACT values from the label. Look for: calories (kcal), "
        "protein (g), carbohydrates (g), and fat (g). Use the 'per serving' values if shown, "
        "otherwise use 'per 100g'.\n\n"
        "If NO nutrition label/table is visible, respond with exactly: NO_LABEL\n\n"
        "If you CAN read the label, respond in this EXACT format (numbers only, no text):\n"
        "LABEL_FOUND\n"
        "portion=per serving (50g)\n"
        "kcal=NUMBER\n"
        "protein=NUMBER\n"
        "carbs=NUMBER\n"
        "fat=NUMBER\n\n"
        "Use integers only. The portion line should describe what the values are for."
    )

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            ],
            config=genai_types.GenerateContentConfig(max_output_tokens=256),
        )
        _log_gemini_cost("label_read", response.usage_metadata)
        text = response.text.strip()

        if "NO_LABEL" in text:
            return None

        if "LABEL_FOUND" not in text:
            return None

        # Parse the structured response
        result = {}
        for line in text.split("\n"):
            line = line.strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            if key == "portion":
                result["portion_note"] = val
            elif key in ("kcal", "protein", "carbs", "fat"):
                try:
                    result[key] = int(re.sub(r'[^\d]', '', val))
                except ValueError:
                    pass

        # Validate we got all required fields
        if all(k in result for k in ("kcal", "protein", "carbs", "fat")):
            result.setdefault("portion_note", "per serving")
            log.info("Nutrition label read for %s: %s", product_name or barcode, result)
            return result

        return None

    except Exception as e:
        log.warning("Label reading failed: %s", e)
        return None


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

    # Show macro progress with targets if set
    macros = get_macro_targets(user_id)
    if macros and macros["protein"] is not None:
        p_left = macros["protein"] - totals["total_protein"]
        f_left = macros["fat"] - totals["total_fat"]
        c_left = macros["carbs"] - totals["total_carbs"]
        lines.append(
            f"📊 Macros: **{totals['total_protein']:.0f}**/{macros['protein']}g P | "
            f"**{totals['total_fat']:.0f}**/{macros['fat']}g F | "
            f"**{totals['total_carbs']:.0f}**/{macros['carbs']}g C"
        )
        if p_left > 0:
            lines.append(f"🥩 Still need **{p_left:.0f}g protein** today")
    else:
        lines.append(f"📊 Today so far: {totals['total_protein']:.0f}g P / {totals['total_carbs']:.0f}g C / {totals['total_fat']:.0f}g F")

    # Water progress
    day_water = get_day_water(user_id, day_key)
    water_pct = min(100, int(day_water / DAILY_WATER_TARGET_ML * 100))
    lines.append(f"💧 Water: **{day_water}ml** / {DAILY_WATER_TARGET_ML}ml ({water_pct}%)")

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
`!macros protein=X fat=X` — Set macro targets (carbs auto-calculated)
`!weight 82.5` — Log your weight (kg)
`!water 250` — Log water intake (ml)
`!streak` — View your streak of days on target
`!weekly` — Weekly summary report with trends
`!monthly` — Monthly summary report
`!history` — View a day's meals + photo GIF
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


async def build_day_gif(user_id: str, day_key: str) -> io.BytesIO | None:
    """Download all meal photos for a day and stitch them into an animated GIF.
    Returns a BytesIO buffer with the GIF or None if no photos."""
    photo_urls = get_day_photo_urls(user_id, day_key)
    if len(photo_urls) < 1:
        return None

    frames = []
    for url in photo_urls:
        try:
            resp = http_requests.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            img = Image.open(io.BytesIO(resp.content))
            # Resize to consistent size for GIF
            img = img.convert("RGB")
            img.thumbnail((480, 480), Image.LANCZOS)
            # Pad to square
            size = max(img.size)
            square = Image.new("RGB", (size, size), (30, 30, 30))
            offset = ((size - img.width) // 2, (size - img.height) // 2)
            square.paste(img, offset)
            frames.append(square)
        except Exception as e:
            log.warning("Failed to download meal photo %s: %s", url[:80], e)
            continue

    if not frames:
        return None

    # If only one photo, duplicate it so GIF is still valid
    if len(frames) == 1:
        frames.append(frames[0])

    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:],
        duration=2000, loop=0, optimize=True,
    )
    buf.seek(0)
    log.info("Built day GIF for user %s on %s: %d frames, %d bytes", user_id, day_key, len(frames), buf.getbuffer().nbytes)
    return buf


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

        # Macro targets comparison
        user_macros = get_macro_targets(user_id)
        if user_macros and user_macros["protein"] is not None:
            lines.append(
                f"\n📊 Macros: **{totals['total_protein']:.0f}**/{user_macros['protein']}g P | "
                f"**{totals['total_fat']:.0f}**/{user_macros['fat']}g F | "
                f"**{totals['total_carbs']:.0f}**/{user_macros['carbs']}g C"
            )
            if totals['total_protein'] >= user_macros['protein']:
                lines.append("✅ Protein target hit!")
            else:
                lines.append(f"🥩 Missed protein target by {user_macros['protein'] - totals['total_protein']:.0f}g")
        else:
            lines.append(f"\n📊 {totals['total_protein']:.0f}g P / {totals['total_carbs']:.0f}g C / {totals['total_fat']:.0f}g F")

        lines.append(f"🍽️ {totals['meal_count']} meals logged")

        # Water
        day_water = get_day_water(user_id, prev_day)
        if day_water > 0:
            pct = min(100, int(day_water / DAILY_WATER_TARGET_ML * 100))
            water_emoji = "✅" if day_water >= DAILY_WATER_TARGET_ML else "💧"
            lines.append(f"{water_emoji} Water: **{day_water}ml** / {DAILY_WATER_TARGET_ML}ml ({pct}%)")

        # Streak
        user_streak = get_streak(user_id)
        if user_streak > 0:
            lines.append(f"🔥 Current streak: **{user_streak} days**")

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

        # Build and attach meal photo GIF
        try:
            gif_buf = await build_day_gif(user_id, prev_day)
            if gif_buf:
                gif_file = discord.File(gif_buf, filename=f"meals-{prev_day}.gif")
                embed.set_image(url=f"attachment://meals-{prev_day}.gif")
                await channel.send(embed=embed, file=gif_file)
            else:
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
    """8am: send welcome/overview to group channel + weight prompt to private channels."""
    group_channel = bot.get_channel(GROUP_CHANNEL_ID)
    if group_channel:
        await group_channel.send(embed=build_welcome_embed())
        log.info("Sent morning overview to group channel")

    # Send weight prompt to each user's private channel
    users = get_all_users()
    for u in users:
        ch_id = u.get("private_channel")
        if not ch_id:
            continue
        channel = bot.get_channel(ch_id)
        if not channel:
            continue
        user_id = u["user_id"]
        history = get_weight_history(user_id, limit=2)
        if history:
            last = history[0]
            weight_line = f"⚖️ **Good morning!** Your last weigh-in: **{last['weight_kg']:.1f} kg** ({last['day_key']})"
            if len(history) >= 2:
                diff = last["weight_kg"] - history[1]["weight_kg"]
                if diff < 0:
                    weight_line += f" — down {abs(diff):.1f}kg 📉"
                elif diff > 0:
                    weight_line += f" — up {diff:.1f}kg 📈"
            weight_line += "\nLog today's weight: `!weight 82.5`"
        else:
            weight_line = "⚖️ **Good morning!** Start tracking your weight: `!weight 82.5`"
        try:
            await channel.send(weight_line)
        except Exception as e:
            log.warning("Failed to send weight prompt to %s: %s", ch_id, e)
    log.info("Sent morning weight prompts to %d users", len(users))


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

    # Monday 4:30am weekly report
    scheduler.add_job(
        send_weekly_reports,
        CronTrigger(day_of_week="mon", hour=4, minute=30, timezone=TIMEZONE),
        id="weekly_report",
        replace_existing=True,
    )
    log.info("Scheduled weekly report at Monday 04:30 %s", TIMEZONE)

    # 1st of month 5:00am monthly report
    scheduler.add_job(
        send_monthly_reports,
        CronTrigger(day=1, hour=5, minute=0, timezone=TIMEZONE),
        id="monthly_report",
        replace_existing=True,
    )
    log.info("Scheduled monthly report at 1st of month 05:00 %s", TIMEZONE)

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
async def on_entitlement_create(entitlement: discord.Entitlement):
    """Fired when a user subscribes to FoodTracker Pro via Discord."""
    if entitlement.sku_id != PRO_SKU_ID:
        return
    user_id = str(entitlement.user_id)
    set_premium(user_id, True)
    log.info("Premium ACTIVATED via Discord subscription for user %s (entitlement %s)", user_id, entitlement.id)
    # Try to DM or notify the user
    try:
        user = await bot.fetch_user(entitlement.user_id)
        await user.send(
            f"🎉 **Welcome to FoodTracker Pro!** Your subscription is active.\n\n"
            f"You now have **{PREMIUM_MONTHLY_CAP} interactions/month** — photos, voice, barcodes, corrections, everything. Enjoy!"
        )
    except Exception:
        log.info("Could not DM user %s about premium activation", user_id)


@bot.event
async def on_entitlement_update(entitlement: discord.Entitlement):
    """Fired when a subscription is cancelled/expired."""
    if entitlement.sku_id != PRO_SKU_ID:
        return
    # Check if the entitlement has ended (ends_at is set and in the past)
    if entitlement.ends_at and entitlement.ends_at <= now_tz():
        user_id = str(entitlement.user_id)
        set_premium(user_id, False)
        log.info("Premium DEACTIVATED for user %s (entitlement %s expired)", user_id, entitlement.id)
        try:
            user = await bot.fetch_user(entitlement.user_id)
            await user.send(
                f"Your **FoodTracker Pro** subscription has ended. You're back to {FREE_DAILY_CAP} interactions/day.\n\n"
                f"Resubscribe anytime to get {PREMIUM_MONTHLY_CAP}/month back!"
            )
        except Exception:
            log.info("Could not DM user %s about premium deactivation", user_id)


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

        # --- INTERACTION CAP CHECK (all modalities) ---
        allowed, remaining = check_interaction_cap(user_id)
        if not allowed:
            if user_is_premium:
                await message.reply(f"You've used all **{PREMIUM_MONTHLY_CAP} interactions** this month. Your limit resets on the 1st!")
            else:
                await _send_premium_upsell(message, "interactions")
            await bot.process_commands(message)
            return

        # --- REPLY-BASED CORRECTION ---
        # If user replies to a bot's Nutrition Breakdown embed, treat as correction
        if message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            is_correction_reply = (
                ref_msg.author == bot.user
                and ref_msg.embeds
                and any("Nutrition Breakdown" in (e.title or "") for e in ref_msg.embeds)
            )
            if is_correction_reply:
                await _handle_correction(message)
                increment_interaction_count(user_id)
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

        # --- IMAGE INPUT ---
        if has_images:
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

                                # Try to read nutrition label from the image — prefer over Open Food Facts
                                ext_bc = attachment.filename.rsplit(".", 1)[-1].lower()
                                media_map_bc = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
                                media_type_bc = media_map_bc.get(ext_bc, "image/jpeg")
                                label = await read_nutrition_label(image_bytes, media_type_bc, product["name"], barcode)
                                if label:
                                    # Override product values with label values
                                    log.info("Using nutrition label values instead of Open Food Facts for %s", product["name"])
                                    product["kcal"] = label["kcal"]
                                    product["protein"] = label["protein"]
                                    product["carbs"] = label["carbs"]
                                    product["fat"] = label["fat"]
                                    product["portion_note"] = f"{label['portion_note']} (from label)"

                                analysis = build_barcode_analysis(product, multiplier, qty_text)
                                source = "label" if label else "OFF"
                                thumb = product.get("image_url") or attachment.url
                                await _process_meal_analysis(
                                    message, analysis,
                                    f"barcode: {barcode} ({product['name']}) x{multiplier:.2g} [{source}]",
                                    thumbnail_url=thumb,
                                )
                                increment_photo_count(user_id)
                                increment_interaction_count(user_id)
                                continue
                            else:
                                await message.reply(f"📦 Barcode `{barcode}` detected but not found in Open Food Facts. Analyzing the image instead...")

                        # No barcode (or barcode not found) — try label, then AI vision
                        ext = attachment.filename.rsplit(".", 1)[-1].lower()
                        media_map = {
                            "png": "image/png", "jpg": "image/jpeg",
                            "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
                        }
                        media_type = media_map.get(ext, "image/jpeg")

                        # Try reading a nutrition label first (no barcode needed)
                        label = await read_nutrition_label(image_bytes, media_type)
                        if label:
                            # Build a product-like dict from the label
                            label_product = {
                                "name": "Product (from nutrition label)",
                                "brand": "",
                                "kcal": label["kcal"],
                                "protein": label["protein"],
                                "carbs": label["carbs"],
                                "fat": label["fat"],
                                "portion_note": label["portion_note"],
                                "image_url": "",
                                "barcode": "",
                            }
                            qty_text = message.content.strip()
                            multiplier = 1.0
                            if qty_text:
                                multiplier = parse_quantity_modifier(qty_text)
                                if multiplier is None:
                                    multiplier = await interpret_quantity_with_ai(
                                        qty_text, "product", label["portion_note"]
                                    )
                            analysis = build_barcode_analysis(label_product, multiplier, qty_text)
                            await _process_meal_analysis(
                                message, analysis, f"label: {label['kcal']} kcal",
                                thumbnail_url=attachment.url,
                            )
                            increment_photo_count(user_id)
                            increment_interaction_count(user_id)
                            continue

                        analysis = await analyze_food_image(image_bytes, media_type)
                        await _process_meal_analysis(
                            message, analysis, attachment.filename,
                            thumbnail_url=attachment.url,
                        )
                        increment_photo_count(user_id)
                        increment_interaction_count(user_id)
                    except Exception as e:
                        log.exception("Error analyzing image")
                        await message.reply(f"⚠️ Couldn't analyze that image: {e}")

        # --- AUDIO / VOICE MESSAGE INPUT ---
        elif has_audio:
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
                    increment_interaction_count(user_id)
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
                        increment_interaction_count(user_id)
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
    water_from_food = parsed.get("water_ml", 0)

    meal_id = add_meal(
        user_id, day_key, window_idx,
        parsed["kcal"], parsed["protein"], parsed["carbs"], parsed["fat"],
        description, analysis,
        photo_url=thumbnail_url,
        water_ml=water_from_food,
    )
    log.info("Stored meal #%s: %s kcal for user %s on %s (window %d, water=%dml)",
             meal_id, parsed["kcal"], user_id, day_key, window_idx, water_from_food)

    # Auto-log food water content
    if water_from_food > 0:
        add_water(user_id, water_from_food, source="food")

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

    # Water prompt after meal
    day_water = get_day_water(user_id, day_key)
    water_line = f"💧 **Water check!** "
    if water_from_food > 0:
        water_line += f"~{water_from_food}ml water from this meal auto-logged. "
    water_line += f"Today: **{day_water}ml** / {DAILY_WATER_TARGET_ML}ml"
    remaining_water = DAILY_WATER_TARGET_ML - day_water
    if remaining_water > 0:
        water_line += f" — {remaining_water}ml to go!"
        water_line += f"\n*Did you drink water with this meal? Log it: `!water 250`*"
    else:
        water_line += " ✅ Target reached!"
    await message.channel.send(water_line)

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
    """Send a premium upsell embed when a free user hits their daily cap."""
    embed = discord.Embed(
        title=f"⚡ Daily limit reached",
        description=PREMIUM_UPSELL,
        color=discord.Color.purple(),
        timestamp=now_tz(),
    )
    trial_left = get_trial_days_left(str(message.author.id))
    if trial_left is not None:
        embed.set_footer(text=f"Trial: {trial_left} days remaining")
    else:
        embed.set_footer(text=f"Type !trial for a free {TRIAL_DAYS}-day upgrade!")
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
        macros = get_macro_targets(user_id)
        if current:
            lines = [f"🎯 Your daily target is **{current} kcal**."]
            if macros and macros["protein"] is not None:
                lines.append(f"🥩 Protein: **{macros['protein']}g** | 🧈 Fat: **{macros['fat']}g** | 🍞 Carbs: **{macros['carbs']}g** (auto)")
            else:
                lines.append("💡 Set macro targets with `!macros protein=150` (fat defaults to 50g, carbs auto-calculated).")
            lines.append("\nUse `!target <number>` to change kcal, `!macros` to adjust protein/fat.")
            await ctx.reply("\n".join(lines))
        else:
            await ctx.reply("No target set yet. Use `!target <number>` to set your daily calorie goal.")
        return

    if kcal < 500 or kcal > 10000:
        await ctx.reply("Please set a target between 500 and 10,000 kcal.")
        return

    set_target_kcal(user_id, kcal)
    macros = get_macro_targets(user_id)
    if macros and macros["protein"] is not None:
        # Recalculate carbs with new kcal
        carbs_kcal = kcal - (macros["protein"] * 4) - (macros["fat"] * 9)
        carbs = max(0, int(carbs_kcal / 4))
        await ctx.reply(
            f"✅ Daily calorie target set to **{kcal} kcal**.\n"
            f"🥩 Protein: **{macros['protein']}g** | 🧈 Fat: **{macros['fat']}g** | 🍞 Carbs: **{carbs}g** (auto-calculated)"
        )
    else:
        await ctx.reply(
            f"✅ Daily calorie target set to **{kcal} kcal**.\n"
            f"💡 Now set your protein goal: `!macros protein=150`"
        )


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


# ---------------------------------------------------------------------------
# !info — Carousel infographic with pagination buttons
# ---------------------------------------------------------------------------
INFO_PAGES = [
    discord.Embed(
        title="🍽️ FoodTracker — How It Works",
        description=(
            "Track your meals, hit your calorie goals, compete with friends.\n\n"
            "**Get started in 30 seconds:**\n"
            "1️⃣ Type `!join` in the group channel to get your own private tracking channel\n"
            "2️⃣ Type `!target 2000` to set your daily calorie target\n"
            "3️⃣ Start logging meals — the bot handles the rest!"
        ),
        color=0xf97316,
    ),
    discord.Embed(
        title="📸 4 Easy Ways to Log Meals",
        description=(
            "**📸 Snap a Photo**\n"
            "Take a pic of your food — AI identifies every item with calories & macros.\n\n"
            "**📦 Scan a Barcode**\n"
            "Photo any product barcode for exact nutrition data. Add \"half\" or \"2 spoons\" for portions.\n\n"
            "**✍️ Type It Out**\n"
            "Just describe your meal: *\"two eggs, toast with butter, and coffee\"*\n\n"
            "**🎤 Voice Message**\n"
            "Record a voice note — the bot transcribes and analyzes it automatically."
        ),
        color=0xec4899,
    ),
    discord.Embed(
        title="🤖 What Happens After You Log",
        description=(
            "**Step 1 — AI Analyzes**\n"
            "Identifies foods, estimates portions & macros.\n\n"
            "**Step 2 — You Get a Breakdown**\n"
            "Calories, protein, carbs & fat per item + totals.\n\n"
            "**Step 3 — Budget Updates**\n"
            "See your remaining kcal split across your meal windows for the rest of the day."
        ),
        color=0x8b5cf6,
    ),
    discord.Embed(
        title="✏️ Made a Mistake? Just Reply",
        description=(
            "If the bot gets something wrong, **reply to the nutrition breakdown** with your corrections — by text or voice.\n\n"
            "**Example replies:**\n"
            "🗣️ *\"the steak is 200g not 300g\"*\n"
            "🗣️ *\"those aren't radishes, they're tomatoes\"*\n"
            "🗣️ *\"remove the bread, I didn't eat it\"*\n"
            "🗣️ *\"add a glass of orange juice\"*\n\n"
            "💡 You can also use `!undo` to remove the last meal, `!delete 2` to remove a specific meal, or `!edit 2 kcal=400` to manually adjust values."
        ),
        color=0x06b6d4,
    ),
    discord.Embed(
        title="⏰ Reminders Throughout the Day",
        description=(
            "You'll get a friendly nudge at each meal window:\n\n"
            "🌅 **8:00** — Breakfast\n"
            "🍎 **11:00** — Morning Snack\n"
            "🥗 **14:00** — Lunch\n"
            "🍌 **17:00** — Afternoon Snack\n"
            "🍽️ **20:00** — Dinner\n"
            "🌙 **23:00** — Evening Snack\n\n"
            "At **4am** you'll get a daily summary with body fat burn/gain estimate."
        ),
        color=0x10b981,
    ),
    discord.Embed(
        title="🏆 Compete With Friends",
        description=(
            "**🔒 Your Meals, Your Channel**\n"
            "Your meal photos and data stay in your private channel — only you and the bot can see them.\n\n"
            "**📢 Group Feed**\n"
            "Every meal posts a quick summary to the shared group channel so friends can cheer you on.\n\n"
            "**🏆 Daily Leaderboard**\n"
            "Who's closest to their calorie target? Check the rankings with `!leaderboard` anytime."
        ),
        color=0x3b82f6,
    ),
    discord.Embed(
        title="⌨️ Quick Command Reference",
        description=(
            "`!join` — Create your private channel\n"
            "`!target 2000` — Set daily calorie goal\n"
            "`!macros protein=150` — Set macro targets\n"
            "`!weight 82.5` — Log weight (kg)\n"
            "`!water 250` — Log water (ml)\n"
            "`!budget` — Remaining kcal + macros + water\n"
            "`!today` — See all meals logged today\n"
            "`!streak` — View your target streak\n"
            "`!weekly` — Weekly summary report\n"
            "`!monthly` — Monthly summary report\n"
            "`!history` — View day's meals + photo GIF\n"
            "`!undo` — Remove last meal\n"
            "`!delete 2` — Delete a specific meal\n"
            "`!edit 2 kcal=400` — Manually fix values\n"
            "`!leaderboard` — Today's group rankings\n"
            "`!pro` — View Pro features & status\n"
            "`!trial` — Start a free 7-day Pro trial\n"
            "`!info` — This guide!"
        ),
        color=0x8b5cf6,
    ),
]

# Set footers with page numbers
for i, page in enumerate(INFO_PAGES):
    page.set_footer(text=f"Page {i + 1}/{len(INFO_PAGES)} — Use the buttons to navigate")


class InfoCarouselView(discord.ui.View):
    """Paginated embed carousel for !info command."""

    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.page = 0
        self.author_id = author_id

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Use `!info` to get your own carousel!", ephemeral=True)
            return
        self.page = (self.page - 1) % len(INFO_PAGES)
        await interaction.response.edit_message(embed=INFO_PAGES[self.page])

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Use `!info` to get your own carousel!", ephemeral=True)
            return
        self.page = (self.page + 1) % len(INFO_PAGES)
        await interaction.response.edit_message(embed=INFO_PAGES[self.page])


@bot.command(name="info")
async def cmd_info(ctx: commands.Context):
    """Show the FoodTracker guide as a carousel."""
    view = InfoCarouselView(author_id=ctx.author.id)
    await ctx.reply(embed=INFO_PAGES[0], view=view)


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
        allowed, remaining = check_interaction_cap(user_id)
        status += f"\n📊 Interactions this month: {PREMIUM_MONTHLY_CAP - remaining}/{PREMIUM_MONTHLY_CAP}"
        embed = discord.Embed(
            title="✨  FoodTracker Pro",
            description=status,
            color=discord.Color.green(),
            timestamp=now_tz(),
        )
    else:
        allowed, remaining = check_interaction_cap(user_id)
        status = f"📊 Interactions today: {FREE_DAILY_CAP - remaining}/{FREE_DAILY_CAP}\n\n" + PREMIUM_UPSELL
        embed = discord.Embed(
            title="✨  FoodTracker Pro",
            description=status,
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
            f"Your free trial has expired. You're back to **{FREE_DAILY_CAP} interactions/day**.\n\n"
            f"Upgrade to **FoodTracker Pro** for {PREMIUM_PRICE} to get **{PREMIUM_MONTHLY_CAP} interactions/month**!\n\n"
            "*(Discord Premium App subscriptions coming soon — for now, ask a server admin to activate your Pro status with `!setpremium @user`)*"
        )
        return

    start_trial(user_id)
    embed = discord.Embed(
        title="🎉  Free Trial Activated!",
        description=(
            f"You now have **{TRIAL_DAYS} days** of FoodTracker Pro!\n\n"
            f"**Upgraded to {PREMIUM_MONTHLY_CAP} interactions/month** (from {FREE_DAILY_CAP}/day).\n\n"
            "All features are available: photos, voice, barcodes, corrections — go wild!\n\n"
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


@bot.command(name="macros")
async def cmd_macros(ctx: commands.Context, *, values: str = None):
    """Set or view your macro targets. Usage: !macros protein=150 fat=60"""
    user_id = str(ctx.author.id)
    macros = get_macro_targets(user_id)

    if values is None:
        # Show current macro targets
        if not macros:
            await ctx.reply("Set your calorie target first with `!target <kcal>`, then `!macros protein=150`.")
            return
        if macros["protein"] is None:
            await ctx.reply(
                f"🎯 Calories: **{macros['kcal']} kcal** | 🧈 Fat: **{macros['fat']}g** (default)\n\n"
                f"Set your protein target: `!macros protein=150`\n"
                f"Carbs will be auto-calculated from the remainder."
            )
        else:
            await ctx.reply(
                f"🎯 **Daily Macro Targets**\n"
                f"Calories: **{macros['kcal']} kcal**\n"
                f"🥩 Protein: **{macros['protein']}g** ({macros['protein'] * 4} kcal)\n"
                f"🧈 Fat: **{macros['fat']}g** ({macros['fat'] * 9} kcal)\n"
                f"🍞 Carbs: **{macros['carbs']}g** ({macros['carbs'] * 4} kcal) — auto-calculated\n\n"
                f"Adjust: `!macros protein=X fat=X`"
            )
        return

    if not macros:
        await ctx.reply("Set your calorie target first with `!target <kcal>`.")
        return

    # Parse key=value pairs
    new_protein = None
    new_fat = None
    for pair in values.split():
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        try:
            num = int(val)
        except ValueError:
            await ctx.reply(f"Invalid value for `{key}`: `{val}`. Use a whole number.")
            return
        key = key.lower().strip()
        if key in ("protein", "p"):
            if num < 0 or num > 500:
                await ctx.reply("Protein target must be between 0 and 500g.")
                return
            new_protein = num
        elif key in ("fat", "f"):
            if num < 30:
                await ctx.reply("⚠️ Fat cannot be set below **30g** — this is the minimum for hormonal health. Setting to 30g.")
                num = 30
            if num > 300:
                await ctx.reply("Fat target must be 300g or less.")
                return
            new_fat = num
        else:
            await ctx.reply(f"Unknown macro: `{key}`. Use: `protein` (or `p`), `fat` (or `f`). Carbs are auto-calculated.")
            return

    if new_protein is None and new_fat is None:
        await ctx.reply("Usage: `!macros protein=150` or `!macros protein=150 fat=60`")
        return

    set_macro_targets(user_id, protein=new_protein, fat=new_fat)

    # Show updated values
    updated = get_macro_targets(user_id)
    if updated["protein"] is not None:
        await ctx.reply(
            f"✅ **Macro targets updated!**\n"
            f"🥩 Protein: **{updated['protein']}g** ({updated['protein'] * 4} kcal)\n"
            f"🧈 Fat: **{updated['fat']}g** ({updated['fat'] * 9} kcal)\n"
            f"🍞 Carbs: **{updated['carbs']}g** ({updated['carbs'] * 4} kcal) — auto-calculated\n"
            f"🎯 Total: **{updated['kcal']} kcal**"
        )
    else:
        await ctx.reply(f"✅ Fat target set to **{updated['fat']}g**. Set protein with `!macros protein=150`.")


@bot.command(name="streak")
async def cmd_streak(ctx: commands.Context):
    """Show your current streak of days hitting your calorie target."""
    user_id = str(ctx.author.id)
    streak = get_streak(user_id)

    if streak == 0:
        await ctx.reply("🔥 No active streak yet. Log meals and stay within your calorie target to start building one!")
    elif streak == 1:
        await ctx.reply("🔥 **1 day** streak! You hit your target yesterday. Keep it going today!")
    else:
        # Fun milestones
        if streak >= 30:
            badge = "🏆💎"
            msg = "Incredible discipline!"
        elif streak >= 14:
            badge = "🏆🔥"
            msg = "Two weeks strong!"
        elif streak >= 7:
            badge = "⭐🔥"
            msg = "One full week!"
        elif streak >= 3:
            badge = "🔥"
            msg = "Building momentum!"
        else:
            badge = "🔥"
            msg = "Keep going!"
        await ctx.reply(f"{badge} **{streak}-day streak!** {msg}")


@bot.command(name="weight")
async def cmd_weight(ctx: commands.Context, kg: float = None):
    """Log your weight or view history. Usage: !weight 82.5"""
    user_id = str(ctx.author.id)

    if kg is None:
        history = get_weight_history(user_id, limit=14)
        if not history:
            await ctx.reply("⚖️ No weight logged yet. Use `!weight 82.5` to start tracking.")
            return
        lines = ["**⚖️ Weight History** (last 14 entries)\n"]
        for i, entry in enumerate(history):
            marker = " ◀️" if i == 0 else ""
            if i > 0:
                diff = entry["weight_kg"] - history[i-1]["weight_kg"]
                sign = "+" if diff > 0 else ""
                trend = f" ({sign}{diff:.1f})"
            else:
                trend = ""
            lines.append(f"  {entry['day_key']}: **{entry['weight_kg']:.1f} kg**{trend}{marker}")

        # Overall change
        if len(history) >= 2:
            change = history[0]["weight_kg"] - history[-1]["weight_kg"]
            period_days = len(history)
            sign = "+" if change > 0 else ""
            lines.append(f"\n📈 Change over last {period_days} entries: **{sign}{change:.1f} kg**")

        await ctx.reply("\n".join(lines))
        return

    if kg < 20 or kg > 300:
        await ctx.reply("Please enter a weight between 20 and 300 kg.")
        return

    is_new = log_weight(user_id, kg)
    history = get_weight_history(user_id, limit=2)

    response = f"✅ Weight logged: **{kg:.1f} kg**"
    if len(history) >= 2:
        diff = kg - history[1]["weight_kg"]
        if diff < 0:
            response += f" — down **{abs(diff):.1f} kg** since last weigh-in! 📉"
        elif diff > 0:
            response += f" — up **{diff:.1f} kg** since last weigh-in 📈"
        else:
            response += " — same as last time ⚖️"
    if not is_new:
        response += "\n*(Updated today's entry)*"

    await ctx.reply(response)


@bot.command(name="water")
async def cmd_water(ctx: commands.Context, amount: int = None):
    """Log water intake or view today's total. Usage: !water 250 (in ml)"""
    user_id = str(ctx.author.id)
    dt = now_tz()
    day_key = get_food_day(dt)

    if amount is None:
        total = get_day_water(user_id, day_key)
        pct = min(100, int(total / DAILY_WATER_TARGET_ML * 100))
        bar_full = pct // 10
        bar_empty = 10 - bar_full
        bar = "🟦" * bar_full + "⬜" * bar_empty
        lines = [
            f"💧 **Water Today**: **{total}ml** / {DAILY_WATER_TARGET_ML}ml ({pct}%)",
            bar,
        ]
        remaining = DAILY_WATER_TARGET_ML - total
        if remaining > 0:
            lines.append(f"Still need **{remaining}ml** — that's about {remaining // 250} glasses!")
        else:
            lines.append("✅ Daily target reached! Great hydration!")
        lines.append(f"\nLog water: `!water 250` (ml)")
        await ctx.reply("\n".join(lines))
        return

    if amount < 1 or amount > 5000:
        await ctx.reply("Please enter an amount between 1 and 5000 ml.")
        return

    total = add_water(user_id, amount, source="manual")
    pct = min(100, int(total / DAILY_WATER_TARGET_ML * 100))
    bar_full = pct // 10
    bar_empty = 10 - bar_full
    bar = "🟦" * bar_full + "⬜" * bar_empty

    response = f"💧 +**{amount}ml** logged! Today: **{total}ml** / {DAILY_WATER_TARGET_ML}ml ({pct}%)\n{bar}"
    remaining = DAILY_WATER_TARGET_ML - total
    if remaining <= 0:
        response += "\n✅ Daily water target reached!"
    elif remaining <= 500:
        response += f"\nAlmost there — just **{remaining}ml** to go!"

    await ctx.reply(response)


@bot.command(name="history")
async def cmd_history(ctx: commands.Context, date: str = None):
    """View a day's meal photo GIF. Usage: !history or !history 2026-03-16"""
    user_id = str(ctx.author.id)
    dt = now_tz()

    if date is None:
        # Default to yesterday (today is still in progress)
        day_dt = datetime.strptime(get_food_day(dt), "%Y-%m-%d") - timedelta(days=1)
        date = day_dt.strftime("%Y-%m-%d")
    else:
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            await ctx.reply("Invalid date format. Use: `!history 2026-03-16`")
            return

    meals = get_day_meals(user_id, date)
    if not meals:
        await ctx.reply(f"No meals logged on {date}.")
        return

    # Show meal list
    totals = get_day_totals(user_id, date)
    lines = [f"**📋 Meals on {date}** ({len(meals)} meals, {totals['total_kcal']} kcal)\n"]
    for i, m in enumerate(meals, 1):
        w = MEAL_WINDOWS[m["window_idx"]]
        ts = datetime.fromisoformat(m["timestamp"]).strftime("%H:%M")
        photo = "📸" if m.get("photo_url") else "✍️"
        lines.append(f"  {photo} {w[3]} {ts} — {m['kcal']} kcal ({m['protein_g']:.0f}P/{m['carbs_g']:.0f}C/{m['fat_g']:.0f}F)")

    lines.append(f"\n**Total**: {totals['total_kcal']} kcal | {totals['total_protein']:.0f}P / {totals['total_carbs']:.0f}C / {totals['total_fat']:.0f}F")

    # Try to build and send GIF
    async with ctx.typing():
        gif_buf = await build_day_gif(user_id, date)

    if gif_buf:
        gif_file = discord.File(gif_buf, filename=f"meals-{date}.gif")
        embed = discord.Embed(
            description="\n".join(lines),
            color=discord.Color.green(),
            timestamp=dt,
        )
        embed.set_image(url=f"attachment://meals-{date}.gif")
        await ctx.reply(embed=embed, file=gif_file)
    else:
        await ctx.reply("\n".join(lines))


# ---------------------------------------------------------------------------
# Weekly & Monthly summary reports
# ---------------------------------------------------------------------------
def build_weekly_report(user_id: str, end_date: str | None = None) -> discord.Embed | None:
    """Build a weekly report embed for a user. end_date defaults to yesterday."""
    dt = now_tz()
    if end_date is None:
        end_dt = datetime.strptime(get_food_day(dt), "%Y-%m-%d") - timedelta(days=1)
    else:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=6)
    start = start_dt.strftime("%Y-%m-%d")
    end = end_dt.strftime("%Y-%m-%d")

    totals = get_period_totals(user_id, start, end)
    if totals["meal_count"] == 0:
        return None

    macros = get_macro_targets(user_id)
    target = macros["kcal"] if macros else 2000
    days_logged = totals["days_logged"]
    daily_breakdown = totals["daily_breakdown"]

    # Averages
    avg_kcal = totals["total_kcal"] / days_logged if days_logged else 0
    avg_protein = totals["total_protein"] / days_logged if days_logged else 0
    avg_carbs = totals["total_carbs"] / days_logged if days_logged else 0
    avg_fat = totals["total_fat"] / days_logged if days_logged else 0

    # Days on target
    days_on_target = sum(1 for d in daily_breakdown if d["day_kcal"] <= target)

    # Streak
    streak = get_streak(user_id)

    # Fat warning: days below 50g
    low_fat_days = sum(1 for d in daily_breakdown if d["day_fat"] < 50)

    # Net deficit/surplus for the week
    total_target = target * days_logged
    net_diff = total_target - totals["total_kcal"]
    fat_change_g = (net_diff / 7700) * 1000

    lines = [
        f"📅 **{start}** to **{end}** ({days_logged} days logged)\n",
        f"**📊 Weekly Averages (per day)**",
        f"🎯 Calories: **{avg_kcal:.0f}** / {target} kcal",
        f"🥩 Protein: **{avg_protein:.0f}g**",
        f"🧈 Fat: **{avg_fat:.0f}g**",
        f"🍞 Carbs: **{avg_carbs:.0f}g**\n",
    ]

    # Macro target comparison
    if macros and macros["protein"] is not None:
        lines.append("**🎯 Macro Targets vs Actual**")
        p_diff = avg_protein - macros["protein"]
        f_diff = avg_fat - macros["fat"]
        c_diff = avg_carbs - macros["carbs"]
        p_emoji = "✅" if abs(p_diff) <= 15 else ("⬆️" if p_diff > 0 else "⬇️")
        f_emoji = "✅" if abs(f_diff) <= 10 else ("⬆️" if f_diff > 0 else "⬇️")
        c_emoji = "✅" if abs(c_diff) <= 20 else ("⬆️" if c_diff > 0 else "⬇️")
        lines.append(f"  {p_emoji} Protein: {avg_protein:.0f}g / {macros['protein']}g target")
        lines.append(f"  {f_emoji} Fat: {avg_fat:.0f}g / {macros['fat']}g target")
        lines.append(f"  {c_emoji} Carbs: {avg_carbs:.0f}g / {macros['carbs']}g target")
        lines.append("")

    # Consistency
    lines.append("**📈 Consistency**")
    lines.append(f"  ✅ Days on target: **{days_on_target}/{days_logged}**")
    lines.append(f"  🍽️ Total meals: **{totals['meal_count']}** ({totals['meal_count']/days_logged:.1f}/day avg)")
    if streak > 0:
        lines.append(f"  🔥 Current streak: **{streak} days**")
    lines.append("")

    # Body composition
    if net_diff > 0:
        lines.append(f"**🔥 Weekly deficit: {net_diff:.0f} kcal** → ~{fat_change_g:.0f}g body fat lost")
    elif net_diff < 0:
        lines.append(f"**📈 Weekly surplus: {abs(net_diff):.0f} kcal** → ~{abs(fat_change_g):.0f}g potential fat gain")
    else:
        lines.append("**⚖️ Maintenance week** — calories in = calories out")

    # Fat warning
    if low_fat_days > 2:
        lines.append(
            f"\n⚠️ **Hormonal health warning:** Your fat intake was below 50g on **{low_fat_days} days** this week. "
            f"For optimal hormonal health, keep fat intake above 50g daily. Adjust with `!macros fat=50`."
        )

    # Weight trend
    weights = get_weight_for_period(user_id, start, end)
    if weights:
        lines.append("")
        first_w = weights[0]["weight_kg"]
        last_w = weights[-1]["weight_kg"]
        w_change = last_w - first_w
        w_sign = "+" if w_change > 0 else ""
        lines.append(f"**⚖️ Weight**: {first_w:.1f} → {last_w:.1f} kg (**{w_sign}{w_change:.1f} kg**)")

    # Water
    water_data = get_period_water(user_id, start, end)
    if water_data["total_ml"] > 0:
        lines.append(f"💧 **Water avg**: {water_data['daily_avg']:.0f}ml/day ({water_data['days_logged']} days tracked)")

    # Day-by-day breakdown
    lines.append("\n**📋 Day-by-Day**")
    for d in daily_breakdown:
        day_dt = datetime.strptime(d["day_key"], "%Y-%m-%d")
        day_name = day_dt.strftime("%a")
        on_target = "✅" if d["day_kcal"] <= target else "⚠️"
        lines.append(f"  {on_target} {day_name} {d['day_key']}: {d['day_kcal']:.0f} kcal | {d['day_protein']:.0f}P / {d['day_carbs']:.0f}C / {d['day_fat']:.0f}F")

    embed = discord.Embed(
        title="📊  Weekly Report",
        description="\n".join(lines),
        color=discord.Color.blue(),
        timestamp=dt,
    )
    return embed


def build_monthly_report(user_id: str, year: int = None, month: int = None) -> discord.Embed | None:
    """Build a monthly report embed for a user."""
    dt = now_tz()
    if year is None or month is None:
        # Default to previous month
        first_of_this_month = dt.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        year = last_month_end.year
        month = last_month_end.month

    _, last_day = calendar.monthrange(year, month)
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}"

    totals = get_period_totals(user_id, start, end)
    if totals["meal_count"] == 0:
        return None

    macros = get_macro_targets(user_id)
    target = macros["kcal"] if macros else 2000
    days_logged = totals["days_logged"]
    daily_breakdown = totals["daily_breakdown"]

    # Averages
    avg_kcal = totals["total_kcal"] / days_logged if days_logged else 0
    avg_protein = totals["total_protein"] / days_logged if days_logged else 0
    avg_carbs = totals["total_carbs"] / days_logged if days_logged else 0
    avg_fat = totals["total_fat"] / days_logged if days_logged else 0

    # Days on target
    days_on_target = sum(1 for d in daily_breakdown if d["day_kcal"] <= target)

    # Streak
    streak = get_streak(user_id)

    # Fat warning
    low_fat_days = sum(1 for d in daily_breakdown if d["day_fat"] < 50)
    low_fat_weeks = low_fat_days  # total days, we'll report it overall

    # Net diff
    total_target = target * days_logged
    net_diff = total_target - totals["total_kcal"]
    fat_change_g = (net_diff / 7700) * 1000

    month_name = calendar.month_name[month]
    lines = [
        f"📅 **{month_name} {year}** ({days_logged} days logged)\n",
        f"**📊 Monthly Averages (per day)**",
        f"🎯 Calories: **{avg_kcal:.0f}** / {target} kcal",
        f"🥩 Protein: **{avg_protein:.0f}g**",
        f"🧈 Fat: **{avg_fat:.0f}g**",
        f"🍞 Carbs: **{avg_carbs:.0f}g**\n",
    ]

    # Macro targets
    if macros and macros["protein"] is not None:
        lines.append("**🎯 Macro Targets vs Actual**")
        p_diff = avg_protein - macros["protein"]
        f_diff = avg_fat - macros["fat"]
        c_diff = avg_carbs - macros["carbs"]
        p_emoji = "✅" if abs(p_diff) <= 15 else ("⬆️" if p_diff > 0 else "⬇️")
        f_emoji = "✅" if abs(f_diff) <= 10 else ("⬆️" if f_diff > 0 else "⬇️")
        c_emoji = "✅" if abs(c_diff) <= 20 else ("⬆️" if c_diff > 0 else "⬇️")
        lines.append(f"  {p_emoji} Protein: {avg_protein:.0f}g / {macros['protein']}g target")
        lines.append(f"  {f_emoji} Fat: {avg_fat:.0f}g / {macros['fat']}g target")
        lines.append(f"  {c_emoji} Carbs: {avg_carbs:.0f}g / {macros['carbs']}g target")
        lines.append("")

    lines.append("**📈 Consistency**")
    lines.append(f"  ✅ Days on target: **{days_on_target}/{days_logged}** ({days_on_target/days_logged*100:.0f}%)")
    lines.append(f"  🍽️ Total meals: **{totals['meal_count']}** ({totals['meal_count']/days_logged:.1f}/day avg)")
    if streak > 0:
        lines.append(f"  🔥 Current streak: **{streak} days**")
    lines.append("")

    # Body composition
    if net_diff > 0:
        lines.append(f"**🔥 Monthly deficit: {net_diff:.0f} kcal** → ~{fat_change_g:.0f}g body fat lost (~{fat_change_g/1000:.2f} kg)")
    elif net_diff < 0:
        lines.append(f"**📈 Monthly surplus: {abs(net_diff):.0f} kcal** → ~{abs(fat_change_g):.0f}g potential fat gain (~{abs(fat_change_g)/1000:.2f} kg)")
    else:
        lines.append("**⚖️ Maintenance month** — calories in = calories out")

    # Fat warning
    if low_fat_days > 8:  # more than 2/week across the month
        lines.append(
            f"\n⚠️ **Hormonal health warning:** Your fat intake was below 50g on **{low_fat_days} days** this month. "
            f"For optimal hormonal health, keep fat intake above 50g daily."
        )

    # Weight trend
    weights = get_weight_for_period(user_id, start, end)
    if len(weights) >= 2:
        first_w = weights[0]["weight_kg"]
        last_w = weights[-1]["weight_kg"]
        w_change = last_w - first_w
        w_sign = "+" if w_change > 0 else ""
        lines.append(f"\n**⚖️ Weight**: {first_w:.1f} → {last_w:.1f} kg (**{w_sign}{w_change:.1f} kg** this month)")

    # Water
    water_data = get_period_water(user_id, start, end)
    if water_data["total_ml"] > 0:
        lines.append(f"💧 **Water avg**: {water_data['daily_avg']:.0f}ml/day ({water_data['days_logged']} days tracked)")

    # Weekly breakdown
    lines.append("\n**📋 Week-by-Week**")
    week_num = 1
    for i in range(0, len(daily_breakdown), 7):
        week_days = daily_breakdown[i:i+7]
        w_kcal = sum(d["day_kcal"] for d in week_days) / len(week_days)
        w_protein = sum(d["day_protein"] for d in week_days) / len(week_days)
        w_on_target = sum(1 for d in week_days if d["day_kcal"] <= target)
        lines.append(f"  Week {week_num}: avg {w_kcal:.0f} kcal | {w_protein:.0f}g P | {w_on_target}/{len(week_days)} on target")
        week_num += 1

    embed = discord.Embed(
        title=f"📊  Monthly Report — {month_name} {year}",
        description="\n".join(lines),
        color=discord.Color.purple(),
        timestamp=dt,
    )
    return embed


async def send_weekly_reports():
    """Monday 4:30am: send weekly reports to all users."""
    users = get_all_users()
    dt = now_tz()
    for u in users:
        ch_id = u.get("private_channel")
        if not ch_id:
            continue
        channel = bot.get_channel(ch_id)
        if not channel:
            continue
        embed = build_weekly_report(u["user_id"])
        if embed:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                log.warning("Failed to send weekly report to %s: %s", ch_id, e)
    log.info("Sent weekly reports to %d users", len(users))


async def send_monthly_reports():
    """1st of month 5:00am: send monthly reports for previous month."""
    users = get_all_users()
    dt = now_tz()
    # Previous month
    first_of_this_month = dt.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    year = last_month_end.year
    month = last_month_end.month

    for u in users:
        ch_id = u.get("private_channel")
        if not ch_id:
            continue
        channel = bot.get_channel(ch_id)
        if not channel:
            continue
        embed = build_monthly_report(u["user_id"], year, month)
        if embed:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                log.warning("Failed to send monthly report to %s: %s", ch_id, e)
    log.info("Sent monthly reports for %d-%02d to %d users", year, month, len(users))


@bot.command(name="weekly")
async def cmd_weekly(ctx: commands.Context):
    """Show your weekly summary report."""
    user_id = str(ctx.author.id)
    embed = build_weekly_report(user_id)
    if embed:
        await ctx.reply(embed=embed)
    else:
        await ctx.reply("No meals logged in the past 7 days.")


@bot.command(name="monthly")
async def cmd_monthly(ctx: commands.Context):
    """Show your monthly summary report (current month so far)."""
    user_id = str(ctx.author.id)
    dt = now_tz()
    # Show current month so far
    year = dt.year
    month = dt.month
    today = get_food_day(dt)
    start = f"{year:04d}-{month:02d}-01"

    totals = get_period_totals(user_id, start, today)
    if totals["meal_count"] == 0:
        await ctx.reply("No meals logged this month yet.")
        return

    # Build current month report
    embed = build_monthly_report(user_id, year, month)
    if embed:
        embed.title = f"📊  Monthly Report — {dt.strftime('%B %Y')} (so far)"
        await ctx.reply(embed=embed)
    else:
        await ctx.reply("No meals logged this month yet.")


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
