'use client';

interface WeightLog {
  day_key: string;
  weight_kg: number;
}

interface WeightCardProps {
  weights: WeightLog[];
}

export default function WeightCard({ weights }: WeightCardProps) {
  const sortedWeights = [...weights].sort((a, b) => a.day_key.localeCompare(b.day_key));
  const current = sortedWeights[sortedWeights.length - 1]?.weight_kg || 0;
  const oldest = sortedWeights[0]?.weight_kg || 0;
  const changeNum = current && oldest ? current - oldest : 0;
  const change = changeNum.toFixed(1);

  const minWeight = Math.min(...sortedWeights.map(w => w.weight_kg || 0), current);
  const maxWeight = Math.max(...sortedWeights.map(w => w.weight_kg || 0), current);
  const range = maxWeight - minWeight || 1;

  const baseHeight = 20;
  const chartHeight = 80;

  return (
    <div className="bg-slate-900 rounded-xl p-5 border border-slate-800">
      <h3 className="font-semibold text-white text-sm mb-4">⚖️ Weight Trend</h3>
      <div className="flex items-end justify-between h-20 px-1 mb-3">
        {sortedWeights.slice(-7).map((w, idx) => {
          const normalized = (w.weight_kg - minWeight) / range;
          const barHeight = baseHeight + normalized * chartHeight;
          const isLatest = idx === sortedWeights.slice(-7).length - 1;

          return (
            <div key={idx} className="flex flex-col items-center gap-1">
              <div
                className={`w-1 rounded-full ${isLatest ? 'bg-green-500' : 'bg-violet-500'}`}
                style={{ height: `${barHeight}px` }}
              ></div>
              <span className={`text-[10px] ${isLatest ? 'text-green-400 font-semibold' : 'text-slate-600'}`}>
                {w.weight_kg.toFixed(1)}
              </span>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between py-2 text-xs border-t border-slate-800">
        <span className="text-slate-500">This week</span>
        <span className={changeNum < 0 ? 'text-green-400 font-semibold' : 'text-slate-400 font-semibold'}>
          {changeNum < 0 ? '-' : ''}{Math.abs(changeNum).toFixed(1)} kg {changeNum < 0 ? '📉' : changeNum > 0 ? '📈' : '-'}
        </span>
      </div>
    </div>
  );
}
