# FoodTracker Bot — Progress & Decision Log

## Project Overview
AI-powered Discord bot for meal tracking with photo analysis, barcode scanning, voice input, calorie budgeting, and social competition features. Deployed on Railway.

---

## Completed Features

### Core Infrastructure
- [x] Discord.py bot with privileged intents (Message Content, Server Members)
- [x] SQLite database with WAL mode for meal + user data
- [x] Railway deployment with Dockerfile, persistent volume, health server on port 8080
- [x] APScheduler for cron-based reminders (Berlin timezone)
- [x] GitHub repo: `anubx/discord-food-bot`

### Meal Input Methods
- [x] **Photo analysis** — GPT-4o Vision identifies foods, estimates portions + macros
- [x] **Barcode scanning** — pyzbar decodes barcodes, Open Food Facts API for nutrition data
- [x] **Barcode quantity modifiers** — supports `half`, `2 servings`, `50g`, `1 spoon`, etc.
- [x] **Text input** — Claude AI analyzes typed food descriptions
- [x] **Voice messages** — OpenAI Whisper transcription → Claude text analysis

### Calorie Budget System
- [x] Per-user daily calorie target (`!target`)
- [x] 6 meal windows: Breakfast (8–11), Morning Snack (11–14), Lunch (14–17), Afternoon Snack (17–20), Dinner (20–23), Evening Snack (23–4)
- [x] 4am day boundary (meals before 4am count as previous day)
- [x] Auto budget update after each meal — remaining kcal split across future windows
- [x] Body fat burn/gain estimate (7,700 kcal = 1kg fat)

### Multi-User & Social
- [x] `!join` auto-provisions a private channel per user
- [x] Private channels with permission overwrites (only user + bot can see)
- [x] Group channel feed — meal summaries posted for all to see
- [x] Daily leaderboard — ranked by closeness to calorie target
- [x] 4am daily summary (personal + group) with fat burn estimates
- [x] 8am morning overview in group channel
- [x] Welcome message on member join

### Meal Corrections
- [x] `!undo` — remove last logged meal
- [x] `!delete <#>` — delete specific meal by number
- [x] `!edit <#> kcal=X protein=X` — manually edit macro values
- [x] `!analyze` — reply to a food photo to re-analyze it
- [x] **Reply-based correction** — reply to any Nutrition Breakdown embed with text or voice (e.g. "the steak is 200g not 300g, the radish are tomatoes") and Claude re-evaluates the entire meal

### Documentation & Tools
- [x] Developer infographic (`infographic.html`) — full technical workflows + tech stack
- [x] Customer infographic (`infographic-users.html`) — simplified user-facing guide
- [x] Interactive cost simulator (`cost-simulator.html`) — per-user API cost calculator with scaling projections

---

## Key Technical Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Image analysis | GPT-4o Vision | Claude Vision misidentified foods (tomatoes as radish); GPT-4o more accurate for food photos |
| Text/reasoning | Claude Sonnet | Better at structured reasoning, quantity interpretation, meal corrections |
| Voice transcription | OpenAI Whisper | Best-in-class speech-to-text, handles multiple languages |
| Barcode database | Open Food Facts | Free, no API key required, large product database |
| Barcode decoding | pyzbar + Pillow | Lightweight, works offline, no API needed |
| Database | SQLite + WAL | Simple, no extra service needed, persistent via Railway volume |
| Hosting | Railway | Easy Docker deploys, persistent volumes, auto-restart |
| Channel architecture | Private per user + shared group | Privacy for meal photos, social motivation via group feed |
| Day boundary | 4am | Late-night snacks count as same day, natural sleep boundary |

---

## Issues Resolved

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| 401 Unauthorized | Used webhook URL as bot token | Got actual bot token from Developer Portal |
| "Integration requires code grant" | OAuth2 URL misconfigured | Manual invite URL with correct permissions integer |
| Railway "Stopping Container" | Old deployments being replaced | Was actually working; added health server as safety net |
| Bot not responding to photos | FoodTracker role missing from channel | Added bot with View/Send/Read/Embed permissions |
| PrivilegedIntentsRequired crash | Server Members Intent not enabled | Toggled on in Developer Portal |
| Bash `!` in double quotes | History expansion in commit messages | Used single quotes for git commit |

---

## Competitive Landscape

### Main Competitor: CalorieBot (caloriebot.ai)
The dominant Discord food tracking bot. Features AI photo analysis, natural language logging, progress dashboards, and wearable sync. Listed on Top.gg.

### Other Players
- **NutriScan** — open source, GPT-4 Vision, basic calorie/macro output
- **Nutri Bot** — text-only, simple nutritional data lookup
- **Healthy Pal** — broader scope (sleep, exercise, diet), less food-focused
- **MealScout** — photo or text logging, no barcode scanning

### Our Differentiators vs CalorieBot
- **Barcode scanning** with quantity modifiers (half, 2 spoons, 50g, etc.)
- **Voice message input** (Whisper transcription)
- **Reply-based natural language corrections** ("the steak is 200g not 300g")
- **Social competition** — private channels + group leaderboard + daily rankings
- **Scheduled reminders** at 6 meal windows throughout the day
- **Body fat burn calculations** in daily summaries

### Strategic Positioning
CalorieBot is solo-focused. Our angle is **social/group accountability**: "Track together, compete together." This targets friend groups, gym buddy groups, fitness challenges, and weight loss accountability communities — a niche CalorieBot doesn't emphasize.

---

## Monetization Strategy

### Pricing Model: Freemium via Discord Premium App Subscriptions

**Free Tier (acquisition — costs ~$0.50–0.72/user/month in API fees)**
- Unlimited text-based meal logging (Claude — cheap)
- Daily calorie budget tracking
- Leaderboard access
- 6x daily reminders

**Premium Tier — $2.99/month per user (7-day free trial)**
- Photo analysis (GPT-4o Vision)
- Voice message logging (Whisper + Claude)
- Barcode scanning with quantity modifiers
- Reply-based meal corrections
- `!analyze` photo reanalysis

**Why $2.99:**
Discord users skew younger and more price-sensitive. $2.99 is impulse-buy territory — well under MyFitnessPal ($9.99/mo) and Lose It ($3.33/mo). Margins are thin (~18%) but volume-dependent; the daily photo cap (8/day) prevents heavy users from blowing past breakeven.

**Note on trials:** Discord Premium App Subscriptions do **not** natively support free trials. Trial functionality is implemented custom in the bot using a `trial_started` timestamp in the database. After 7 days, users must subscribe through Discord's native payment flow.

### Revenue Mechanics
- Discord handles all billing, receipts, and refunds
- Developer gets 85% (Discord takes 15%) until $1M revenue, then 70/30
- Payouts via Stripe Connect after $100 minimum
- Available to US, UK, EU developers
- Subscription status checked in bot code via Discord API to gate features

### Unit Economics (per the cost simulator)

| Metric | Value |
|--------|-------|
| Average API cost per premium user/month | ~$2.07 |
| Revenue after Discord's 15% cut | ~$2.54 |
| Profit per premium user/month | ~$0.47 |
| Margin | ~18% |
| Free tier cost per user/month | ~$0.72 |
| 7-day trial cost per user | ~$0.48 |
| Acquisition cost (at 30% trial→paid conversion) | ~$1.61 |

### Scaling Projections (70% premium / 30% free split)

| Users | Revenue | API Cost | Profit/month |
|-------|---------|----------|-------------|
| 25 | $45 | $41 | +$4 |
| 50 | $89 | $82 | +$7 |
| 100 | $178 | $165 | +$13 |
| 250 | $445 | $412 | +$33 |
| 500 | $889 | $823 | +$66 |
| 1,000 | $1,778 | $1,647 | +$131 |

### Cost Controls
- Cap photo analyses at 8/day per user (plenty for real use, prevents abuse)
- Consider GPT-4o-mini for photos if margins tighten (~1/10th cost, slightly lower quality)
- Free tier text-only keeps acquisition cost under $1/user/month

---

## Marketing & Distribution Strategy

### Where to Advertise (in order of likely ROI)

**1. Discord Bot Directories (Free, organic)**
- Top.gg, Discord.me, Disboard
- List with compelling screenshots and description
- Target tags: fitness, health, nutrition, weight-loss, diet

**2. Reddit (Free, high-intent)**
- r/Discord, r/discordapp — "I built this" posts
- r/fitness, r/loseit, r/CICO, r/caloriecount, r/mealprep — fitness audiences
- Share as a project showcase, not an ad — Reddit rewards authenticity

**3. Existing Fitness Discord Servers**
- Diet & Nutrition (~7,500 members) — discord.com/invite/diet
- Eating Well — weight loss + recipe community
- Gaintrust — fitness server already using custom macro tracking
- Various CICO / weight loss communities
- Strategy: join as a member, introduce bot naturally, offer partnerships

**4. Short-form Video (TikTok / YouTube Shorts / Instagram Reels)**
- Screen-record the flow: snap photo → AI breakdown → budget update → leaderboard
- Fitness content performs well on short-form; no need to be an influencer
- "I built an AI that tracks my calories in Discord" is a compelling hook

**5. Product Hunt**
- Launch as a fun side project
- Discord bots get attention for novelty factor
- Provides one-day traffic spike + long-tail SEO

**6. Micro-influencer Outreach**
- Small fitness YouTubers/TikTokers (10K–50K followers)
- Many will promote for free or $50–100 if they think it's cool
- Approach: "built this for my friend group, thought you might like it"

### Go-to-Market Approach
1. **Phase 1 (now)**: Launch completely free, no paywall. Get into 20–30 servers. Collect feedback.
2. **Phase 2 (200+ active users)**: Introduce premium tier with generous grandfather deal for existing users.
3. **Phase 3 (post-traction)**: Invest in content marketing and influencer outreach with real user testimonials and leaderboard screenshots.

### Key Insight
Don't search Disboard for "food tracking" — those servers don't exist as a category. Instead search for **fitness**, **weight-loss**, **health**, **nutrition**, **diet**, **CICO** tags. The audience is there, just labeled differently.

### Trial & Legal Notes
- Discord Premium App Subscriptions do **not** natively support free trials (trials only exist for Premium Memberships, a separate feature for server subscriptions)
- Our 7-day trial is custom-built: `trial_started` timestamp in SQLite, checked on each premium feature use
- This is fully legal — we're simply giving away our own product for free temporarily; no Discord billing/entitlement system is bypassed
- After trial expiry, payment goes through Discord's official subscription flow
- Trial communication must be transparent: clearly state the 7-day window and what happens after

---

## Pending: Manual Cost Test Plan

Before finalizing pricing, run a real-world test to get exact API costs (not estimates):

### Setup
1. Note current spend on OpenAI dashboard (platform.openai.com/usage) and Anthropic dashboard (console.anthropic.com)
2. Create a second Discord account, `!join` from group channel

### Test Actions (60 total)
- [ ] 10 food photos (varied complexity — simple apple to full dinner plate)
- [ ] 10 voice messages describing meals
- [ ] 10 text messages describing meals
- [ ] 10 `!analyze` replies to re-analyze food photos
- [ ] 10 voice correction replies to Nutrition Breakdown embeds
- [ ] 10 text correction replies to Nutrition Breakdown embeds

### After Test
- Check both API dashboards for actual spend delta
- Divide by action type to get real cost-per-call
- Plug into cost simulator to validate pricing model
- Adjust $2.99 price point if needed

---

## Potential Next Features

### High Impact (build these to drive premium conversions)
- [ ] Weekly/monthly summary reports with trends and charts
- [ ] Streak tracking — consecutive days hitting calorie target (drives retention + premium stickiness)
- [ ] `!pro` upsell command — shows premium features + upgrade button
- [ ] Premium gating logic — check Discord subscription status, gate photo/voice/barcode behind paywall
- [ ] Daily photo cap (8/day) to control costs
- [ ] Macro targets (not just kcal) — protein/carbs/fat goals

### Medium Impact
- [ ] Meal photo gallery — `!history` to browse past meals with thumbnails
- [ ] Weight logging + progress chart (`!weight 82.5`)
- [ ] Water intake tracking
- [ ] Meal templates / favorites — save and reuse frequent meals (`!save breakfast1`, `!log breakfast1`)
- [ ] Recipe analysis — paste a recipe URL and get per-serving macros
- [ ] Restaurant menu lookup — "I'm eating at McDonald's, Big Mac combo"
- [ ] Export data to CSV/PDF (`!export week`)
- [ ] Multi-language support (German prompts since Berlin timezone)
- [ ] Timezone per user (currently server-wide Berlin)

### Social & Gamification (build these for the "compete together" angle)
- [ ] Weekly challenges ("Protein Week: hit 150g protein daily")
- [ ] Achievement badges (first meal logged, 7-day streak, 30-day streak, etc.)
- [ ] Betting/accountability — pledge to hit target or pay penalty
- [ ] Meal reactions — friends can react to meal photos
- [ ] "Cheat day" mode — relaxed target with no penalty

### Technical Improvements
- [ ] PostgreSQL migration for better concurrency at scale
- [ ] Redis caching for frequent DB queries
- [ ] Rate limiting per user to prevent API cost spikes
- [ ] Slash commands (Discord interactions) alongside `!` prefix commands
- [ ] Dashboard web UI for viewing history/charts outside Discord
- [ ] Webhook integration for MyFitnessPal / Apple Health / Google Fit

---

## Cost Structure (Current)

| Service | Cost | Notes |
|---------|------|-------|
| Railway hosting | ~$5/month | Starter plan, single container |
| OpenAI API (GPT-4o Vision + Whisper) | Variable | ~$0.01 per image, ~$0.0015 per 15s audio |
| Anthropic API (Claude Sonnet) | Variable | ~$0.008 per text analysis, ~$0.01 per correction |
| Open Food Facts | Free | No API key needed |
| Discord | Free | Bot hosting is free |

Estimated cost per active premium user: **~$2.07/month** (3 photos, 1 voice, 2 texts, 2 corrections per day).
Estimated cost per free user: **~$0.72/month** (3 text logs per day).

---

## Files in This Repo

| File | Purpose |
|------|---------|
| `bot.py` | Main bot — all features, commands, AI integrations, scheduling |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container build with libzbar for barcode scanning |
| `railway.toml` | Railway deployment config |
| `.env.example` | Required environment variables template |
| `infographic.html` | Developer infographic — full technical workflows |
| `infographic-users.html` | Customer infographic — simplified user guide |
| `cost-simulator.html` | Interactive cost/pricing calculator |
| `PROGRESS.md` | This file — progress, decisions, strategy |

---

*Last updated: March 17, 2026*
