'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase';
import Header from '@/components/Header';
import type { DailyRecord, Widget } from '@/types';

function getPast7Days(): string[] {
  const days: string[] = [];
  const now = new Date();
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  for (let i = 6; i >= 0; i--) {
    const d = new Date(jst);
    d.setDate(d.getDate() - i);
    days.push(d.toISOString().split('T')[0]);
  }
  return days;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  const days = ['日', '月', '火', '水', '木', '金', '土'];
  return `${d.getMonth() + 1}/${d.getDate()}(${days[d.getDay()]})`;
}

interface DayStats {
  date: string;
  completionRate: number;
  recordedCount: number;
  totalWidgets: number;
}

export default function HistoryPage() {
  const router = useRouter();
  const supabase = createClient();

  const [stats, setStats] = useState<DayStats[]>([]);
  const [currentStreak, setCurrentStreak] = useState(0);
  const [longestStreak, setLongestStreak] = useState(0);
  const [totalRecorded, setTotalRecorded] = useState(0);
  const [loading, setLoading] = useState(true);

  const loadHistory = useCallback(async () => {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) { router.replace('/'); return; }

    // Get widgets
    const { data: dashboardData } = await supabase
      .from('dashboards')
      .select('id')
      .eq('user_id', user.id)
      .single();

    if (!dashboardData) { setLoading(false); return; }

    const { data: widgets } = await supabase
      .from('widgets')
      .select('id')
      .eq('dashboard_id', dashboardData.id);

    const widgetIds = (widgets ?? []).map((w: Pick<Widget, 'id'>) => w.id);
    const totalWidgets = widgetIds.length;

    const past7 = getPast7Days();

    // Fetch records for past 7 days
    const { data: records } = await supabase
      .from('records')
      .select('widget_id, date')
      .eq('user_id', user.id)
      .in('date', past7)
      .in('widget_id', widgetIds.length > 0 ? widgetIds : ['__none__']);

    const recordsByDate = new Map<string, Set<string>>();
    for (const r of (records ?? []) as Pick<DailyRecord, 'widget_id' | 'date'>[]) {
      if (!recordsByDate.has(r.date)) recordsByDate.set(r.date, new Set());
      recordsByDate.get(r.date)!.add(r.widget_id);
    }

    const dayStats: DayStats[] = past7.map((date) => {
      const recorded = recordsByDate.get(date)?.size ?? 0;
      const rate = totalWidgets > 0 ? Math.round((recorded / totalWidgets) * 100) : 0;
      return { date, completionRate: rate, recordedCount: recorded, totalWidgets };
    });

    setStats(dayStats);

    // Calculate streaks
    const today = getPast7Days()[6];
    let streak = 0;
    let longest = 0;
    let tempStreak = 0;
    let total = 0;

    for (const s of dayStats) {
      if (s.completionRate === 100) {
        tempStreak++;
        total++;
        if (tempStreak > longest) longest = tempStreak;
      } else {
        tempStreak = 0;
      }
    }

    // Current streak (from today backwards)
    const reversed = [...dayStats].reverse();
    for (const s of reversed) {
      if (s.completionRate === 100) streak++;
      else break;
    }

    setCurrentStreak(streak);
    setLongestStreak(longest);
    setTotalRecorded(total);
    setLoading(false);
  }, [supabase, router]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--bg)' }}>
        <div
          className="w-6 h-6 border-2 rounded-full"
          style={{
            borderColor: 'var(--border)',
            borderTopColor: 'var(--accent)',
            animation: 'spin 0.8s linear infinite',
          }}
        />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--bg)', maxWidth: 480, margin: '0 auto' }}>
      <Header />

      <main className="flex-1 px-4 pb-8">
        {/* Title */}
        <div className="py-4">
          <p className="label-base">7日間の記録</p>
        </div>

        {/* Streak stats */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          {[
            { label: '現在のストリーク', value: `${currentStreak}日`, icon: '🔥' },
            { label: '最長ストリーク', value: `${longestStreak}日`, icon: '🏆' },
            { label: '完全達成日', value: `${totalRecorded}日`, icon: '✅' },
          ].map((stat) => (
            <div key={stat.label} className="card p-3 text-center">
              <p className="text-lg mb-1">{stat.icon}</p>
              <p className="text-xl font-light">{stat.value}</p>
              <p className="text-xs mt-1" style={{ color: 'var(--text-muted)', lineHeight: 1.3 }}>
                {stat.label}
              </p>
            </div>
          ))}
        </div>

        {/* 7-day calendar strip */}
        <div className="card p-4 mb-6">
          <p className="label-base mb-4">達成率</p>
          <div className="flex gap-2">
            {stats.map((s) => {
              const isToday = s.date === getPast7Days()[6];
              const rate = s.completionRate;
              const color =
                rate === 100
                  ? 'var(--success)'
                  : rate >= 50
                  ? 'var(--accent)'
                  : rate > 0
                  ? 'var(--text-muted)'
                  : 'var(--border)';

              return (
                <div key={s.date} className="flex-1 flex flex-col items-center gap-1">
                  <div
                    style={{
                      width: '100%',
                      aspectRatio: '1',
                      backgroundColor: 'var(--bg-hover)',
                      borderRadius: 4,
                      border: `1px solid ${isToday ? 'var(--accent)' : 'var(--border)'}`,
                      position: 'relative',
                      overflow: 'hidden',
                    }}
                  >
                    {/* Fill bar */}
                    <div
                      style={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        height: `${rate}%`,
                        backgroundColor: color,
                        opacity: 0.25,
                        transition: 'height 0.3s ease',
                      }}
                    />
                    {/* Percentage */}
                    <div
                      className="absolute inset-0 flex items-center justify-center text-xs font-medium"
                      style={{ color: rate > 0 ? color : 'var(--text-muted)', fontSize: 10 }}
                    >
                      {rate > 0 ? `${rate}%` : '—'}
                    </div>
                  </div>
                  <p className="text-center" style={{ color: 'var(--text-muted)', fontSize: 9 }}>
                    {formatDate(s.date).split('(')[1]?.replace(')', '') ?? ''}
                  </p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Day-by-day detail */}
        <div>
          <p className="label-base mb-3">日別詳細</p>
          <div className="space-y-2">
            {[...stats].reverse().map((s) => {
              const isToday = s.date === getPast7Days()[6];
              return (
                <div
                  key={s.date}
                  className="card p-4 flex items-center gap-4"
                  style={{ borderColor: isToday ? 'var(--accent)' : 'var(--border)' }}
                >
                  <div className="flex-shrink-0">
                    <p className="text-sm font-medium">{formatDate(s.date)}</p>
                    {isToday && (
                      <span className="text-xs" style={{ color: 'var(--accent)' }}>今日</span>
                    )}
                  </div>
                  <div className="flex-1">
                    <div
                      style={{
                        height: 4,
                        backgroundColor: 'var(--border)',
                        borderRadius: 2,
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          width: `${s.completionRate}%`,
                          height: '100%',
                          backgroundColor:
                            s.completionRate === 100
                              ? 'var(--success)'
                              : 'var(--accent)',
                          borderRadius: 2,
                          transition: 'width 0.3s ease',
                        }}
                      />
                    </div>
                  </div>
                  <div className="flex-shrink-0 text-right">
                    <p className="text-sm font-light">{s.recordedCount}/{s.totalWidgets}</p>
                    <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{s.completionRate}%</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}
