# FoodTracker Dashboard - Complete Index

## Quick Links

- **Getting Started**: See [QUICKSTART.sh](QUICKSTART.sh) or [SETUP.md](SETUP.md)
- **Project Overview**: [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)
- **File List**: [FILE_MANIFEST.txt](FILE_MANIFEST.txt)
- **Main README**: [README.md](README.md)

## Getting Started (5 minutes)

### 1. Install & Setup
```bash
npm install
cp .env.local.example .env.local
# Edit .env.local with Discord & Gemini credentials
```

### 2. Get Discord OAuth Credentials
1. Go to https://discord.com/developers/applications
2. Create New Application
3. OAuth2 > Copy Client ID & Secret
4. Add Redirect URI: `http://localhost:3000/api/auth/callback/discord`

### 3. Get Gemini API Key
1. Go to https://aistudio.google.com/apikey
2. Create new API key
3. Paste into `GEMINI_API_KEY` in .env.local

### 4. Run Dev Server
```bash
npm run dev
# Visit http://localhost:3000
```

## Project Structure at a Glance

```
src/
├── app/                    # Pages & API routes
│   ├── page.tsx           # Dashboard (/)
│   ├── login/page.tsx     # Auth (/login)
│   ├── log/page.tsx       # Meal logging (/log)
│   └── api/               # Backend routes
│       ├── auth/...       # Discord OAuth
│       ├── stats          # Get dashboard data
│       ├── meals          # Save meals
│       └── analyze        # Gemini AI
├── components/            # Reusable UI components
│   ├── Sidebar.tsx
│   ├── StatCard.tsx
│   ├── MealsTable.tsx
│   ├── CalorieChart.tsx
│   ├── MacroRing.tsx
│   ├── WeightCard.tsx
│   ├── WaterCard.tsx
│   └── StreakCard.tsx
└── lib/                   # Utilities
    ├── db.ts             # PostgreSQL helpers
    └── auth.ts           # NextAuth config
```

## Key Features

| Feature | File | Description |
|---------|------|-------------|
| Dashboard | `src/app/page.tsx` | Main nutrition tracking page |
| Meal Logger | `src/app/log/page.tsx` | AI-powered meal input |
| OAuth Login | `src/app/login/page.tsx` | Discord authentication |
| Stats API | `src/app/api/stats/route.ts` | Dashboard data endpoint |
| AI Analysis | `src/app/api/analyze/route.ts` | Gemini meal analysis |
| Meal Save | `src/app/api/meals/route.ts` | Database storage |
| Navigation | `src/components/Sidebar.tsx` | App sidebar |
| Stat Cards | `src/components/StatCard.tsx` | Calorie/macro displays |
| Meals Table | `src/components/MealsTable.tsx` | Today's meals list |
| Weekly Chart | `src/components/CalorieChart.tsx` | 7-day bar chart |
| Macro Ring | `src/components/MacroRing.tsx` | Macro breakdown chart |
| Weight Track | `src/components/WeightCard.tsx` | Weight history |
| Water Track | `src/components/WaterCard.tsx` | Water intake counter |
| Streaks | `src/components/StreakCard.tsx` | Achievement badges |
| Database | `src/lib/db.ts` | PostgreSQL functions |
| Auth Setup | `src/lib/auth.ts` | NextAuth.js config |

## Configuration Files

| File | Purpose |
|------|---------|
| `package.json` | Dependencies & scripts |
| `tsconfig.json` | TypeScript settings |
| `next.config.js` | Next.js configuration |
| `tailwind.config.ts` | Tailwind theme |
| `postcss.config.js` | PostCSS processing |
| `.env.local.example` | Environment template |
| `.gitignore` | Git ignore rules |

## API Endpoints

### GET /api/stats
Returns complete dashboard data:
- User targets (calories, macros, water)
- Today's totals
- Meal list with details
- Weight history
- Water intake
- Streak count
- Weekly chart data

### POST /api/analyze
Analyze food with Gemini:
- **Input**: FormData with `photo` (image) or `text` (description)
- **Output**: AI analysis with macro breakdown

### POST /api/meals
Save meal to database:
- **Input**: Analysis text + optional photo
- **Output**: Saved meal ID + parsed macros

### POST /api/auth/callback/discord
Discord OAuth callback (automatic):
- Handled by NextAuth.js
- Creates session with Discord ID

## Development Commands

```bash
npm run dev       # Start development server (port 3000)
npm run build     # Build for production
npm start         # Run production server
```

## Environment Variables

```
DISCORD_CLIENT_ID=...           # From Discord Developer Portal
DISCORD_CLIENT_SECRET=...       # From Discord Developer Portal
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=...             # Generated 32-char string
DATABASE_URL=postgresql://...   # PostgreSQL connection
GEMINI_API_KEY=...              # From Google AI Studio
```

## Database Requirements

Connected to PostgreSQL with these tables:
- `user_settings` - User targets & preferences
- `meals` - Food log entries
- `weight_log` - Weight history
- `water_log` - Water intake

Discord ID is the primary user identifier.

## Component Deep Dive

### Sidebar.tsx
Navigation sidebar with:
- Logo and app title
- Navigation links (Dashboard, Calendar, Trends, etc)
- Current user info
- Sign out button

### StatCard.tsx
Generic stat display:
- Icon + label
- Current value
- Target value + percent
- Progress bar (colored)

### MealsTable.tsx
Displays meals logged today:
- Meal window emoji
- Time logged
- Food description
- Macros (calories, protein, carbs, fat)
- Water content

### CalorieChart.tsx
7-day calorie bar chart:
- Height = calories
- Green = under target
- Red = over target
- Orange = today
- Target line at top

### MacroRing.tsx
Circular macro breakdown:
- SVG rings for P/C/F
- Protein (red), Carbs (yellow), Fat (blue)
- Center shows total calories
- Percentages below

### WeightCard.tsx
Weight history mini chart:
- 7 vertical bars
- Height shows weight
- Green = latest, purple = older
- Change and trend indicator

### WaterCard.tsx
Water intake tracker:
- 10 glass grid
- Filled glasses = progress
- Breakdown by source (food vs manual)
- Remaining target

### StreakCard.tsx
Achievement tracker:
- Days on target
- Unlocked badges (3d, 7d, 14d, 30d)
- Best streak
- Weekly average

## Data Flow

### Dashboard Load
1. Page loads → `useSession()` checks auth
2. If not authenticated → redirect to `/login`
3. Component mounts → `useEffect` calls `GET /api/stats`
4. API calls database with Discord ID
5. Returns user targets + today's data
6. Components render with real data
7. Auto-refreshes every 30 seconds

### Meal Logging
1. User visits `/log`
2. Uploads photo or types description
3. Click "Analyze Meal" → `POST /api/analyze`
4. Gemini analyzes and returns nutrition
5. User sees parsed macros
6. Click "Log Meal" → `POST /api/meals`
7. API saves to database
8. Redirects back to dashboard (updated)

### Authentication
1. User visits `/` or `/log`
2. Not authenticated → redirect to `/login`
3. Click "Sign in with Discord"
4. Discord OAuth flow
5. Callback to `/api/auth/callback/discord`
6. NextAuth creates JWT with Discord ID
7. User can now access protected pages

## Food Day Logic

- **4 AM Boundary**: Food logged 12:00 AM - 3:59 AM = yesterday
- **Implementation**:
  ```javascript
  const now = new Date();
  const dayKey = now.getHours() < 4
    ? new Date(now.getTime() - 86400000).toISOString().split('T')[0]
    : now.toISOString().split('T')[0];
  ```

## Meal Windows

Food is categorized into 6 windows by logging time:

| Time | Window | Emoji |
|------|--------|-------|
| 7:00-9:59 AM | Breakfast | 🌅 |
| 10:00-12:59 PM | Morning Snack | 🍎 |
| 1:00-3:59 PM | Lunch | 🥗 |
| 4:00-6:59 PM | Afternoon Snack | 🍌 |
| 7:00-9:59 PM | Dinner | 🍽️ |
| 10:00 PM-3:59 AM | Evening Snack | 🌙 |

## Styling

- **Framework**: Tailwind CSS 3.4
- **Theme**: Dark (slate-900/950)
- **Accent**: Green (#22c55e)
- **No external libraries**: Charts use CSS + SVG
- **Responsive**: Mobile-friendly grid layouts

## Deployment

### Vercel (Recommended)
```bash
npm install -g vercel
vercel
# Follow prompts, set environment variables
```

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

### Environment Variables (Production)
Set in hosting platform:
- DISCORD_CLIENT_ID
- DISCORD_CLIENT_SECRET
- NEXTAUTH_URL (your domain)
- NEXTAUTH_SECRET
- DATABASE_URL
- GEMINI_API_KEY

## Testing Checklist

- [ ] npm install works
- [ ] .env.local configured
- [ ] npm run dev starts without errors
- [ ] /login page loads
- [ ] Can sign in with Discord
- [ ] Dashboard shows user data
- [ ] /log page loads
- [ ] Can analyze a meal photo
- [ ] Can analyze text description
- [ ] Meal saves to database
- [ ] Dashboard updates with new meal
- [ ] Sidebar navigation works
- [ ] Sign out button works
- [ ] npm run build succeeds
- [ ] npm start works

## Common Issues

**"User not found"**
- Discord ID not in `user_settings` table
- Run bot `/settings` command first

**AI analysis blank**
- GEMINI_API_KEY invalid
- No internet connection
- Gemini API rate limited

**Database connection error**
- DATABASE_URL format wrong
- Database not accessible
- Firewall blocking connection

**OAuth fails**
- Discord redirect URI doesn't match exactly
- Client ID/Secret wrong
- Not using https:// in production

## File Sizes

| Component | Lines | Purpose |
|-----------|-------|---------|
| page.tsx | 194 | Main dashboard |
| log/page.tsx | 346 | Meal logging |
| db.ts | 117 | Database layer |
| Sidebar | ~60 | Navigation |
| Components | ~50 ea | UI elements |
| API routes | ~80 ea | Backend logic |

**Total**: ~2,000 lines of TypeScript + CSS

## Next Steps After Setup

1. ✅ Install: `npm install`
2. ✅ Configure: Edit `.env.local`
3. ✅ Dev: `npm run dev`
4. ✅ Test: Visit http://localhost:3000
5. ✅ Build: `npm run build`
6. ✅ Deploy: Push to Vercel or Docker

## Support & Docs

- **Next.js**: https://nextjs.org/docs
- **NextAuth.js**: https://next-auth.js.org
- **Tailwind CSS**: https://tailwindcss.com/docs
- **PostgreSQL**: https://www.postgresql.org/docs
- **Gemini API**: https://ai.google.dev/docs
- **Discord OAuth**: https://discord.com/developers/docs/oauth2

---

**Project Status**: ✅ Complete and ready to deploy

Last updated: 2026-03-18
