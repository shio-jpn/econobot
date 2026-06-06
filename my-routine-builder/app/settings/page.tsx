'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase';
import Header from '@/components/Header';
import type { Theme, Widget, Subscription } from '@/types';

const THEMES: { value: Theme; label: string; desc: string }[] = [
  { value: 'dark', label: 'ダーク', desc: '#0a0a0a' },
  { value: 'light', label: 'ライト', desc: '#ffffff' },
  { value: 'sage', label: 'セージ', desc: '#1a2418' },
];

export default function SettingsPage() {
  const router = useRouter();
  const supabase = createClient();

  const [theme, setTheme] = useState<Theme>('dark');
  const [widgets, setWidgets] = useState<Widget[]>([]);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [dashboardId, setDashboardId] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);

  const loadSettings = useCallback(async () => {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) { router.replace('/'); return; }

    const [dashRes, subRes] = await Promise.all([
      supabase.from('dashboards').select('id, theme').eq('user_id', user.id).single(),
      supabase.from('subscriptions').select('*').eq('user_id', user.id).single(),
    ]);

    if (dashRes.data) {
      setDashboardId(dashRes.data.id);
      setTheme(dashRes.data.theme as Theme);

      const { data: widgetsData } = await supabase
        .from('widgets')
        .select('*')
        .eq('dashboard_id', dashRes.data.id)
        .order('position');

      setWidgets(widgetsData ?? []);
    }

    if (subRes.data) {
      setSubscription(subRes.data as Subscription);
    }

    setLoading(false);
  }, [supabase, router]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleThemeChange = async (newTheme: Theme) => {
    setTheme(newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);

    if (!dashboardId) return;
    setSaving(true);
    await supabase
      .from('dashboards')
      .update({ theme: newTheme })
      .eq('id', dashboardId);
    setSaving(false);
  };

  const handleDeleteWidget = async (widgetId: string) => {
    setDeleteId(widgetId);
    const res = await fetch(`/api/widgets?id=${widgetId}`, { method: 'DELETE' });
    if (res.ok) {
      setWidgets((prev) => prev.filter((w) => w.id !== widgetId));
    }
    setDeleteId(null);
  };

  const handlePortal = async () => {
    setPortalLoading(true);
    const res = await fetch('/api/stripe/portal', { method: 'POST' });
    const data = await res.json();
    if (data.url) window.location.href = data.url;
    else setPortalLoading(false);
  };

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.replace('/');
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

  return (
    <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--bg)', maxWidth: 480, margin: '0 auto' }}>
      <Header />

      <main className="flex-1 px-4 pb-8">
        <div className="py-4">
          <p className="label-base">設定</p>
        </div>

        {/* Theme Section */}
        <section className="mb-6">
          <p className="label-base mb-3">テーマ</p>
          <div className="space-y-2">
            {THEMES.map((t) => (
              <button
                key={t.value}
                onClick={() => handleThemeChange(t.value)}
                className="w-full card p-4 flex items-center justify-between text-left transition-all"
                style={{
                  borderColor: theme === t.value ? 'var(--accent)' : 'var(--border)',
                  backgroundColor: theme === t.value ? 'var(--bg-hover)' : 'var(--bg-card)',
                }}
              >
                <div className="flex items-center gap-3">
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: 4,
                      backgroundColor: t.value === 'dark' ? '#0a0a0a' : t.value === 'light' ? '#ffffff' : '#1a2418',
                      border: '1px solid var(--border)',
                    }}
                  />
                  <div>
                    <p className="text-sm font-medium">{t.label}</p>
                    <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{t.desc}</p>
                  </div>
                </div>
                {theme === t.value && (
                  <span className="text-xs" style={{ color: 'var(--accent)' }}>✓</span>
                )}
              </button>
            ))}
          </div>
          {saving && (
            <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>保存中...</p>
          )}
        </section>

        <hr className="divider mb-6" />

        {/* Widgets Section */}
        <section className="mb-6">
          <p className="label-base mb-3">ウィジェット管理</p>
          {widgets.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              ウィジェットがありません
            </p>
          ) : (
            <div className="space-y-2">
              {widgets.map((w) => (
                <div
                  key={w.id}
                  className="card p-3 flex items-center justify-between"
                >
                  <div className="flex items-center gap-2">
                    <span>{w.icon}</span>
                    <div>
                      <p className="text-sm">{w.label}</p>
                      <p className="text-xs uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
                        {w.type}{w.unit ? ` · ${w.unit}` : ''}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => handleDeleteWidget(w.id)}
                    disabled={deleteId === w.id}
                    className="btn-ghost text-xs px-2 py-1"
                    style={{ color: 'var(--danger)' }}
                  >
                    {deleteId === w.id ? '...' : '削除'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        <hr className="divider mb-6" />

        {/* Plan Section */}
        <section className="mb-6">
          <p className="label-base mb-3">プラン</p>
          <div className="card p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-sm font-medium">
                  {subscription?.plan === 'pro' ? 'Pro プラン' : 'Free プラン'}
                </p>
                {subscription?.plan === 'pro' && subscription.current_period_end && (
                  <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    次回更新: {new Date(subscription.current_period_end).toLocaleDateString('ja-JP')}
                  </p>
                )}
              </div>
              <span className={subscription?.plan === 'pro' ? 'badge-pro' : 'badge-free'}>
                {subscription?.plan === 'pro' ? 'PRO' : 'FREE'}
              </span>
            </div>

            {subscription?.plan === 'pro' ? (
              <button
                onClick={handlePortal}
                disabled={portalLoading}
                className="btn-secondary w-full text-sm"
              >
                {portalLoading ? '読み込み中...' : '請求管理 →'}
              </button>
            ) : (
              <button
                onClick={() => router.push('/upgrade')}
                className="btn-primary w-full text-sm"
              >
                Pro にアップグレード ¥480/月 →
              </button>
            )}
          </div>
        </section>

        <hr className="divider mb-6" />

        {/* Danger zone */}
        <section>
          <p className="label-base mb-3">アカウント</p>
          <button
            onClick={handleSignOut}
            className="btn-secondary w-full text-sm"
            style={{ color: 'var(--text-muted)' }}
          >
            ログアウト
          </button>
        </section>
      </main>
    </div>
  );
}
