'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase';

const NAV_ITEMS = [
  { href: '/dashboard', label: '今日' },
  { href: '/history', label: '履歴' },
  { href: '/settings', label: '設定' },
];

export default function Header() {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createClient();

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.replace('/');
  };

  return (
    <header
      className="sticky top-0 z-40 w-full"
      style={{
        backgroundColor: 'var(--bg)',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <div
        className="mx-auto px-4 h-12 flex items-center justify-between"
        style={{ maxWidth: 480 }}
      >
        {/* Logo */}
        <Link
          href="/dashboard"
          className="text-xs font-medium tracking-widest uppercase"
          style={{ color: 'var(--text-muted)', textDecoration: 'none' }}
        >
          Routine
        </Link>

        {/* Nav */}
        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map(({ href, label }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className="px-3 py-1 text-xs rounded transition-colors"
                style={{
                  color: active ? 'var(--text)' : 'var(--text-muted)',
                  backgroundColor: active ? 'var(--bg-hover)' : 'transparent',
                  textDecoration: 'none',
                  fontWeight: active ? 500 : 400,
                }}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Sign out */}
        <button
          onClick={handleSignOut}
          className="btn-ghost text-xs px-2 py-1"
          title="ログアウト"
        >
          ↩
        </button>
      </div>
    </header>
  );
}
