'use client';

import Link from 'next/link';
import { signOut, useSession } from 'next-auth/react';

export default function Sidebar() {
  const { data: session } = useSession();
  const initials = session?.user?.name?.split(' ').map(n => n[0]).join('').toUpperCase() || '?';

  return (
    <aside className="w-60 bg-slate-900 border-r border-slate-800 flex flex-col fixed h-screen z-30">
      <div className="px-5 py-5 flex items-center gap-2.5">
        <div className="w-8 h-8 bg-green-500 rounded-lg flex items-center justify-center text-white font-bold text-sm">F</div>
        <span className="font-bold text-lg text-white">FoodTracker</span>
        <span className="ml-auto text-[10px] font-semibold bg-green-500/20 text-green-400 px-1.5 py-0.5 rounded">PRO</span>
      </div>

      <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
        <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider px-2 pt-3 pb-1">Overview</div>
        <Link href="/" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg bg-green-500/10 text-green-400 text-sm font-medium">
          <span>📊</span> Dashboard
        </Link>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>📅</span> Calendar
        </a>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>📈</span> Trends
        </a>

        <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider px-2 pt-4 pb-1">Log</div>
        <Link href="/log" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>➕</span> <span className="text-green-400 font-semibold">Log a Meal</span>
        </Link>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>🍽️</span> Meals
        </a>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>⚖️</span> Weight
        </a>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>💧</span> Water
        </a>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>💪</span> Body Fat
        </a>

        <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider px-2 pt-4 pb-1">Reports</div>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>📊</span> Weekly
        </a>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>📊</span> Monthly
        </a>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>📤</span> Export
        </a>

        <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider px-2 pt-4 pb-1">Account</div>
        <a href="#" className="sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 text-sm">
          <span>⚙️</span> Settings
        </a>
      </nav>

      <div className="px-4 py-3 border-t border-slate-800 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-violet-600 flex items-center justify-center text-white font-bold text-xs">{initials}</div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-white truncate">{session?.user?.name || 'User'}</div>
          <div className="text-[11px] text-green-400">✨ Pro Member</div>
        </div>
        <button
          onClick={() => signOut({ callbackUrl: '/login' })}
          className="text-slate-500 hover:text-slate-300 text-sm"
          title="Sign out"
        >
          🚪
        </button>
      </div>
    </aside>
  );
}
