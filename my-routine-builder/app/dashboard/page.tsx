'use client';

import { useEffect, useState, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { createClient } from '@/lib/supabase';
import Header from '@/components/Header';
import WidgetCard from '@/components/widgets/WidgetCard';
import RecordModal from '@/components/RecordModal';
import UpgradeModal from '@/components/UpgradeModal';
import type { Widget, DailyRecord, WidgetWithRecord, RecordValue } from '@/types';

function todayJST(): string {
  const now = new Date();
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return jst.toISOString().split('T')[0];
}

export default function DashboardPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--bg)' }}>
        <div className="w-6 h-6 border-2 rounded-full" style={{ borderColor: 'var(--border)', borderTopColor: 'var(--accent)', animation: 'spin 0.8s linear infinite' }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    }>
      <DashboardContent />
    </Suspense>
  );
}

function DashboardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const supabase = createClient();

  const today = todayJST();

  const [widgets, setWidgets] = useState<WidgetWithRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedWidget, setSelectedWidget] = useState<WidgetWithRecord | null>(null);
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [completionBanner, setCompletionBanner] = useState(false);
  const [hasDashboard, setHasDashboard] = useState<boolean | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) { router.replace('/'); return; }

      // Check if dashboard exists
      const { data: dashboardData } = await supabase
        .from('dashboards')
        .select('id, theme')
        .eq('user_id', user.id)
        .single();

      if (!dashboardData) {
        setHasDashboard(false);
        setLoading(false);
        return;
      }

      setHasDashboard(true);

      // Apply theme
      const { data: dashboard } = await supabase
        .from('dashboards')
        .select('theme')
        .eq('user_id', user.id)
        .single();

      if (dashboard?.theme) {
        document.documentElement.setAttribute('data-theme', dashboard.theme);
        localStorage.setItem('theme', dashboard.theme);
      }

      // Load widgets
      const [widgetsRes, recordsRes] = await Promise.all([
        fetch('/api/widgets'),
        fetch(`/api/records?date=${today}`),
      ]);

      const { widgets: rawWidgets }: { widgets: Widget[] } = await widgetsRes.json();
      const { records }: { records: DailyRecord[] } = await recordsRes.json();

      const recordMap = new Map(records.map((r) => [r.widget_id, r]));

      const enriched: WidgetWithRecord[] = (rawWidgets ?? []).map((w) => ({
        ...w,
        record: recordMap.get(w.id),
      }));

      setWidgets(enriched);

      // Check if all widgets are recorded
      if (enriched.length > 0 && enriched.every((w) => !!w.record)) {
        setCompletionBanner(true);
      }
    } catch (e) {
      console.error('Dashboard load error:', e);
    } finally {
      setLoading(false);
    }
  }, [supabase, router, today]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Show upgrade success message
  useEffect(() => {
    if (searchParams.get('upgraded') === '1') {
      // Could show a toast here
    }
  }, [searchParams]);

  const handleRecordSaved = (widgetId: string, value: RecordValue) => {
    setWidgets((prev) => {
      const updated = prev.map((w) =>
        w.id === widgetId
          ? {
              ...w,
              record: {
                id: `temp-${widgetId}`,
                widget_id: widgetId,
                user_id: '',
                date: today,
                value,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            }
          : w
      );

      if (updated.every((w) => !!w.record)) {
        setTimeout(() => setCompletionBanner(true), 200);
      }

      return updated;
    });
  };

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

  if (hasDashboard === false) {
    return (
      <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--bg)', maxWidth: 480, margin: '0 auto' }}>
        <Header />
        <div className="flex-1 flex flex-col items-center justify-center px-4 text-center">
          <p className="text-3xl mb-4">◈</p>
          <h2 className="text-lg font-medium mb-2">ダッシュボードがまだありません</h2>
          <p className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>
            AIと会話してあなただけのダッシュボードを作りましょう
          </p>
          <button
            className="btn-primary"
            onClick={() => router.push('/onboarding')}
          >
            今すぐ作成する →
          </button>
        </div>
      </div>
    );
  }

  const recorded = widgets.filter((w) => !!w.record).length;
  const total = widgets.length;
  const progressPercent = total > 0 ? Math.round((recorded / total) * 100) : 0;

  return (
    <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--bg)', maxWidth: 480, margin: '0 auto' }}>
      <Header />

      <main className="flex-1 px-4 pb-8">
        {/* Date + Progress */}
        <div className="py-4">
          <p className="label-base mb-2">{today}</p>
          <div className="flex items-center gap-3">
            <div
              className="flex-1"
              style={{ height: 3, backgroundColor: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}
            >
              <div
                style={{
                  width: `${progressPercent}%`,
                  height: '100%',
                  backgroundColor: 'var(--accent)',
                  borderRadius: 2,
                  transition: 'width 0.3s ease',
                }}
              />
            </div>
            <span className="text-xs" style={{ color: 'var(--text-muted)', flexShrink: 0 }}>
              {recorded}/{total}
            </span>
          </div>
        </div>

        {/* Completion banner */}
        {completionBanner && (
          <div
            className="mb-4 py-3 px-4 text-sm font-medium text-center rounded animate-fade-in"
            style={{
              backgroundColor: 'rgba(74, 222, 128, 0.08)',
              border: '1px solid var(--success)',
              color: 'var(--success)',
            }}
          >
            今日の記録が完了しました！継続は力なり 🎉
          </div>
        )}

        {/* Widget grid */}
        {widgets.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              ウィジェットがありません
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {widgets.map((widget) => (
              <WidgetCard
                key={widget.id}
                widget={widget}
                onClick={() => setSelectedWidget(widget)}
              />
            ))}
          </div>
        )}

        {/* Add widget button (for Pro / within limit) */}
        <button
          onClick={() => setShowUpgrade(true)}
          className="w-full mt-4 py-3 text-xs rounded"
          style={{
            border: '1px dashed var(--border)',
            color: 'var(--text-muted)',
            backgroundColor: 'transparent',
            cursor: 'pointer',
          }}
        >
          + ウィジェットを追加
        </button>
      </main>

      {/* Record modal */}
      {selectedWidget && (
        <RecordModal
          widget={selectedWidget}
          date={today}
          onClose={() => setSelectedWidget(null)}
          onSaved={handleRecordSaved}
        />
      )}

      {/* Upgrade modal */}
      {showUpgrade && (
        <UpgradeModal onClose={() => setShowUpgrade(false)} />
      )}
    </div>
  );
}
