"""
Discord Food Tracker Bot
- Sends meal photo reminders at scheduled times
- Analyzes food photos using Claude Vision for macros & kcal
"""

import os
import io
import base64
import logging
from datetime import datetime
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
TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("foodbot")

# ---------------------------------------------------------------------------
# Meal schedule — (hour, label, emoji)
# ---------------------------------------------------------------------------
MEAL_SCHEDULE = [
    (8,  "Breakfast",       "🌅"),
    (11, "Morning Snack",   "🍎"),
    (14, "Lunch",           "🥗"),
    (17, "Afternoon Snack", "🍌"),
    (20, "Dinner",          "🍽️"),
    (23, "Evening Snack",   "🌙"),
]

# ---------------------------------------------------------------------------
# Claude Vision client
# ---------------------------------------------------------------------------
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ANALYSIS_SYSTEM_PROMPT = """You are a nutrition analysis assistant. When given a photo of food, provide:

1. **Identified foods** — list every item you can see
2. **Estimated macros per item** (protein, carbs, fat in grams)
3. **Estimated calories per item**
4. **Meal totals** — sum of protein, carbs, fat, and total kcal

Be concise. Use a clean table format. If you're uncertain about portion sizes, state your assumptions (e.g., "assuming ~200g chicken breast"). Always give your best estimate rather than refusing."""


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


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)

    # Start the scheduler
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    for hour, label, emoji in MEAL_SCHEDULE:
        scheduler.add_job(
            send_reminder,
            CronTrigger(hour=hour, minute=0, timezone=TIMEZONE),
            args=[label, emoji],
            id=f"reminder_{hour}",
            replace_existing=True,
        )
        log.info("Scheduled %s reminder at %02d:00 %s", label, hour, TIMEZONE)

    scheduler.start()


@bot.event
async def on_message(message: discord.Message):
    # Ignore own messages
    if message.author == bot.user:
        return

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

                        # Build response embed
                        embed = discord.Embed(
                            title="📊  Nutrition Breakdown",
                            description=analysis,
                            color=discord.Color.blue(),
                            timestamp=datetime.now(ZoneInfo(TIMEZONE)),
                        )
                        embed.set_thumbnail(url=attachment.url)
                        embed.set_footer(text=f"Analyzed for {message.author.display_name}")

                        await message.reply(embed=embed)

                    except Exception as e:
                        log.exception("Error analyzing image")
                        await message.reply(f"⚠️ Sorry, I couldn't analyze that image: {e}")

    # Process commands (e.g., !help)
    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# Slash / prefix commands
# ---------------------------------------------------------------------------
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
            embed = discord.Embed(
                title="📊  Nutrition Breakdown",
                description=analysis,
                color=discord.Color.blue(),
                timestamp=datetime.now(ZoneInfo(TIMEZONE)),
            )
            embed.set_thumbnail(url=attachment.url)
            await ctx.reply(embed=embed)


@bot.command(name="schedule")
async def cmd_schedule(ctx: commands.Context):
    """Show the current reminder schedule."""
    tz = ZoneInfo(TIMEZONE)
    lines = [f"{emoji} **{label}** — {hour:02d}:00 {TIMEZONE}" for hour, label, emoji in MEAL_SCHEDULE]
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
