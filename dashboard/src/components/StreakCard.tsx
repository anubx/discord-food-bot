'use client';

interface StreakCardProps {
  streak: number;
  targetKcal: number;
}

export default function StreakCard({ streak, targetKcal }: StreakCardProps) {
  const getAchievements = () => {
    return [
      { label: '🔥 3d', unlocked: streak >= 3 },
      { label: '⭐ 7d', unlocked: streak >= 7 },
      { label: '🏆 14d', unlocked: streak >= 14 },
      { label: '💎 30d', unlocked: streak >= 30 },
    ];
  };

  return (
    <div className="bg-slate-900 rounded-xl p-5 border border-slate-800 text-center">
      <h3 className="font-semibold text-white text-sm mb-2 text-left">🔥 Streak</h3>
      <div className="text-5xl font-extrabold text-orange-400 my-3">{streak}</div>
      <div className="text-sm text-slate-400 mb-3">days on target</div>
      <div className="flex gap-2 justify-center mb-4">
        {getAchievements().map((ach, idx) => (
          <span
            key={idx}
            className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
              ach.unlocked
                ? 'bg-green-500/15 text-green-400'
                : 'bg-slate-800 text-slate-500'
            }`}
          >
            {ach.label}
          </span>
        ))}
      </div>
      <div className="space-y-1.5 text-xs text-left">
        <div className="flex justify-between py-1 border-t border-slate-800">
          <span className="text-slate-500">Best streak</span>
          <span className="font-semibold">{streak} days</span>
        </div>
        <div className="flex justify-between py-1 border-t border-slate-800/50">
          <span className="text-slate-500">Weekly avg</span>
          <span className="font-semibold">{targetKcal} kcal/day</span>
        </div>
      </div>
    </div>
  );
}
