'use client';

const MEAL_WINDOWS = [
  { label: 'Breakfast', emoji: '🌅' },
  { label: 'Morning Snack', emoji: '🍎' },
  { label: 'Lunch', emoji: '🥗' },
  { label: 'Afternoon Snack', emoji: '🍌' },
  { label: 'Dinner', emoji: '🍽️' },
  { label: 'Evening Snack', emoji: '🌙' },
];

interface Meal {
  id: string;
  window_idx: number;
  description: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  water_ml: number;
  timestamp: string;
}

interface MealsTableProps {
  meals: Meal[];
  totals: any;
}

export default function MealsTable({ meals, totals }: MealsTableProps) {
  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 mb-6">
      <div className="px-5 py-4 flex items-center justify-between border-b border-slate-800">
        <h3 className="font-semibold text-white text-sm">Today's Meals</h3>
        <span className="text-xs text-slate-500">{totals?.meal_count || 0} meals · {totals?.total_kcal || 0} kcal</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <th className="text-left px-5 py-3 font-semibold">Meal</th>
              <th className="text-right px-3 py-3 font-semibold">Kcal</th>
              <th className="text-right px-3 py-3 font-semibold">Protein</th>
              <th className="text-right px-3 py-3 font-semibold">Carbs</th>
              <th className="text-right px-3 py-3 font-semibold">Fat</th>
              <th className="text-right px-5 py-3 font-semibold">Water</th>
            </tr>
          </thead>
          <tbody>
            {meals.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-8 text-slate-500">
                  No meals logged yet. Add one to get started!
                </td>
              </tr>
            ) : (
              meals.map((meal) => (
                <tr key={meal.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg bg-slate-800 flex items-center justify-center text-lg">
                        {MEAL_WINDOWS[meal.window_idx]?.emoji || '🍽️'}
                      </div>
                      <div>
                        <div className="font-medium text-white">{meal.description || 'Meal'}</div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          {formatTime(meal.timestamp)} · {MEAL_WINDOWS[meal.window_idx]?.label || 'Other'}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="text-right px-3 py-3 font-semibold text-orange-400">{meal.kcal}</td>
                  <td className="text-right px-3 py-3 text-slate-300">{meal.protein_g}g</td>
                  <td className="text-right px-3 py-3 text-slate-300">{meal.carbs_g}g</td>
                  <td className="text-right px-3 py-3 text-slate-300">{meal.fat_g}g</td>
                  <td className="text-right px-5 py-3 text-cyan-400/70">{meal.water_ml}ml</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
