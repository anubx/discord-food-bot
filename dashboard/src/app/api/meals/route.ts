import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import { addMeal, addWater } from '@/lib/db';
import { NextResponse } from 'next/server';

// Parse $$TOTALS$$ from AI response
function parseTotals(analysis: string) {
  const match = analysis.match(/\$\$TOTALS:\s*kcal=(\d+),\s*protein=(\d+),\s*carbs=(\d+),\s*fat=(\d+)(?:,\s*water=(\d+))?\$\$/);
  if (match) {
    return {
      kcal: parseInt(match[1]), protein: parseInt(match[2]),
      carbs: parseInt(match[3]), fat: parseInt(match[4]),
      water_ml: match[5] ? parseInt(match[5]) : 0,
    };
  }
  return null;
}

// Get meal window index based on hour
function getWindowIdx(hour: number): number {
  if (hour >= 7 && hour < 10) return 0;
  if (hour >= 10 && hour < 13) return 1;
  if (hour >= 13 && hour < 16) return 2;
  if (hour >= 16 && hour < 19) return 3;
  if (hour >= 19 && hour < 22) return 4;
  return 5; // 22-4
}

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const discordId = (session.user as any).discordId;
  const body = await request.json();
  const { analysis, description, photoUrl } = body;

  if (!analysis) return NextResponse.json({ error: 'No analysis provided' }, { status: 400 });

  const parsed = parseTotals(analysis);
  if (!parsed) return NextResponse.json({ error: 'Could not parse totals' }, { status: 400 });

  const now = new Date();
  const dayKey = now.getHours() < 4
    ? new Date(now.getTime() - 86400000).toISOString().split('T')[0]
    : now.toISOString().split('T')[0];
  const windowIdx = getWindowIdx(now.getHours());

  const mealId = await addMeal(
    discordId, dayKey, windowIdx,
    parsed.kcal, parsed.protein, parsed.carbs, parsed.fat,
    description || '', analysis, photoUrl, parsed.water_ml
  );

  // Auto-log food water
  if (parsed.water_ml > 0) {
    await addWater(discordId, dayKey, parsed.water_ml, 'food');
  }

  return NextResponse.json({ mealId, parsed });
}
