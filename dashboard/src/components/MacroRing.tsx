'use client';

interface MacroRingProps {
  kcal: number;
  protein: number;
  carbs: number;
  fat: number;
}

export default function MacroRing({ kcal, protein, carbs, fat }: MacroRingProps) {
  const total = protein + carbs + fat;
  const proteinPercent = total > 0 ? (protein / total) * 100 : 0;
  const carbsPercent = total > 0 ? (carbs / total) * 100 : 0;
  const fatPercent = total > 0 ? (fat / total) * 100 : 0;

  // SVG ring calculation (circumference = 2πr = 2π(60) ≈ 377)
  const circumference = 377;
  const proteinDash = (proteinPercent / 100) * circumference;
  const carbsDash = (carbsPercent / 100) * circumference;
  const fatDash = (fatPercent / 100) * circumference;

  return (
    <div className="bg-slate-900 rounded-xl p-5 border border-slate-800 flex flex-col items-center justify-center">
      <h3 className="font-semibold text-white text-sm mb-4 self-start">🎯 Macro Split</h3>
      <div className="relative w-40 h-40 mb-4">
        <svg viewBox="0 0 160 160" className="w-full h-full -rotate-90">
          <circle cx="80" cy="80" r="60" fill="none" stroke="#1e293b" strokeWidth="18" />
          <circle cx="80" cy="80" r="60" fill="none" stroke="#ef4444" strokeWidth="18"
            strokeDasharray={`${proteinDash} ${circumference - proteinDash}`}
            strokeDashoffset="0" strokeLinecap="round" />
          <circle cx="80" cy="80" r="60" fill="none" stroke="#eab308" strokeWidth="18"
            strokeDasharray={`${carbsDash} ${circumference - carbsDash}`}
            strokeDashoffset={`-${proteinDash}`} strokeLinecap="round" />
          <circle cx="80" cy="80" r="60" fill="none" stroke="#3b82f6" strokeWidth="18"
            strokeDasharray={`${fatDash} ${circumference - fatDash}`}
            strokeDashoffset={`-${proteinDash + carbsDash}`} strokeLinecap="round" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold text-white">{kcal}</span>
          <span className="text-[11px] text-slate-500">kcal today</span>
        </div>
      </div>
      <div className="flex gap-4 text-xs">
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-red-500"></span> P {proteinPercent.toFixed(0)}%</span>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-yellow-500"></span> C {carbsPercent.toFixed(0)}%</span>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span> F {fatPercent.toFixed(0)}%</span>
      </div>
    </div>
  );
}
