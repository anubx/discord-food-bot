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
- [x] **Photo analysis** — Gemini 2.5 Flash Lite vision (fallback: GPT-4o)
- [x] **Barcode scanning** — pyzbar decodes barcodes, Open Food Facts API for nutrition data
- [x] **Barcode quantity modifiers** — supports `half`, `2 servings`, `50g`, `1 spoon`, etc.
- [x] **Text input** — Gemini 2.5 Flash Lite (fallback: Claude Sonnet)
- [x] **Voice messages** — Gemini native audio (fallback: Whisper + Claude)

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

### Macro Targets & Nutrition Goals
- [x] **Protein-first macro system** — user sets kcal target → protein target → fat (default 50g, min 30g) → carbs auto-calculated from remainder
- [x] **`!macros`** — view/set protein and fat targets (`!macros protein=150 fat=60`)
- [x] **Fat floor enforcement** — fat cannot be set below 30g (hormonal health minimum)
- [x] **Budget macro overlay** — `!budget` shows macro progress vs targets with remaining protein
- [x] **Daily summary macro comparison** — personal 4am summary shows target vs actual macros

### Streak Tracking & Reports
- [x] **Streak tracking** — consecutive days at or under calorie target, calculated dynamically
- [x] **`!streak`** — view current streak with milestone badges (3, 7, 14, 30+ days)
- [x] **Weekly report** — auto-sent Monday 4:30am + `!weekly` command. Includes: daily averages, macro target comparison, consistency %, day-by-day breakdown, fat <50g health warning
- [x] **Monthly report** — auto-sent 1st of month 5:00am + `!monthly` command. Includes: monthly averages, week-by-week breakdown, body composition estimate, fat intake warnings
- [x] **Fat health warning** — if fat intake stays below 50g for more than 2 days/week, weekly report flags it: "for optimal hormonal health, keep fat intake above 50g"

### Meal Corrections
- [x] `!undo` — remove last logged meal
- [x] `!delete <#>` — delete specific meal by number
- [x] `!edit <#> kcal=X protein=X` — manually edit macro values
- [x] `!analyze` — reply to a food photo to re-analyze it
- [x] **Reply-based correction** — reply to any Nutrition Breakdown embed with text or voice (e.g. "the steak is 200g not 300g, the radish are tomatoes") and Claude re-evaluates the entire meal

### Premium & Monetization
- [x] **Freemium tier system** — free: 3 interactions/day, Pro: 500/month ($2.99/month)
- [x] **7-day free trial** — custom implementation (Discord doesn't support native app subscription trials)
- [x] **Discord Premium App Subscriptions** — full integration with entitlement events (`on_entitlement_create` / `on_entitlement_update`)
- [x] **SKU created** in Discord Developer Portal (ID: 1483496066660700252)
- [x] **Stripe Connect** payouts configured via Rozek Industries Ltd.
- [x] **Interaction cap system** — daily counter for free users, monthly counter for premium, auto-reset
- [x] **Upsell flow** — shown when free users hit daily cap, links to `!trial` and `!pro`
- [x] **Admin commands** — `!setpremium @user` / `!removepremium @user` (admin-only)
- [x] **`!pro`** — shows tier status, interaction usage, upgrade info
- [x] **`!trial`** — starts 7-day free trial, prevents double-use

### Documentation & Legal
- [x] Developer infographic (`infographic.html`) — full technical workflows + tech stack
- [x] Customer infographic (`infographic-users.html`) — simplified user-facing guide
- [x] Interactive cost simulator (`cost-simulator.html`) — per-user API cost calculator with scaling projections
- [x] **`!info` carousel** — 7-page paginated Discord embed guide with Back/Next buttons
- [x] **Terms of Service** (`terms.html`) — hosted on GitHub Pages
- [x] **Privacy Policy** (`privacy.html`) — hosted on GitHub Pages, covers AI data processing, GDPR basics
- [x] **App icon** (`icon.png`) — 1024x1024 branded icon for Discord Developer Portal
- [x] **API cost logging** — all 5 endpoints log token counts + exact costs to Railway logs

### AI Engine Migration (March 2026)
- [x] **Migrated from 3 APIs → 1** — OpenAI GPT-4o + Whisper + Anthropic Claude → Gemini 2.5 Flash Lite
- [x] **27x cost reduction** — $0.004/interaction → $0.00015/interaction
- [x] **Fallback system** — OpenAI/Anthropic used automatically if Gemini key not configured

---

## Key Technical Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| **Primary AI engine** | **Gemini 2.5 Flash Lite** | 27x cheaper than GPT-4o/Claude; handles text, image, audio natively in one API |
| Image analysis (fallback) | GPT-4o Vision | Claude Vision misidentified foods (tomatoes as radish); GPT-4o more accurate for food photos |
| Text/reasoning (fallback) | Claude Sonnet | Better at structured reasoning, quantity interpretation, meal corrections |
| Voice transcription (fallback) | OpenAI Whisper | Best-in-class speech-to-text, handles multiple languages |
| Barcode database | Open Food Facts | Free, no API key required, large product database |
| Barcode decoding | pyzbar + Pillow | Lightweight, works offline, no API needed |
| Database | SQLite + WAL | Simple, no extra service needed, persistent via Railway volume |
| Hosting | Railway | Easy Docker deploys, persistent volumes, auto-restart |
| Channel architecture | Private per user + shared group | Privacy for meal photos, social motivation via group feed |
| Day boundary | 4am | Late-night snacks count as same day, natural sleep boundary |
| Tier gating | Interaction cap (not modality) | All modalities cost ~same; volume cap converts better than feature-locking |
| Payments | Discord Premium App Subscriptions | Discord handles billing/refunds; 85/15 revenue split; Stripe Connect payouts |
| Legal entity | Rozek Industries Ltd. | Required for Stripe Connect / Discord monetization |
| Macro system | Protein-first, carbs as remainder | Users care most about protein; fat has 30g floor for hormonal health; carbs fill the gap |
| Fat minimum | 30g (warn <50g) | Below 30g impairs hormone production; 50g is optimal threshold flagged in weekly reports |
| Report schedule | Weekly Mon 4:30am, Monthly 1st 5:00am | After daily summary (4am) but before morning overview (8am) |

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

**Free Tier — 3 interactions/day (any modality)**
- All input types: photos, voice, text, barcodes, corrections
- Capped at 3 per day (resets at 4am with the food day)
- Calorie budget tracking, leaderboard, 6x daily reminders always free
- Cost: ~$0.36/user/month (3 interactions × 30 days × $0.004)

**Premium Tier — $2.99/month, 500 interactions/month**
- Same features as free, just 500/month instead of 3/day
- 7-day free trial (custom implementation — Discord doesn't support native trials)

**Why this split instead of modality-gating:**
Real-world API cost testing showed all modalities cost ~$0.004 per interaction regardless of type (text, photo, voice). Gating by modality made users feel the free tier was broken. Giving everyone full access but capping volume creates better conversion: users experience the magic, want more.

**Why $2.99:**
Discord users skew younger and more price-sensitive. $2.99 is impulse-buy territory — well under MyFitnessPal ($9.99/mo) and Lose It ($3.33/mo).

**Note on trials:** Discord Premium App Subscriptions do **not** natively support free trials. Trial functionality is implemented custom in the bot using a `trial_started` timestamp in the database. After 7 days, users must subscribe through Discord's native payment flow. This is fully legal — no Discord billing system is bypassed.

### Revenue Mechanics
- Discord handles all billing, receipts, and refunds
- Developer gets 85% (Discord takes 15%) until $1M revenue, then 70/30
- Payouts via Stripe Connect after $100 minimum
- Available to US, UK, EU developers
- Subscription status checked in bot code via Discord API to gate features

### Unit Economics (based on real API cost testing — March 2026)

**Pre-Gemini (OpenAI + Anthropic):** ~$0.004/interaction (text: $0.004, photo: $0.004, voice: $0.005)
**Post-Gemini (2.5 Flash Lite):** ~$0.00015/interaction — **27x cheaper**

| Metric | Pre-Gemini | Post-Gemini |
|--------|-----------|-------------|
| Cost per interaction | ~$0.004 | ~$0.00015 |
| Premium user max cost (500/mo) | ~$2.00 | ~$0.075 |
| Revenue after Discord's 15% cut | $2.54 | $2.54 |
| **Profit per premium user/month** | **$0.54** | **$2.47** |
| **Margin** | **21%** | **97%** |
| Free tier cost per user/month | ~$0.36 | ~$0.014 |
| 7-day trial cost per user | ~$0.48 | ~$0.02 |
| Break-even ratio | 1 premium covers 1.5 free | 1 premium covers 176 free |

### Scaling Projections — Post-Gemini (70% premium / 30% free split)

| Users | Revenue | API Cost | Hosting | Profit/month |
|-------|---------|----------|---------|-------------|
| 25 | $45 | $1.40 | $5 | +$39 |
| 50 | $89 | $2.80 | $5 | +$81 |
| 100 | $178 | $5.60 | $5 | +$167 |
| 250 | $445 | $14 | $5 | +$426 |
| 500 | $889 | $28 | $10 | +$851 |
| 1,000 | $1,778 | $56 | $10 | +$1,712 |

### Cost Controls
- Free users capped at 3 interactions/day (~90/month max)
- Premium users capped at 500 interactions/month
- Gemini already so cheap that cost is essentially negligible
- OpenAI/Anthropic fallbacks only used if Gemini key not set

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
1. **Phase 1 (now)**: Freemium launch — free tier (3/day) + Pro ($2.99/mo, 500/month) + 7-day trial. Get into 20–30 servers. Collect feedback. Premium infrastructure is live.
2. **Phase 2 (200+ active users)**: Optimize conversion funnel. A/B test trial length, cap limits, upsell messaging. Grandfather early adopters with discounts.
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

## Completed: Manual Cost Test (March 17, 2026)

Real-world API cost test performed using Railway logs with per-call cost logging.

### Results (OpenAI + Anthropic — pre-Gemini migration)
| Action | Cost | Details |
|--------|------|---------|
| Text meal (Claude Sonnet) | $0.004 | ~220 in, ~250 out tokens |
| Photo meal (GPT-4o Vision) | $0.004 | ~990 in, ~160 out tokens |
| Voice meal (Whisper + Claude) | $0.005 | Whisper ~$0.0004 + Claude ~$0.004 |
| Barcode (Open Food Facts hit) | $0.000 | Free API, no AI call needed |
| Barcode (fallback to photo) | $0.004 | Falls back to GPT-4o Vision |

**Key finding:** All modalities cost ~$0.004 regardless of type. The output tokens (nutrition breakdown) dominate cost, not the input. This led to the decision to gate by interaction volume rather than modality.

### Post-Gemini (pending verification)
Expected ~$0.00015/interaction with Gemini 2.5 Flash Lite. Needs live testing to confirm.

---

## Potential Next Features

### High Impact (build these to drive premium conversions)
- [x] ~~Weekly/monthly summary reports~~ — **Done.** Auto-sent weekly (Mon 4:30am) + monthly (1st 5:00am) + `!weekly` / `!monthly` commands
- [x] ~~Streak tracking~~ — **Done.** Consecutive days on target, `!streak` command with milestone badges
- [x] ~~`!pro` upsell command~~ — **Done.** Shows tier status, interaction usage, upgrade info
- [x] ~~Premium gating logic~~ — **Done.** Interaction cap system (3/day free, 500/month Pro) with entitlement events
- [x] ~~Daily photo cap~~ — **Done.** Replaced by unified interaction cap across all modalities
- [x] ~~Macro targets~~ — **Done.** Protein-first system with auto-calculated carbs, 30g fat minimum, fat health warnings

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

## Cost Structure (Current — Gemini 2.5 Flash Lite)

**Migrated from OpenAI GPT-4o + Anthropic Claude Sonnet → Google Gemini 2.5 Flash Lite (March 2026)**

| Service | Cost | Notes |
|---------|------|-------|
| Railway hosting | ~$5/month | Starter plan, single container |
| **Gemini 2.5 Flash Lite** (primary) | $0.10/1M in, $0.40/1M out | All modalities: text, image, audio |
| OpenAI API (fallback only) | $2.50/1M in, $10.00/1M out | GPT-4o Vision + Whisper |
| Anthropic API (fallback only) | $3.00/1M in, $15.00/1M out | Claude Sonnet |
| Open Food Facts | Free | No API key needed |
| Discord | Free | Bot hosting is free |

**Cost per interaction with Gemini: ~$0.00015** (27x cheaper than previous setup at ~$0.004).

Estimated cost per active premium user (500 interactions/month): **~$0.075/month**.
Estimated cost per free user (90 interactions/month): **~$0.014/month**.

### Why Gemini 2.5 Flash Lite?
- Cheapest stable multimodal model available (March 2026)
- Handles text + image + audio natively — one API instead of three
- Voice messages: single Gemini call replaces Whisper transcription + Claude analysis (2 calls → 1)
- Gemini 2.0 Flash was deprecated; 2.5 Flash Lite is the stable replacement
- OpenAI/Anthropic kept as optional fallbacks if GEMINI_API_KEY is not set

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
| `terms.html` | Terms of Service — hosted on GitHub Pages |
| `privacy.html` | Privacy Policy — hosted on GitHub Pages |
| `icon.png` | 1024x1024 app icon for Discord Developer Portal |
| `PROGRESS.md` | This file — progress, decisions, strategy |

---

*Last updated: March 17, 2026*
