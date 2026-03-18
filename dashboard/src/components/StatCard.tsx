'use client';

interface StatCardProps {
  icon: string;
  label: string;
  value: string | number;
  target: string | number;
  percent: number;
  color: 'orange' | 'red' | 'yellow' | 'blue' | 'cyan';
}

const colorMap = {
  orange: { gradient: 'from-orange-500 to-orange-400', text: 'text-orange-400' },
  red: { gradient: 'from-red-500 to-red-400', text: 'text-red-400' },
  yellow: { gradient: 'from-yellow-500 to-yellow-400', text: 'text-yellow-400' },
  blue: { gradient: 'from-blue-500 to-blue-400', text: 'text-blue-400' },
  cyan: { gradient: 'from-cyan-500 to-cyan-400', text: 'text-cyan-400' },
};

export default function StatCard({
  icon, label, value, target, percent, color
}: StatCardProps) {
  const colors = colorMap[color];
  const safePercent = Math.min(100, Math.max(0, percent));

  return (
    <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 hover:border-slate-700 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">{icon} {label}</span>
        <span className="text-[11px] text-slate-600">{safePercent}%</span>
      </div>
      <div className={`text-2xl font-bold ${colors.text}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-1">of {target} target</div>
      <div className="mt-3 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full bg-gradient-to-r ${colors.gradient} rounded-full`} style={{ width: `${safePercent}%` }}></div>
      </div>
    </div>
  );
}
