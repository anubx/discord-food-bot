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

### DM-Based Architecture (Privacy Refactor — March 2026)
- [x] **All tracking via Discord DMs** — meal logging, reports, weight, water, body fat all happen in private DMs between user and bot
- [x] **No server channels needed** — removed private channel creation; admin cannot see user data
- [x] **Auto-registration on first DM** — users are registered automatically when they first message the bot
- [x] **`!join` simplified** — registers user and sends welcome DM, no channel creation
- [x] **Group channel preserved** — leaderboard, daily group summary, join announcements still post to group channel
- [x] **Privacy improvement** — individual meal details no longer posted to group channel, only aggregated leaderboard data
- [x] **All scheduled jobs DM-based** — reminders, summaries, reports, weight prompts all sent via DM

### Multi-User & Social
- [x] Daily leaderboard — ranked by closeness to calorie target
- [x] 4am daily summary (personal DM + group leaderboard)
- [x] 8am morning overview with weight prompt via DM
- [x] Welcome DM on member join

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

### Meal Photo Gallery
- [x] **Photo URLs stored** — all meal photos saved in DB for later retrieval
- [x] **Daily meal GIF** — at 4am, all day's meal photos stitched into an animated GIF (2s per frame, 480px)
- [x] **GIF attached to daily summary** — appears below the personal summary embed
- [x] **`!history`** — view any day's meals + photo GIF (`!history 2026-03-16`)

### Weight Tracking
- [x] **`!weight 82.5`** — log daily weight (kg), one entry per day (updates if re-logged)
- [x] **Weight history** — `!weight` shows last 14 entries with trend arrows
- [x] **Morning weight prompt** — 8am private channel message asks to log weight, shows last entry + delta
- [x] **Weight in reports** — weekly/monthly reports show weight trend (start → end + change)

### Water Tracking
- [x] **AI water estimation** — Gemini estimates water content in food (ml), auto-logged per meal
- [x] **`!water 250`** — manual water logging (ml), shows progress bar
- [x] **Post-meal water prompt** — after each meal, shows food water auto-logged + asks about drinks
- [x] **Daily water target** — 2500ml default, tracked in `!budget` and daily summary
- [x] **Water in reports** — weekly/monthly reports show average daily water intake

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
- [x] **Admin commands** — `!setpremium @user` / `!removepremium @user` / `!migrate` (admin-only)
- [x] **`!pro`** — shows tier status, interaction usage, upgrade info, cancellation instructions
- [x] **`!trial`** — starts 7-day free trial, auto-expires (no cancellation needed)
- [x] **Subscription cancellation** — handled by Discord (Settings → Subscriptions); bot deactivates Pro via `on_entitlement_update` event

### Body Fat Tracking (Opt-in, GDPR-compliant)
- [x] **Navy method calculation** — pure Python, no AI involved (height, waist, neck, hip → BF%)
- [x] **Explicit opt-in consent** — `!bodyfat setup` explains data handling, `!bodyfat confirm` to opt in
- [x] **Data minimization** — only BF% stored, raw measurements discarded immediately after calculation
- [x] **`!bodyfat male 180 85 38`** — calculate and log BF% for male (height waist neck)
- [x] **`!bodyfat female 165 75 34 100`** — calculate and log BF% for female (height waist neck hip)
- [x] **`!bodyfat`** — view BF% history with trends
- [x] **`!bodyfat delete`** — revoke consent and delete all body fat data
- [x] **Integrated in reports** — weekly/monthly reports show BF% trend when user has consented

### GDPR & Privacy Compliance
- [x] **`!deletedata` command** — two-step confirmation, permanently deletes ALL user data (meals, weight, water, body fat, settings)
- [x] **Privacy Policy v2** (`privacy.html`) — comprehensive update covering: DM architecture, body measurements, health data notice (GDPR Art. 9, CCPA, PIPEDA, FADP), data minimization, EU hosting, legal basis, international transfers, right to deletion via bot command
- [x] **Health data classification** — body fat and weight data acknowledged as GDPR special category data with explicit consent
- [x] **EU data residency** — Railway EU region, body fat data never leaves server

### Documentation & Legal
- [x] Developer infographic (`infographic.html`) — full technical workflows + tech stack
- [x] Customer infographic (`infographic-users.html`) — simplified user-facing guide
- [x] Interactive cost simulator (`cost-simulator.html`) — per-user API cost calculator with scaling projections
- [x] **`!info` carousel** — 7-page paginated Discord embed guide with Back/Next buttons
- [x] **Terms of Service** (`terms.html`) — hosted on GitHub Pages
- [x] **Privacy Policy** (`privacy.html`) — hosted on GitHub Pages, covers AI data processing, health data, GDPR/CCPA/PIPEDA/FADP compliance
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
| Channel architecture | **DM-based** + shared group | All tracking via DMs for genuine privacy; group channel for leaderboard only |
| Day boundary | 4am | Late-night snacks count as same day, natural sleep boundary |
| Tier gating | Interaction cap (not modality) | All modalities cost ~same; volume cap converts better than feature-locking |
| Payments | Discord Premium App Subscriptions | Discord handles billing/refunds; 85/15 revenue split; Stripe Connect payouts |
| Legal entity | Rozek Industries Ltd. | Required for Stripe Connect / Discord monetization |
| Macro system | Protein-first, carbs as remainder | Users care most about protein; fat has 30g floor for hormonal health; carbs fill the gap |
| Fat minimum | 30g (warn <50g) | Below 30g impairs hormone production; 50g is optimal threshold flagged in weekly reports |
| Report schedule | Weekly Mon 4:30am, Monthly 1st 5:00am | After daily summary (4am) but before morning overview (8am) |
| Body fat method | US Navy method (local Python) | No AI needed; data minimization — only BF% stored, measurements discarded |
| Body fat consent | Explicit opt-in (GDPR Art. 9) | Health data = special category; requires affirmative action before any processing |
| Data deletion | Self-service `!deletedata` | Instant deletion, no 30-day wait; covers GDPR, CCPA, PIPEDA, FADP right to erasure |
| DM architecture | All tracking in DMs | Admin cannot see health data; genuine privacy vs private channels |

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
| Admin could see user health data | Private channels visible to server admin | Refactored to DM-based architecture — admin physically cannot read DMs |
| Trial cancellation confusion | Users didn't know if they need to cancel trial | Trial auto-expires after 7 days, no action needed. Added info to `!pro` output |
| Subscription cancellation | Users didn't know how to cancel Pro | Discord handles it: Settings → Subscriptions. Added info to `!pro` output |
| Existing user migration | Old users had private channels, new architecture uses DMs | Added `!migrate` admin command — DMs all users explaining the switch |

---

## Privacy & Compliance Strategy

### Health Data Classification

Weight, body fat percentages, calorie tracking, and nutritional data are classified as **health data** — a special category under multiple jurisdictions:

- **GDPR Article 9 (EU/EEA)** — "special category personal data" requiring explicit consent (Art. 9(2)(a))
- **CCPA/CPRA (California)** — "sensitive personal information" with right to limit use, deletion, and opt-in
- **CMIA (California)** — narrower; applies to healthcare providers/insurers, not general apps. CPRA is the relevant law for us
- **PIPEDA (Canada)** — "sensitive personal information" requiring explicit (not implied, not bundled) consent, purpose limitation, named privacy officer (can be the operator), 30-day response to access/correction requests
- **Swiss FADP (revised 2023)** — "sensitive personal data" requiring explicit consent, 72h breach notification to FDPIC, fines on *individuals* up to CHF 250,000 (not just companies)
- **HIPAA (US)** — does **not** apply to us. Only covers "covered entities" (healthcare providers, health plans, clearinghouses) and "business associates." A Discord bot is not a covered entity unless partnering with a provider. Worth designing as-if for future-proofing

### Architecture Decisions for Compliance

| Decision | Implementation | Why |
|----------|---------------|-----|
| DM-based tracking | All health data exchanged in private Discord DMs only | Server admin cannot see user health data — genuine privacy, not policy-based |
| Body fat calculated locally | Navy method formula in pure Python on our server | Body measurements never sent to Gemini or any third party |
| Data minimization | Only BF% stored; height/waist/neck/hip discarded after calculation | Minimize health data retention per GDPR Art. 5(1)(c) |
| Explicit opt-in | `!bodyfat setup` → explanation → `!bodyfat confirm` to consent | GDPR Art. 9(2)(a), CPRA, PIPEDA, FADP all require explicit consent for health data |
| Self-service deletion | `!deletedata` command with two-step confirm | Instant erasure — no 30-day wait. Covers GDPR Art. 17, CCPA, PIPEDA, FADP |
| Selective deletion | `!bodyfat delete` revokes consent + deletes BF data only | Users can delete health subcategory without wiping all data |
| EU data residency | Railway EU region (Amsterdam/Frankfurt) | No cross-border transfer issues for primary data; simplest GDPR compliance |

### Data Processing Agreements (DPAs)

At our current scale (SQLite on Railway, single operator), the DPA landscape is:

| Processor | DPA Status | Action Required |
|-----------|-----------|-----------------|
| **Google (Gemini API)** | Available via Google Cloud Console | ✅ Accept DPA in Cloud Console settings (5 min checkbox) |
| **Railway (hosting)** | Covered under ToS; formal DPA available on request | ⚠️ Email Railway support to request explicit DPA |
| **Discord (message transport)** | Discord Developer DPA for verified apps | ⚠️ Request when app is verified |
| **OpenAI (fallback)** | Available via OpenAI dashboard | Accept if using fallback |
| **Anthropic (fallback)** | Available via Anthropic console | Accept if using fallback |
| **Operator (self)** | N/A — you are both controller and processor | No DPA with yourself |

**Key insight:** Body fat measurements never touch any third party. The Navy method calculation is local Python math on the Railway EU server. DPA obligations only apply to the meal analysis flow (food photos/text → Gemini API).

### Server Location

Railway runs on GCP infrastructure. Deploy to **EU region** (`eu-west`) for simplest compliance:

- GDPR: data stays in EU, no transfer mechanism needed
- Swiss FADP: EU adequacy recognized, no issues
- CCPA/CPRA: no geographic restriction, EU is fine
- PIPEDA: disclose non-Canadian storage location in privacy policy (done)

If Railway is currently on US region → redeploy to EU (config change, no code change). Confirm in Railway project settings.

### Breach Notification Requirements

| Jurisdiction | Timeframe | Notify |
|-------------|-----------|--------|
| GDPR | 72 hours | Supervisory authority (DPA) + affected individuals if high risk |
| Swiss FADP | 72 hours | FDPIC (Swiss DPA) + affected individuals |
| CCPA/CPRA | "Most expedient time possible" | Affected California residents |
| PIPEDA | "As soon as feasible" | Privacy Commissioner of Canada + affected individuals |

### What's Covered vs What's Needed

**Already implemented:**
- [x] Explicit opt-in consent for body fat (special category health data)
- [x] Right to deletion via `!deletedata` (instant, self-service)
- [x] Selective body fat deletion via `!bodyfat delete`
- [x] Data minimization (raw measurements discarded, only BF% stored)
- [x] Local body fat calculation (no third-party processing)
- [x] DM-based architecture (admin cannot access health data)
- [x] Privacy policy v2 covering all jurisdictions
- [x] EU data residency intent (Railway EU region)
- [x] Legal basis documented (consent for Art. 9, legitimate interest for core features)

**Action items (manual, not code):**
- [ ] Accept Google Cloud DPA in console settings
- [ ] Email Railway for formal DPA
- [ ] Confirm Railway service is on EU region — redeploy if on US
- [ ] Request Discord Developer DPA when app is verified
- [ ] Designate privacy officer (can be the operator) for PIPEDA compliance
- [ ] Create breach notification procedure document (who to contact, within what timeframe)

### iOS/Android Native App — Not Recommended

Evaluated wrapping the Discord bot in a native iOS/Android app. **Recommendation: don't.**

Reasons: the bot already works natively in the Discord mobile app (iOS + Android), which handles push notifications, camera, voice, and photo uploads. A native wrapper would require: App Store / Play Store review (health app category triggers extra scrutiny), Apple/Google's 30% commission on subscriptions (vs Discord's 15%), separate payment infrastructure, maintaining two codebases, and health data compliance for mobile app stores (stricter than Discord's platform). The Discord-native approach gives you mobile for free.

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
- **DM-based privacy** — genuine privacy (admin can't see data), unlike channel-based bots
- **Barcode scanning** with quantity modifiers (half, 2 spoons, 50g, etc.)
- **Voice message input** (Whisper transcription)
- **Reply-based natural language corrections** ("the steak is 200g not 300g")
- **Social competition** — DM tracking + group leaderboard + daily rankings
- **Scheduled reminders** at 6 meal windows throughout the day
- **Body fat tracking** — opt-in Navy method with GDPR compliance
- **Water tracking** — AI food water estimation + manual logging
- **Body fat burn calculations** in daily summaries
- **Self-service data deletion** — GDPR/CCPA compliant `!deletedata`

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
- [x] ~~Meal photo gallery~~ — **Done.** `!history` with daily GIF + photo GIF in daily summary
- [x] ~~Weight logging~~ — **Done.** `!weight`, morning prompt, trends in reports
- [x] ~~Water intake tracking~~ — **Done.** AI food water estimation + `!water` + post-meal prompts + daily target
- [x] ~~Body fat estimation~~ — **Done.** Navy method, opt-in consent, data minimization, integrated in reports
- [x] ~~DM-based architecture~~ — **Done.** All tracking via DMs, admin can't see data, auto-registration
- [x] ~~GDPR right to deletion~~ — **Done.** `!deletedata` command, instant self-service deletion
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
