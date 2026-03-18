# FoodTracker Dashboard - Setup Guide

## Quick Start

### 1. Install Dependencies
```bash
npm install
```

### 2. Environment Variables
Copy `.env.local.example` to `.env.local` and configure:

```bash
cp .env.local.example .env.local
```

Then edit `.env.local`:

```
# Discord OAuth (from Discord Developer Portal)
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret

# NextAuth configuration
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=generated_secret_here

# PostgreSQL (same as Discord bot)
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Gemini API Key (same as Discord bot)
GEMINI_API_KEY=your_gemini_key
```

### 3. Generate NextAuth Secret
```bash
openssl rand -base64 32
```
Copy the output and paste into `NEXTAUTH_SECRET` in `.env.local`

### 4. Discord OAuth Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a New Application
3. Go to OAuth2 > General
   - Note your **Client ID** and **Client Secret**
4. Add Redirect URL:
   - For local: `http://localhost:3000/api/auth/callback/discord`
   - For production: `https://yourdomain.com/api/auth/callback/discord`

### 5. Run Development Server
```bash
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000)
- First time: Redirects to `/login`
- Click "Sign in with Discord" to authenticate
- Redirects back to dashboard

### 6. Build for Production
```bash
npm run build
npm start
```

## Database Schema

The dashboard connects to the same PostgreSQL database as the Discord bot. It expects these tables:

### `user_settings`
```sql
CREATE TABLE user_settings (
  user_id TEXT PRIMARY KEY,
  display_name TEXT,
  target_kcal INTEGER DEFAULT 2000,
  protein_target INTEGER DEFAULT 150,
  carbs_target INTEGER DEFAULT 250,
  fat_target INTEGER DEFAULT 65,
  water_target INTEGER DEFAULT 2500,
  is_premium BOOLEAN DEFAULT false,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### `meals`
```sql
CREATE TABLE meals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT REFERENCES user_settings(user_id),
  day_key DATE,
  window_idx INTEGER,
  timestamp TIMESTAMP DEFAULT NOW(),
  description TEXT,
  kcal INTEGER,
  protein_g DECIMAL,
  carbs_g DECIMAL,
  fat_g DECIMAL,
  water_ml INTEGER DEFAULT 0,
  photo_url TEXT,
  raw_analysis TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### `weight_log`
```sql
CREATE TABLE weight_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT REFERENCES user_settings(user_id),
  day_key DATE,
  weight_kg DECIMAL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### `water_log`
```sql
CREATE TABLE water_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT REFERENCES user_settings(user_id),
  day_key DATE,
  amount_ml INTEGER,
  source TEXT DEFAULT 'manual',
  timestamp TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW()
);
```

## Food Day Boundary

The dashboard uses a 4 AM boundary (same as the Discord bot):
- Food logged between 12:00 AM - 3:59 AM counts toward the **previous day**
- Food logged between 4:00 AM - 11:59 PM counts toward the **current day**

This logic is implemented in `/api/stats` and `/api/meals` routes.

## Meal Windows

Foods are automatically categorized into 6 meal windows based on the hour they're logged:

1. **🌅 Breakfast** - 7:00 AM - 9:59 AM
2. **🍎 Morning Snack** - 10:00 AM - 12:59 PM
3. **🥗 Lunch** - 1:00 PM - 3:59 PM
4. **🍌 Afternoon Snack** - 4:00 PM - 6:59 PM
5. **🍽️ Dinner** - 7:00 PM - 9:59 PM
6. **🌙 Evening Snack** - 10:00 PM - 3:59 AM

## API Routes

### `GET /api/stats`
Returns dashboard data for authenticated user:
- Today's nutrition totals
- Meal list
- Weight history
- Water intake
- Streak count
- Weekly chart data

### `POST /api/analyze`
Sends food to Gemini for analysis.

**Request**: FormData with either:
- `photo`: Image file
- `text`: Food description string

**Response**:
```json
{
  "analysis": "AI response with $$TOTALS: kcal=X, protein=Y, carbs=Z, fat=W, water=V$$"
}
```

### `POST /api/meals`
Saves analyzed meal to database.

**Request**:
```json
{
  "analysis": "AI analysis text (contains $$TOTALS$$)",
  "description": "What you ate",
  "photoUrl": "base64 or URL"
}
```

**Response**:
```json
{
  "mealId": "uuid",
  "parsed": { "kcal": 500, "protein": 25, ... }
}
```

### `POST /api/auth/callback/discord`
NextAuth Discord OAuth callback (automatic)

## SSL Configuration

- **Railway Internal**: `DATABASE_URL` contains `railway.internal` → SSL disabled
- **External Database**: SSL enabled with `rejectUnauthorized: false`

If you have a proper SSL certificate, modify `src/lib/db.ts`:
```typescript
ssl: { rejectUnauthorized: true }
```

## Troubleshooting

### "User not found" error
- Ensure Discord user ID is in `user_settings` table
- The Discord bot should have created this entry when the user first used `/settings`

### "Could not parse totals" error
- Gemini response didn't include `$$TOTALS: ...$$`
- Check that Gemini API key is valid in `.env.local`
- Test with a simple text description first (easier for AI)

### Database connection error
- Verify `DATABASE_URL` is correct and accessible
- Check firewall/network rules
- Test connection with: `psql $DATABASE_URL`

### OAuth callback not working
- Verify Discord OAuth redirect URI matches exactly (including protocol and path)
- Check that `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` are correct
- Ensure `NEXTAUTH_URL` matches your domain

## Performance Tips

- Dashboard data refreshes every 30 seconds
- Chart only shows last 7 days of data
- Weight history limited to 14 entries
- Use connection pooling (max 5 connections in pool)

## Deployment

### Vercel
```bash
npm install -g vercel
vercel
```
Vercel will automatically detect Next.js and set up environment variables from `.env.local`.

### Docker
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

### Environment Variables for Production
Set in your hosting platform:
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `NEXTAUTH_URL` (your domain)
- `NEXTAUTH_SECRET` (generated 32-char string)
- `DATABASE_URL` (production database)
- `GEMINI_API_KEY`

## Key Files

| File | Purpose |
|------|---------|
| `src/app/page.tsx` | Main dashboard with stats |
| `src/app/log/page.tsx` | AI-powered meal logging |
| `src/app/login/page.tsx` | Discord OAuth login |
| `src/lib/db.ts` | PostgreSQL query helpers |
| `src/lib/auth.ts` | NextAuth configuration |
| `src/components/*.tsx` | Reusable UI components |
| `src/app/api/*.ts` | Backend API routes |
