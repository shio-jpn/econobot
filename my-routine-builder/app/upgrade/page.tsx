'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { createClient } from '@/lib/supabase';
import Header from '@/components/Header';

export default function UpgradePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--bg)' }}>
        <div className="w-6 h-6 border-2 rounded-full" style={{ borderColor: 'var(--border)', borderTopColor: 'var(--accent)', animation: 'spin 0.8s linear infinite' }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    }>
      <UpgradeContent />
    </Suspense>
  );
}

function UpgradeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const supabase = createClient();

  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const wasCanceled = searchParams.get('canceled') === '1';

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (!user) router.replace('/');
      else setChecking(false);
    });
  }, [supabase, router]);

  const handleCheckout = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/stripe/checkout', { method: 'POST' });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setLoading(false);
      }
    } catch {
      setLoading(false);
    }
  };

  if (checking) {
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

      <main className="flex-1 px-4 pb-8 flex flex-col">
        <div className="py-4">
          <p className="label-base">アップグレード</p>
        </div>

        {wasCanceled && (
          <div
            className="mb-4 p-3 text-xs rounded"
            style={{
              backgroundColor: 'rgba(251, 191, 36, 0.1)',
              border: '1px solid var(--warning)',
              color: 'var(--warning)',
            }}
          >
            チェックアウトがキャンセルされました。いつでも再開できます。
          </div>
        )}

        {/* Plan comparison */}
        <div className="card p-6 mb-6 text-center">
          <p className="label-base mb-2">Pro プラン</p>
          <p className="text-4xl font-light mb-1">¥480</p>
          <p className="text-xs mb-6" style={{ color: 'var(--text-muted)' }}>月額 · いつでもキャンセル可能</p>

          <div className="space-y-4 text-left mb-8">
            {[
              {
                icon: '◉',
                title: '無制限ダッシュボード',
                desc: 'テーマ別・目標別に複数作成できます',
              },
              {
                icon: '◉',
                title: '無制限ウィジェット',
                desc: 'Freeは3つまで。Proは制限なし',
              },
              {
                icon: '◉',
                title: '全期間の履歴閲覧',
                desc: '過去のすべての記録を確認できます',
              },
              {
                icon: '◉',
                title: 'カスタムテーマ',
                desc: 'ダーク / ライト / セージ 全3テーマ',
              },
            ].map((feature) => (
              <div key={feature.title} className="flex gap-3">
                <span className="text-sm mt-0.5 flex-shrink-0" style={{ color: 'var(--success)' }}>
                  {feature.icon}
                </span>
                <div>
                  <p className="text-sm font-medium">{feature.title}</p>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    {feature.desc}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <button
            onClick={handleCheckout}
            disabled={loading}
            className="btn-primary w-full py-4 text-sm"
          >
            {loading ? '処理中...' : 'Proにアップグレード →'}
          </button>
        </div>

        {/* Free plan reminder */}
        <div
          className="p-4 rounded text-sm"
          style={{
            border: '1px solid var(--border)',
            backgroundColor: 'var(--bg-card)',
          }}
        >
          <p className="font-medium mb-2">現在のFreeプランの制限</p>
          <ul className="space-y-1">
            {['1ダッシュボードのみ', '最大3ウィジェット', '7日間の履歴'].map((item) => (
              <li key={item} className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                <span>—</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <button
          onClick={() => router.back()}
          className="btn-ghost text-xs mt-4 self-center"
        >
          ← 戻る
        </button>
      </main>
    </div>
  );
}
