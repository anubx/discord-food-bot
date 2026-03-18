import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import { getUserByDiscordId, getDayTotals, getDayMeals, getWeightHistory, getDayWater, getStreak, getWeekTotals } from '@/lib/db';
import { NextResponse } from 'next/server';

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const discordId = (session.user as any).discordId;
  const user = await getUserByDiscordId(discordId);
  if (!user) return NextResponse.json({ error: 'User not found' }, { status: 404 });

  // Get today's food day (4am boundary)
  const now = new Date();
  const dayKey = now.getHours() < 4
    ? new Date(now.getTime() - 86400000).toISOString().split('T')[0]
    : now.toISOString().split('T')[0];

  const [totals, meals, weight, weekData] = await Promise.all([
    getDayTotals(discordId, dayKey),
    getDayMeals(discordId, dayKey),
    getWeightHistory(discordId, 14),
    getWeekTotals(discordId, dayKey),
  ]);

  const water = await getDayWater(discordId, dayKey);
  const streak = await getStreak(discordId, user.target_kcal || 2000);

  return NextResponse.json({
    user: {
      displayName: user.display_name,
      targetKcal: user.target_kcal,
      proteinTarget: user.protein_target,
      carbs_target: user.carbs_target,
      fat_target: user.fat_target,
      water_target: user.water_target || 2500,
      isPremium: !!user.is_premium,
    },
    dayKey,
    totals,
    meals,
    weight,
    water: Number(water),
    streak,
    weekData,
  });
}
