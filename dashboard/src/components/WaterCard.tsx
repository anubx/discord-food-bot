'use client';

interface WaterCardProps {
  current: number;
  target: number;
}

export default function WaterCard({ current, target }: WaterCardProps) {
  const percent = Math.min(100, (current / target) * 100);
  const remaining = Math.max(0, target - current);
  const glasses = Math.ceil(remaining / 250);
  const fromFood = Math.round(current * 0.3);
  const manual = current - fromFood;

  const glasses_filled = Math.floor(percent / 10);
  const glasses_total = 10;

  return (
    <div className="bg-slate-900 rounded-xl p-5 border border-slate-800">
      <h3 className="font-semibold text-white text-sm mb-3">💧 Water Today</h3>
      <div className="text-center mb-3">
        <div className="text-3xl font-bold text-cyan-400">
          {current}
          <span className="text-lg text-slate-500 font-normal">ml</span>
        </div>
        <div className="text-xs text-slate-500 mt-1">of {target}ml target ({percent.toFixed(0)}%)</div>
      </div>
      <div className="flex gap-1 mb-4">
        {Array.from({ length: glasses_total }).map((_, i) => (
          <div
            key={i}
            className={`flex-1 h-5 rounded ${i < glasses_filled ? 'bg-gradient-to-b from-cyan-400 to-cyan-600' : 'bg-slate-800'}`}
          ></div>
        ))}
      </div>
      <div className="space-y-1.5 text-xs">
        <div className="flex justify-between py-1"><span className="text-slate-500">From food</span><span>{fromFood}ml (auto)</span></div>
        <div className="flex justify-between py-1 border-t border-slate-800/50"><span className="text-slate-500">Manual</span><span>{manual}ml</span></div>
        <div className="flex justify-between py-1 border-t border-slate-800/50">
          <span className="text-slate-500">Remaining</span>
          <span className="text-cyan-400 font-semibold">{remaining}ml (~{glasses} glasses)</span>
        </div>
      </div>
    </div>
  );
}
