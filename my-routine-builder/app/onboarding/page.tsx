'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import type { Metric, RhythmType, Theme, OnboardingData } from '@/types';

// ============================================================
// Step definitions
// ============================================================

const METRICS: { value: Metric; label: string; emoji: string }[] = [
  { value: '健康', label: '健康', emoji: '💪' },
  { value: '睡眠', label: '睡眠', emoji: '😴' },
  { value: 'メンタル', label: 'メンタル', emoji: '🧘' },
  { value: '学習', label: '学習', emoji: '📚' },
  { value: '体重', label: '体重', emoji: '⚖️' },
  { value: '自由', label: '自由', emoji: '✨' },
];

const RHYTHMS: { value: RhythmType; label: string }[] = [
  { value: '朝型', label: '朝型 — 早起きが得意' },
  { value: '夜型', label: '夜型 — 夜に集中できる' },
  { value: '不規則', label: '不規則 — 日によってバラバラ' },
];

const TRACK_ITEMS = [
  '睡眠時間', '体重', '運動', '水分摂取', '気分・ムード', 'メモ・日記',
];

const THEMES: { value: Theme; label: string; desc: string }[] = [
  { value: 'dark', label: 'ダーク', desc: 'モノクロ・シャープ' },
  { value: 'light', label: 'ライト', desc: 'クリーン・明るい' },
  { value: 'sage', label: 'セージ', desc: 'ナチュラル・グリーン' },
];

const AI_MESSAGES: Record<number, string> = {
  1: 'こんにちは！いちばん変えたいことは何ですか？',
  2: '1日のリズムはどちらですか？',
  3: '毎日記録したい項目を選んでください（複数可）。',
  4: '達成したい目標があれば教えてください。（スキップ可）',
  5: 'ダッシュボードのテーマを選んでください。',
};

type Message = { role: 'ai' | 'user'; text: string };

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [messages, setMessages] = useState<Message[]>([
    { role: 'ai', text: AI_MESSAGES[1] },
  ]);
  const [data, setData] = useState<Partial<OnboardingData>>({});
  const [goalText, setGoalText] = useState('');
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const addMessage = (role: 'ai' | 'user', text: string) => {
    setMessages((prev) => [...prev, { role, text }]);
  };

  const advanceStep = (userText: string, newData: Partial<OnboardingData>) => {
    addMessage('user', userText);
    const nextStep = step + 1;
    setData((prev) => ({ ...prev, ...newData }));

    if (nextStep <= 5) {
      setTimeout(() => {
        addMessage('ai', AI_MESSAGES[nextStep as keyof typeof AI_MESSAGES]);
        setStep(nextStep as 1 | 2 | 3 | 4 | 5);
      }, 300);
    } else {
      // Trigger submit
      setTimeout(() => {
        addMessage('ai', 'ダッシュボードを作成しています...');
        handleSubmit({ ...data, ...newData } as OnboardingData);
      }, 300);
    }
  };

  const handleSubmit = async (finalData: OnboardingData) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/onboarding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(finalData),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Failed to create dashboard');
      }
      router.replace('/dashboard');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'エラーが発生しました');
      setLoading(false);
    }
  };

  const toggleItem = (item: string) => {
    setSelectedItems((prev) =>
      prev.includes(item) ? prev.filter((i) => i !== item) : [...prev, item]
    );
  };

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ backgroundColor: 'var(--bg)', maxWidth: 480, margin: '0 auto' }}
    >
      {/* Header */}
      <div
        className="px-4 py-4 flex items-center justify-between"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <span className="label-base">オンボーディング</span>
        <div className="flex gap-1">
          {[1, 2, 3, 4, 5].map((s) => (
            <div
              key={s}
              style={{
                width: 20,
                height: 3,
                borderRadius: 2,
                backgroundColor: s <= step ? 'var(--accent)' : 'var(--border)',
                transition: 'background-color 0.2s',
              }}
            />
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex animate-fade-in ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'ai' && (
              <span
                className="w-6 h-6 flex items-center justify-center text-xs flex-shrink-0 mr-2 mt-1"
                style={{
                  border: '1px solid var(--border)',
                  borderRadius: '50%',
                  color: 'var(--text-muted)',
                }}
              >
                AI
              </span>
            )}
            <div className={msg.role === 'ai' ? 'chat-bubble-ai' : 'chat-bubble-user'}>
              {msg.text}
            </div>
          </div>
        ))}

        {/* Step input UI */}
        <div className="mt-6 animate-slide-up">
          {step === 1 && !data.metric && (
            <div className="grid grid-cols-3 gap-2">
              {METRICS.map((m) => (
                <button
                  key={m.value}
                  onClick={() => advanceStep(`${m.emoji} ${m.label}`, { metric: m.value })}
                  className="card-hover p-3 text-center"
                >
                  <div className="text-xl mb-1">{m.emoji}</div>
                  <div className="text-xs font-medium">{m.label}</div>
                </button>
              ))}
            </div>
          )}

          {step === 2 && !data.rhythm && (
            <div className="space-y-2">
              {RHYTHMS.map((r) => (
                <button
                  key={r.value}
                  onClick={() => advanceStep(r.label, { rhythm: r.value })}
                  className="card-hover p-4 w-full text-left text-sm"
                >
                  {r.label}
                </button>
              ))}
            </div>
          )}

          {step === 3 && !data.trackItems && (
            <div>
              <div className="grid grid-cols-2 gap-2 mb-4">
                {TRACK_ITEMS.map((item) => (
                  <button
                    key={item}
                    onClick={() => toggleItem(item)}
                    className="card p-3 text-left text-xs flex items-center gap-2 transition-all"
                    style={{
                      borderColor: selectedItems.includes(item) ? 'var(--accent)' : 'var(--border)',
                      backgroundColor: selectedItems.includes(item) ? 'var(--bg-hover)' : 'var(--bg-card)',
                    }}
                  >
                    <span
                      style={{
                        width: 12,
                        height: 12,
                        border: `1px solid ${selectedItems.includes(item) ? 'var(--accent)' : 'var(--border)'}`,
                        borderRadius: 2,
                        backgroundColor: selectedItems.includes(item) ? 'var(--accent)' : 'transparent',
                        flexShrink: 0,
                      }}
                    />
                    {item}
                  </button>
                ))}
              </div>
              <button
                className="btn-primary w-full"
                disabled={selectedItems.length === 0}
                onClick={() =>
                  advanceStep(selectedItems.join('、'), { trackItems: selectedItems })
                }
              >
                次へ →
              </button>
            </div>
          )}

          {step === 4 && data.trackItems && !data.goal && (
            <div>
              <textarea
                value={goalText}
                onChange={(e) => setGoalText(e.target.value)}
                className="input-base mb-3"
                rows={3}
                placeholder="例: 毎日7時間睡眠を取る、3ヶ月で5kg痩せる..."
              />
              <div className="flex gap-2">
                <button
                  className="btn-secondary flex-1 text-xs"
                  onClick={() => advanceStep('スキップ', { goal: '' })}
                >
                  スキップ
                </button>
                <button
                  className="btn-primary flex-1 text-xs"
                  onClick={() => advanceStep(goalText || 'スキップ', { goal: goalText })}
                >
                  次へ →
                </button>
              </div>
            </div>
          )}

          {step === 5 && data.goal !== undefined && !data.theme && (
            <div className="space-y-2">
              {THEMES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => advanceStep(t.label, { theme: t.value })}
                  className="card-hover p-4 w-full text-left flex items-center justify-between"
                >
                  <div>
                    <p className="text-sm font-medium">{t.label}</p>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{t.desc}</p>
                  </div>
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>→</span>
                </button>
              ))}
            </div>
          )}

          {loading && (
            <div className="text-center py-8">
              <div
                className="inline-block w-6 h-6 border-2 rounded-full"
                style={{
                  borderColor: 'var(--border)',
                  borderTopColor: 'var(--accent)',
                  animation: 'spin 0.8s linear infinite',
                }}
              />
              <p className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>
                ダッシュボードを生成中...
              </p>
            </div>
          )}

          {error && (
            <div
              className="p-3 text-xs rounded"
              style={{ backgroundColor: 'rgba(248, 113, 113, 0.1)', color: 'var(--danger)', border: '1px solid var(--danger)' }}
            >
              {error}
            </div>
          )}
        </div>

        <div ref={bottomRef} />
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
