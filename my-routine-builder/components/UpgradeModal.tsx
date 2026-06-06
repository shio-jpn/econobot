'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

interface UpgradeModalProps {
  onClose: () => void;
}

export default function UpgradeModal({ onClose }: UpgradeModalProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  const handleUpgrade = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/stripe/checkout', { method: 'POST' });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      }
    } catch {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ backgroundColor: 'rgba(0,0,0,0.75)' }}
      onClick={handleBackdropClick}
    >
      <div
        className="w-full animate-slide-up"
        style={{
          maxWidth: 400,
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 8,
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
          <span className="text-sm font-medium">Pro にアップグレード</span>
          <button onClick={onClose} className="btn-ghost text-base w-8 h-8 flex items-center justify-center">
            ×
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-5">
          <div className="text-center mb-6">
            <p className="text-3xl font-light mb-1">
              ¥480
              <span className="text-sm font-normal" style={{ color: 'var(--text-muted)' }}>
                /月
              </span>
            </p>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              いつでもキャンセル可能
            </p>
          </div>

          <ul className="space-y-3 mb-6">
            {[
              ['無制限ダッシュボード', 'Freeは1つのみ'],
              ['無制限ウィジェット', 'Freeは3つまで'],
              ['全期間の履歴', 'Freeは7日のみ'],
              ['カスタムテーマ', '全3テーマ使用可'],
            ].map(([feature, desc]) => (
              <li key={feature} className="flex items-start gap-3">
                <span className="text-sm mt-0.5" style={{ color: 'var(--success)' }}>✓</span>
                <div>
                  <p className="text-sm font-medium">{feature}</p>
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{desc}</p>
                </div>
              </li>
            ))}
          </ul>

          <button
            onClick={handleUpgrade}
            disabled={loading}
            className="btn-primary w-full py-3 text-sm"
          >
            {loading ? '処理中...' : 'Proにアップグレード →'}
          </button>

          <button
            onClick={onClose}
            className="btn-ghost w-full text-xs mt-2"
          >
            後で
          </button>
        </div>
      </div>
    </div>
  );
}
