"""
Discord Food Tracker Bot
- Sends meal photo reminders at scheduled times
- Analyzes food photos using Claude Vision for macros & kcal
- Tracks daily calorie budget across 6 meal windows
- 4am daily summary with surplus/deficit + bodyfat estimate
"""

import os
import io
import re
import json
import base64
import logging
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
import anthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Berlin")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("foodbot")

# ---------------------------------------------------------------------------
# Meal windows — each window: (start_hour, end_hour, label, emoji)
# A "day" runs from 04:00 to 03:59 next day.
# Meals before 4am count towards the previous day's last window.
# Meals at/after 4am count towards the current day's first window.
# ---------------------------------------------------------------------------
MEAL_WINDOWS = [
    (8,  11, "Breakfast",       "🌅"),   # 08:00 – 10:59
    (11, 14, "Morning Snack",   "🍎"),   # 11:00 – 13:59
    (14, 17, "Lunch",           "🥗"),   # 14:00 – 16:59
    (17, 20, "Afternoon Snack", "🍌"),   # 17:00 – 19:59
    (20, 23, "Dinner",          "🍽️"),   # 20:00 – 22:59
    (23, 4,  "Evening Snack",   "🌙"),   # 23:00 – 03:59 (crosses midnight)
]

# Reminder hours (start of each window)
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
            user_id     TEXT PRIMARY KEY,
            target_kcal INTEGER NOT NULL DEFAULT 2000
        );
        CREATE TABLE IF NOT EXISTS meals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            day_key     TEXT NOT NULL,       -- YYYY-MM-DD (the "food day", shifts at 4am)
            window_idx  INTEGER NOT NULL,    -- 0-5
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
    conn.commit()
    conn.close()
    log.info("Database initialized at %s", DB_PATH)

# ---------------------------------------------------------------------------
# Time / window helpers
# ---------------------------------------------------------------------------
def now_tz() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))

def get_food_day(dt: datetime) -> str:
    """Return the 'food day' key. Before 4am counts as previous day."""
    if dt.hour < 4:
        dt = dt - timedelta(days=1)
    return dt.strftime("%Y-%m-%d")

def get_current_window_idx(dt: datetime) -> int:
    """Return which meal window (0-5) the given time falls into.
    Times between 4:00-7:59 are before any window (return -1)."""
    h = dt.hour
    if 4 <= h < 8:
        return -1  # between day boundary and first window
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
    # 23:00-23:59 or 00:00-03:59
    return 5

def get_remaining_windows(dt: datetime) -> list[int]:
    """Return indices of windows that haven't ended yet (including current)."""
    h = dt.hour
    remaining = []
    if h < 4:
        # We're in window 5 (last window), nothing after
        return [5]
    if 4 <= h < 8:
        # Before first window, all windows remain
        return [0, 1, 2, 3, 4, 5]
    for i, (start, end, _, _) in enumerate(MEAL_WINDOWS):
        if i < 5:  # normal windows
            if h < end:
                remaining.append(i)
        else:  # last window (23-4)
            remaining.append(i)  # always remaining until 4am
    return remaining

def is_last_window(dt: datetime) -> bool:
    """Check if we're in the last meal window (23:00-03:59)."""
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
# Claude Vision client
# ---------------------------------------------------------------------------
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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
    """Extract the $$TOTALS: ...$$ line from Claude's response."""
    match = re.search(r'\$\$TOTALS:\s*kcal=(\d+),\s*protein=(\d+),\s*carbs=(\d+),\s*fat=(\d+)\$\$', analysis)
    if match:
        return {
            "kcal": int(match.group(1)),
            "protein": float(match.group(2)),
            "carbs": float(match.group(3)),
            "fat": float(match.group(4)),
        }
    # Fallback: try to find any calorie number
    kcal_match = re.search(r'(\d[,\d]*)\s*(?:kcal|calories|cal)\b', analysis, re.IGNORECASE)
    if kcal_match:
        kcal_str = kcal_match.group(1).replace(",", "")
        return {"kcal": int(kcal_str), "protein": 0, "carbs": 0, "fat": 0}
    return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}


def strip_totals_line(analysis: str) -> str:
    """Remove the $$TOTALS: ...$$ line from the display text."""
    return re.sub(r'\n?\$\$TOTALS:.*?\$\$\n?', '', analysis).strip()


async def analyze_food_image(image_bytes: bytes, media_type: str = "image/jpeg") -> str:
    """Send a food photo to Claude Vision and return the macro breakdown."""
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this meal photo. Estimate macros (protein, carbs, fat) and total calories.",
                    },
                ],
            }
        ],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Budget / tracking helpers
# ---------------------------------------------------------------------------
def build_budget_text(user_id: str, day_key: str, dt: datetime) -> str:
    """Build the remaining calorie budget text after a meal."""
    target = get_target_kcal(user_id)
    if target is None:
        return "⚠️ No calorie target set. Use `!target <kcal>` to set one."

    totals = get_day_totals(user_id, day_key)
    consumed = totals["total_kcal"]
    remaining = target - consumed

    if is_last_window(dt):
        # Last window: just show total + surplus/deficit + bodyfat
        return _build_end_of_day_text(target, consumed, remaining, totals)

    # Normal window: show remaining total + per-window breakdown
    remaining_windows = get_remaining_windows(dt)
    # Exclude already-passed windows
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
    """Build the last-window summary (no per-window breakdown)."""
    lines = []

    if remaining > 0:
        lines.append(f"**🌙 Last window — {remaining} kcal remaining** (of {target} kcal)")
    elif remaining == 0:
        lines.append(f"**✅ You've hit your {target} kcal target exactly!**")
    else:
        lines.append(f"**⚠️ {abs(remaining)} kcal over target!** ({consumed} / {target} kcal)")

    lines.append(f"📊 Today: {consumed} kcal | {totals['total_protein']:.0f}g P / {totals['total_carbs']:.0f}g C / {totals['total_fat']:.0f}g F")

    # Deficit = fat burned; surplus = fat gained
    # ~7,700 kcal ≈ 1 kg of body fat
    deficit = target - consumed  # positive = deficit = fat loss
    if deficit > 0:
        fat_g = (deficit / 7700) * 1000
        lines.append(f"\n🔥 On track to exhale **{fat_g:.0f}g of body fat** today! Keep going.")
    elif deficit < 0:
        fat_g = (abs(deficit) / 7700) * 1000
        lines.append(f"\n📈 Surplus of {abs(deficit)} kcal (~{fat_g:.0f}g potential fat storage).")

    return "\n".join(lines)


def build_daily_summary(user_id: str, day_key: str) -> str:
    """Build the 4am daily summary for the previous food day."""
    target = get_target_kcal(user_id)
    totals = get_day_totals(user_id, day_key)
    meals = get_day_meals(user_id, day_key)
    consumed = totals["total_kcal"]

    lines = []
    lines.append(f"**📋 Daily Summary — {day_key}**\n")

    if target:
        diff = target - consumed
        if diff > 0:
            lines.append(f"🎯 Target: {target} kcal | Consumed: {consumed} kcal")
            lines.append(f"✅ **Deficit: {diff} kcal**")
            fat_g = (diff / 7700) * 1000
            lines.append(f"🔥 You exhaled approximately **{fat_g:.0f}g of body fat** yesterday!")
        elif diff == 0:
            lines.append(f"🎯 Target: {target} kcal | Consumed: {consumed} kcal")
            lines.append(f"✅ **Hit your target exactly!**")
        else:
            lines.append(f"🎯 Target: {target} kcal | Consumed: {consumed} kcal")
            lines.append(f"⚠️ **Surplus: {abs(diff)} kcal**")
            fat_g = (abs(diff) / 7700) * 1000
            lines.append(f"📈 ~{fat_g:.0f}g potential fat storage.")
    else:
        lines.append(f"Total consumed: {consumed} kcal (no target set)")

    lines.append(f"\n📊 **Macros**: {totals['total_protein']:.0f}g protein / {totals['total_carbs']:.0f}g carbs / {totals['total_fat']:.0f}g fat")
    lines.append(f"🍽️ **Meals logged**: {totals['meal_count']}")

    if meals:
        lines.append("\n**Meal breakdown:**")
        for m in meals:
            window = MEAL_WINDOWS[m["window_idx"]]
            ts = datetime.fromisoformat(m["timestamp"]).strftime("%H:%M")
            lines.append(f"  {window[3]} {ts} — {m['kcal']} kcal ({m['protein_g']:.0f}P / {m['carbs_g']:.0f}C / {m['fat_g']:.0f}F)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------------------------------------------------------------------
# Reminder messages
# ---------------------------------------------------------------------------
def build_reminder_embed(label: str, emoji: str) -> discord.Embed:
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    embed = discord.Embed(
        title=f"{emoji}  Time to log your {label}!",
        description=(
            "Snap a photo of your meal and post it here.\n"
            "I'll analyze it for macros & calories automatically."
        ),
        color=discord.Color.green(),
        timestamp=now,
    )
    embed.set_footer(text="Reply with a food photo to get your breakdown")
    return embed


async def send_reminder(label: str, emoji: str):
    """Called by the scheduler at each meal time."""
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        log.warning("Could not find channel %s", DISCORD_CHANNEL_ID)
        return
    embed = build_reminder_embed(label, emoji)
    await channel.send(embed=embed)
    log.info("Sent %s reminder", label)


async def send_daily_summary():
    """Called by the scheduler at 4am to summarize the previous food day."""
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        return

    dt = now_tz()
    # The food day that just ended is yesterday (since it's now 4am)
    prev_day = (dt - timedelta(days=1)).strftime("%Y-%m-%d")

    # Find all users who logged meals that day
    conn = get_db()
    users = conn.execute(
        "SELECT DISTINCT user_id FROM meals WHERE day_key = ?", (prev_day,)
    ).fetchall()
    conn.close()

    if not users:
        log.info("No meals logged for %s, skipping daily summary", prev_day)
        return

    for user_row in users:
        user_id = user_row["user_id"]
        summary = build_daily_summary(user_id, prev_day)
        embed = discord.Embed(
            title="🌅  Daily Summary",
            description=summary,
            color=discord.Color.purple(),
            timestamp=dt,
        )
        await channel.send(embed=embed)
        log.info("Sent daily summary for user %s, day %s", user_id, prev_day)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    init_db()

    # Start the scheduler
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    for hour, label, emoji in REMINDER_HOURS:
        scheduler.add_job(
            send_reminder,
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

    scheduler.start()


@bot.event
async def on_message(message: discord.Message):
    # Ignore own messages
    if message.author == bot.user:
        return

    # Debug logging
    log.info(
        "Message in #%s (id=%s) from %s | attachments=%s | target_channel=%s",
        message.channel.name, message.channel.id, message.author,
        len(message.attachments), DISCORD_CHANNEL_ID,
    )

    # Check if message is in the tracked channel and has image attachments
    if message.channel.id == DISCORD_CHANNEL_ID and message.attachments:
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                log.info("Food photo received from %s: %s", message.author, attachment.filename)

                # Send a "thinking" indicator
                async with message.channel.typing():
                    try:
                        # Download the image
                        image_bytes = await attachment.read()

                        # Determine media type
                        ext = attachment.filename.rsplit(".", 1)[-1].lower()
                        media_map = {
                            "png": "image/png",
                            "jpg": "image/jpeg",
                            "jpeg": "image/jpeg",
                            "webp": "image/webp",
                            "gif": "image/gif",
                        }
                        media_type = media_map.get(ext, "image/jpeg")

                        # Analyze with Claude Vision
                        analysis = await analyze_food_image(image_bytes, media_type)

                        # Parse totals from the analysis
                        parsed = parse_totals(analysis)
                        display_text = strip_totals_line(analysis)

                        # Determine food day and window
                        dt = now_tz()
                        day_key = get_food_day(dt)
                        window_idx = get_current_window_idx(dt)
                        if window_idx < 0:
                            window_idx = 0  # Before first window, assign to first

                        # Store the meal
                        user_id = str(message.author.id)
                        add_meal(
                            user_id, day_key, window_idx,
                            parsed["kcal"], parsed["protein"], parsed["carbs"], parsed["fat"],
                            attachment.filename, analysis,
                        )
                        log.info("Stored meal: %s kcal for user %s on %s (window %d)",
                                 parsed["kcal"], user_id, day_key, window_idx)

                        # Build response embed with analysis
                        embed = discord.Embed(
                            title="📊  Nutrition Breakdown",
                            description=display_text,
                            color=discord.Color.blue(),
                            timestamp=dt,
                        )
                        embed.set_thumbnail(url=attachment.url)
                        embed.set_footer(text=f"Analyzed for {message.author.display_name}")
                        await message.reply(embed=embed)

                        # Build and send budget embed
                        budget_text = build_budget_text(user_id, day_key, dt)
                        budget_embed = discord.Embed(
                            title="🎯  Daily Budget",
                            description=budget_text,
                            color=discord.Color.gold(),
                            timestamp=dt,
                        )
                        await message.channel.send(embed=budget_embed)

                    except Exception as e:
                        log.exception("Error analyzing image")
                        await message.reply(f"⚠️ Sorry, I couldn't analyze that image: {e}")

    # Process commands (e.g., !help)
    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@bot.command(name="target")
async def cmd_target(ctx: commands.Context, kcal: int = None):
    """Set or view your daily calorie target. Usage: !target 2000"""
    user_id = str(ctx.author.id)

    if kcal is None:
        current = get_target_kcal(user_id)
        if current:
            await ctx.reply(f"🎯 Your daily target is **{current} kcal**. Use `!target <number>` to change it.")
        else:
            await ctx.reply("No target set yet. Use `!target <number>` to set your daily calorie goal.\nExample: `!target 2000`")
        return

    if kcal < 500 or kcal > 10000:
        await ctx.reply("Please set a target between 500 and 10,000 kcal.")
        return

    set_target_kcal(user_id, kcal)
    await ctx.reply(f"✅ Daily calorie target set to **{kcal} kcal**. I'll track your remaining budget after each meal.")


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


@bot.command(name="analyze")
async def cmd_analyze(ctx: commands.Context):
    """Reply to a message with a food photo using !analyze to re-analyze it."""
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
    embed = discord.Embed(
        title="🗓️  Meal Reminder Schedule",
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
    lines = [
        "`!target <kcal>` — Set your daily calorie target",
        "`!budget` — View remaining calories for today",
        "`!today` — See all meals logged today",
        "`!analyze` — Reply to a food photo to (re-)analyze it",
        "`!schedule` — View reminder schedule",
        "`!ping` — Health check",
        "`!commands` — This list",
        "",
        "**Or just post a food photo** and I'll analyze it automatically!",
    ]
    embed = discord.Embed(
        title="📖  Available Commands",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )
    await ctx.reply(embed=embed)


# ---------------------------------------------------------------------------
# Dummy HTTP server so Railway sees a listening port and doesn't kill us
# ---------------------------------------------------------------------------
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *args):
        pass  # silence access logs

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
