'use client';

interface ChartData {
  day_key: string;
  day_kcal: number;
}

interface CalorieChartProps {
  weekData: ChartData[];
  target: number;
}

export default function CalorieChart({ weekData, target }: CalorieChartProps) {
  const maxCalories = Math.max(target * 1.2, Math.max(...weekData.map(d => d.day_kcal || 0), target));
  const chartHeight = 140;

  const getDayLabel = (dateStr: string) => {
    const date = new Date(dateStr + 'T00:00:00');
    return date.toLocaleString('en-US', { weekday: 'short' });
  };

  const isToday = (dateStr: string) => {
    const today = new Date().toISOString().split('T')[0];
    return dateStr === today;
  };

  const getBarColor = (kcal: number) => {
    if (kcal <= target) return 'from-green-600 to-green-500';
    return 'from-red-600 to-red-500';
  };

  return (
    <div className="col-span-2 bg-slate-900 rounded-xl p-5 border border-slate-800">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-white text-sm">📈 Weekly Calorie Trend</h3>
        <div className="flex gap-3 text-[11px]">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500 inline-block"></span> Under target</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block"></span> Over target</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500 inline-block animate-pulse"></span> Today</span>
        </div>
      </div>
      <div className="relative h-48 flex items-end gap-3 px-2 pb-6">
        <div className="absolute left-0 right-0 border-t border-dashed border-slate-700" style={{ bottom: `${chartHeight + 24}px` }}>
          <span className="absolute right-0 -top-4 text-[10px] text-slate-600">{target} kcal</span>
        </div>
        {weekData.slice(-7).map((data, idx) => {
          const barHeight = (data.day_kcal / maxCalories) * chartHeight;
          const today = isToday(data.day_key);

          return (
            <div key={idx} className="flex-1 flex flex-col items-center gap-1">
              <div
                className={`w-full rounded-t-md bg-gradient-to-t ${getBarColor(data.day_kcal)} ${today ? 'shadow-lg shadow-orange-500/20' : ''}`}
                style={{ height: `${barHeight}px` }}
              ></div>
              <span className={`text-[11px] ${today ? 'text-orange-400 font-semibold' : 'text-slate-500'}`}>
                {getDayLabel(data.day_key)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
