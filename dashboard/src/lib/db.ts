import { Pool, QueryResult } from 'pg';

// Lazy pool — only created on first query (not at import/build time)
let _pool: Pool | null = null;

function getPool(): Pool {
  if (!_pool) {
    _pool = new Pool({
      connectionString: process.env.DATABASE_URL,
      ssl: process.env.DATABASE_URL?.includes('railway.internal') ? false : { rejectUnauthorized: false },
      max: 5,
    });
  }
  return _pool;
}

export async function query(text: string, params?: any[]): Promise<QueryResult> {
  const client = await getPool().connect();
  try {
    const result = await client.query(text, params);
    return result;
  } finally {
    client.release();
  }
}

// Helper to get user by Discord ID
export async function getUserByDiscordId(discordId: string) {
  const result = await query('SELECT * FROM user_settings WHERE user_id = $1', [discordId]);
  return result.rows[0] || null;
}

// Get day meals
export async function getDayMeals(userId: string, dayKey: string) {
  const result = await query(
    'SELECT * FROM meals WHERE user_id = $1 AND day_key = $2 ORDER BY timestamp',
    [userId, dayKey]
  );
  return result.rows;
}

// Get day totals
export async function getDayTotals(userId: string, dayKey: string) {
  const result = await query(
    `SELECT COALESCE(SUM(kcal),0) as total_kcal,
            COALESCE(SUM(protein_g),0) as total_protein,
            COALESCE(SUM(carbs_g),0) as total_carbs,
            COALESCE(SUM(fat_g),0) as total_fat,
            COUNT(*) as meal_count
     FROM meals WHERE user_id = $1 AND day_key = $2`,
    [userId, dayKey]
  );
  return result.rows[0];
}

// Get weight history
export async function getWeightHistory(userId: string, limit: number = 14) {
  const result = await query(
    'SELECT * FROM weight_log WHERE user_id = $1 ORDER BY day_key DESC LIMIT $2',
    [userId, limit]
  );
  return result.rows;
}

// Get day water
export async function getDayWater(userId: string, dayKey: string) {
  const result = await query(
    'SELECT COALESCE(SUM(amount_ml), 0) as total FROM water_log WHERE user_id = $1 AND day_key = $2',
    [userId, dayKey]
  );
  return result.rows[0]?.total || 0;
}

// Get streak (simplified — count consecutive days at/under target)
export async function getStreak(userId: string, targetKcal: number) {
  // Get recent daily totals
  const result = await query(
    `SELECT day_key, SUM(kcal) as day_kcal FROM meals WHERE user_id = $1
     GROUP BY day_key ORDER BY day_key DESC LIMIT 60`,
    [userId]
  );
  let streak = 0;
  for (const row of result.rows) {
    if (row.day_kcal <= targetKcal) {
      streak++;
    } else {
      break;
    }
  }
  return streak;
}

// Get week totals for chart
export async function getWeekTotals(userId: string, endDate: string) {
  const result = await query(
    `SELECT day_key, SUM(kcal) as day_kcal, SUM(protein_g) as day_protein,
            SUM(carbs_g) as day_carbs, SUM(fat_g) as day_fat
     FROM meals WHERE user_id = $1 AND day_key > $2::date - interval '7 days' AND day_key <= $2
     GROUP BY day_key ORDER BY day_key`,
    [userId, endDate]
  );
  return result.rows;
}

// Add a meal
export async function addMeal(userId: string, dayKey: string, windowIdx: number,
  kcal: number, protein: number, carbs: number, fat: number,
  description: string, rawAnalysis: string, photoUrl?: string, waterMl: number = 0) {
  const result = await query(
    `INSERT INTO meals (user_id, day_key, window_idx, timestamp, kcal, protein_g, carbs_g, fat_g,
     description, raw_analysis, photo_url, water_ml)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) RETURNING id`,
    [userId, dayKey, windowIdx, new Date().toISOString(), kcal, protein, carbs, fat,
     description || '', rawAnalysis, photoUrl || null, waterMl]
  );
  return result.rows[0]?.id;
}

// Add water
export async function addWater(userId: string, dayKey: string, amountMl: number, source: string = 'manual') {
  await query(
    'INSERT INTO water_log (user_id, day_key, amount_ml, source, timestamp) VALUES ($1, $2, $3, $4, $5)',
    [userId, dayKey, amountMl, source, new Date().toISOString()]
  );
}
