# FoodTracker Dashboard

A full-featured Next.js web dashboard for the FoodTracker Discord bot. Track nutrition, log meals with AI analysis, and visualize your progress.

## Features

- **Dashboard**: Real-time stats for calories, macros, water, weight, and streaks
- **AI Meal Logging**: Use Gemini to analyze food photos or text descriptions
- **Discord OAuth**: Seamless login with Discord
- **PostgreSQL Integration**: Same database as the Discord bot
- **Responsive Design**: Beautiful dark UI with Tailwind CSS

## Setup

1. **Install dependencies**:
   ```bash
   npm install
   ```

2. **Configure environment**:
   Copy `.env.local.example` to `.env.local` and fill in:
   - Discord OAuth credentials (from Discord Developer Portal)
   - Database URL (same as bot's `DATABASE_URL`)
   - Gemini API key
   - NextAuth secret (generate with: `openssl rand -base64 32`)

3. **Run dev server**:
   ```bash
   npm run dev
   ```
   Open [http://localhost:3000](http://localhost:3000)

4. **Build for production**:
   ```bash
   npm run build
   npm start
   ```

## Project Structure

```
src/
├── app/
│   ├── layout.tsx          # Root layout with SessionProvider
│   ├── page.tsx            # Main dashboard
│   ├── login/page.tsx      # Discord OAuth login
│   ├── log/page.tsx        # Meal logging with AI analysis
│   ├── api/
│   │   ├── auth/[...nextauth]/route.ts
│   │   ├── stats/route.ts  # Dashboard data
│   │   ├── meals/route.ts  # Save meals to DB
│   │   └── analyze/route.ts # Gemini AI analysis
│   └── globals.css
├── components/
│   ├── Sidebar.tsx
│   ├── StatCard.tsx
│   ├── MealsTable.tsx
│   ├── CalorieChart.tsx
│   ├── MacroRing.tsx
│   ├── WeightCard.tsx
│   ├── WaterCard.tsx
│   └── StreakCard.tsx
└── lib/
    ├── db.ts   # PostgreSQL queries
    └── auth.ts # NextAuth config
```

## Database Requirements

The dashboard reads from the same PostgreSQL database as the Discord bot. Required tables:

- `user_settings` - User targets and preferences
- `meals` - Food log entries
- `water_log` - Water intake tracking
- `weight_log` - Weight history

## Authentication

Uses NextAuth.js with Discord OAuth. The Discord user ID is stored in the JWT and used to query the database.

## AI Analysis

Uses Google Gemini 2.5 Flash Lite to analyze food:
- Photo uploads: Analyze what you eat from a photo
- Text descriptions: Describe your meal for macro estimation
- Returns: `$$TOTALS: kcal=X, protein=Y, carbs=Z, fat=W, water=V$$`

## Notes

- SSL disabled for Railway internal connections (DATABASE_URL contains `railway.internal`)
- Food day boundary: 4 AM (matches Discord bot)
- All times in local timezone
- Auto-logs water from food analysis
