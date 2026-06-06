'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase';

export default function LandingPage() {
  const router = useRouter();
  const supabase = createClient();

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user) {
        router.replace('/dashboard');
      }
    });
  }, [router, supabase]);

  const handleGoogleLogin = async () => {
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
  };

  return (
    <main className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--bg)', color: 'var(--text)' }}>
      {/* Nav */}
      <nav className="w-full mx-auto px-4 py-4 flex items-center justify-between" style={{ maxWidth: 480 }}>
        <span className="text-sm font-medium tracking-widest uppercase" style={{ color: 'var(--text-muted)' }}>
          Routine Builder
        </span>
        <button
          onClick={handleGoogleLogin}
          className="btn-secondary text-xs"
        >
          Sign in
        </button>
      </nav>

      {/* Hero */}
      <section className="flex-1 flex flex-col justify-center px-4 pb-16" style={{ maxWidth: 480, margin: '0 auto', width: '100%' }}>
        <div className="animate-slide-up">
          <p className="label-base mb-4">AI Habit Dashboard</p>
          <h1 className="text-3xl font-light leading-tight tracking-tight mb-6" style={{ letterSpacing: '-0.02em' }}>
            あなただけの<br />
            <span style={{ color: 'var(--accent)', fontWeight: 300 }}>習慣ダッシュボード</span>を<br />
            AIと一緒に作る
          </h1>
          <p className="text-sm leading-relaxed mb-10" style={{ color: 'var(--text-muted)' }}>
            5つの質問に答えるだけ。AIがあなたの目標に合った
            習慣トラッカーを自動生成します。毎日の記録を
            シンプルに続けられる環境を作りましょう。
          </p>
          <button
            onClick={handleGoogleLogin}
            className="btn-primary w-full py-3 text-sm tracking-wide"
          >
            Googleでログイン して始める →
          </button>
          <p className="text-center mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
            無料で始められます。クレジットカード不要。
          </p>
        </div>

        {/* Feature cards */}
        <div className="mt-16 space-y-3">
          {[
            {
              icon: '◈',
              title: 'AIがダッシュボードを自動生成',
              desc: '目標・リズム・記録したい項目を伝えるだけで最適なウィジェット構成を提案',
            },
            {
              icon: '◉',
              title: '5種類のトラッキングウィジェット',
              desc: 'ムード・数値・習慣チェック・進捗・メモ — すべての記録スタイルに対応',
            },
            {
              icon: '◎',
              title: '7日間のストリーク履歴',
              desc: '継続率と達成傾向を一目で確認。継続モチベーションを維持',
            },
          ].map((f) => (
            <div key={f.title} className="card p-4 flex gap-4 items-start animate-fade-in">
              <span className="text-lg mt-0.5 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{f.icon}</span>
              <div>
                <p className="text-sm font-medium mb-1">{f.title}</p>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>{f.desc}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Pricing teaser */}
        <div className="mt-10 card p-5">
          <p className="label-base mb-4">料金プラン</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="p-3" style={{ border: '1px solid var(--border)', borderRadius: 4 }}>
              <p className="text-xs font-medium mb-1">Free</p>
              <p className="text-xl font-light mb-2">¥0</p>
              <ul className="space-y-1">
                {['1ダッシュボード', '3ウィジェット', '7日履歴'].map(item => (
                  <li key={item} className="text-xs" style={{ color: 'var(--text-muted)' }}>— {item}</li>
                ))}
              </ul>
            </div>
            <div className="p-3" style={{ border: '1px solid var(--accent)', borderRadius: 4 }}>
              <p className="text-xs font-medium mb-1">Pro</p>
              <p className="text-xl font-light mb-2">¥480<span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>/月</span></p>
              <ul className="space-y-1">
                {['無制限ダッシュボード', '無制限ウィジェット', '全履歴'].map(item => (
                  <li key={item} className="text-xs" style={{ color: 'var(--text-muted)' }}>— {item}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-6 px-4 text-center" style={{ borderTop: '1px solid var(--border)' }}>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          © 2026 My Routine Builder
        </p>
      </footer>
    </main>
  );
}
