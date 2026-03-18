import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import { query, addMeal, addWater } from '@/lib/db';
import { NextResponse } from 'next/server';

// GET: list templates
export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const discordId = (session.user as any).discordId;

  const result = await query('SELECT * FROM meal_templates WHERE user_id = $1 ORDER BY name', [discordId]);
  return NextResponse.json({ templates: result.rows });
}

// POST: log a template as a meal
export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const discordId = (session.user as any).discordId;
  const { templateName } = await request.json();

  // Get template
  const tResult = await query('SELECT * FROM meal_templates WHERE user_id = $1 AND name = $2', [discordId, templateName.toLowerCase().trim()]);
  const template = tResult.rows[0];
  if (!template) return NextResponse.json({ error: 'Template not found' }, { status: 404 });

  // Get food day (day runs from 4am to 3:59am next day)
  const now = new Date();
  const dayKey = now.getHours() < 4
    ? new Date(now.getTime() - 86400000).toISOString().split('T')[0]
    : now.toISOString().split('T')[0];

  // Get window index
  const hour = now.getHours();
  let windowIdx = 5; // evening snack default
  if (hour >= 7 && hour < 10) windowIdx = 0;   // breakfast
  else if (hour >= 10 && hour < 13) windowIdx = 1; // morning snack
  else if (hour >= 13 && hour < 16) windowIdx = 2; // lunch
  else if (hour >= 16 && hour < 19) windowIdx = 3; // afternoon snack
  else if (hour >= 19 && hour < 22) windowIdx = 4; // dinner

  // Insert meal
  const mealId = await addMeal(
    discordId, dayKey, windowIdx,
    template.kcal, template.protein_g, template.carbs_g, template.fat_g,
    template.description || ('template: ' + template.name),
    'Template: ' + template.name,
    null,
    template.water_ml || 0
  );

  // Auto-log water from template
  if (template.water_ml > 0) {
    await addWater(discordId, dayKey, template.water_ml, 'food');
  }

  return NextResponse.json({ mealId, template });
}

// DELETE: remove a template
export async function DELETE(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const discordId = (session.user as any).discordId;
  const { name } = await request.json();

  const result = await query('DELETE FROM meal_templates WHERE user_id = $1 AND name = $2', [discordId, name.toLowerCase().trim()]);
  return NextResponse.json({ deleted: (result.rowCount || 0) > 0 });
}
