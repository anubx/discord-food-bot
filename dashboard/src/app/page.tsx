'use client';

import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import Sidebar from '@/components/Sidebar';
import StatCard from '@/components/StatCard';
import MealsTable from '@/components/MealsTable';
import CalorieChart from '@/components/CalorieChart';
import MacroRing from '@/components/MacroRing';
import WeightCard from '@/components/WeightCard';
import WaterCard from '@/components/WaterCard';
import StreakCard from '@/components/StreakCard';

interface DashboardData {
  user: {
    displayName: string;
    targetKcal: number;
    proteinTarget: number;
    carbs_target: number;
    fat_target: number;
    water_target: number;
    isPremium: boolean;
  };
  dayKey: string;
  totals: {
    total_kcal: number;
    total_protein: number;
    total_carbs: number;
    total_fat: number;
    meal_count: number;
  };
  meals: any[];
  weight: any[];
  water: number;
  streak: number;
  weekData: any[];
}

export default function Dashboard() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/login');
    }
  }, [status, router]);

  useEffect(() => {
    if (session?.user) {
      const fetchStats = async () => {
        try {
          setLoading(true);
          const res = await fetch('/api/stats');
          if (!res.ok) throw new Error('Failed to fetch stats');
          const json = await res.json();
          setData(json);
        } catch (err: any) {
          setError(err.message);
        } finally {
          setLoading(false);
        }
      };

      fetchStats();
      const interval = setInterval(fetchStats, 30000); // Refresh every 30 seconds
      return () => clearInterval(interval);
    }
  }, [session]);

  if (status === 'loading' || loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-slate-700 border-t-green-500 mb-4"></div>
          <p className="text-slate-400">Loading your dashboard...</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="text-center">
          <p className="text-red-400 mb-4">{error || 'Failed to load dashboard'}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg text-white text-sm font-medium"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  const caloriePercent = (data.totals.total_kcal / data.user.targetKcal) * 100;
  const proteinPercent = (data.totals.total_protein / data.user.proteinTarget) * 100;
  const carbsPercent = (data.totals.total_carbs / data.user.carbs_target) * 100;
  const fatPercent = (data.totals.total_fat / data.user.fat_target) * 100;
  const waterPercent = (data.water / data.user.water_target) * 100;

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr + 'T00:00:00');
    return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <div className="flex min-h-screen">
      <Sidebar />

      <main className="ml-60 flex-1 p-6 lg:p-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-sm text-slate-500 mt-0.5">Track your nutrition, hit your goals</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold text-white min-w-[140px] text-center">{formatDate(data.dayKey)}</span>
            <button className="px-3 py-1.5 text-sm bg-green-600 hover:bg-green-500 rounded-lg text-white font-medium">
              Today
            </button>
          </div>
        </div>

        <div className="grid grid-cols-5 gap-4 mb-6">
          <StatCard
            icon="🔥"
            label="Calories"
            value={data.totals.total_kcal}
            target={data.user.targetKcal}
            percent={caloriePercent}
            color="orange"
          />
          <StatCard
            icon="💪"
            label="Protein"
            value={`${data.totals.total_protein}g`}
            target={`${data.user.proteinTarget}g`}
            percent={proteinPercent}
            color="red"
          />
          <StatCard
            icon="🍞"
            label="Carbs"
            value={`${data.totals.total_carbs}g`}
            target={`${data.user.carbs_target}g`}
            percent={carbsPercent}
            color="yellow"
          />
          <StatCard
            icon="🧈"
            label="Fat"
            value={`${data.totals.total_fat}g`}
            target={`${data.user.fat_target}g`}
            percent={fatPercent}
            color="blue"
          />
          <StatCard
            icon="💧"
            label="Water"
            value={`${data.water}ml`}
            target={`${data.user.water_target}ml`}
            percent={waterPercent}
            color="cyan"
          />
        </div>

        <div className="grid grid-cols-3 gap-4 mb-6">
          <CalorieChart weekData={data.weekData} target={data.user.targetKcal} />
          <MacroRing
            kcal={data.totals.total_kcal}
            protein={data.totals.total_protein}
            carbs={data.totals.total_carbs}
            fat={data.totals.total_fat}
          />
        </div>

        <MealsTable meals={data.meals} totals={data.totals} />

        <div className="grid grid-cols-3 gap-4">
          <WeightCard weights={data.weight} />
          <WaterCard current={data.water} target={data.user.water_target} />
          <StreakCard streak={data.streak} targetKcal={data.user.targetKcal} />
        </div>
      </main>
    </div>
  );
}
