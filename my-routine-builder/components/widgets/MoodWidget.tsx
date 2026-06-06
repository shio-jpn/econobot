'use client';

import { useState } from 'react';
import type { RecordValue } from '@/types';

interface MoodWidgetProps {
  value?: RecordValue;
  onChange: (value: RecordValue) => void;
}

const MOODS = [
  { rating: 1, emoji: '😞', label: '最悪' },
  { rating: 2, emoji: '😕', label: '悪い' },
  { rating: 3, emoji: '😐', label: '普通' },
  { rating: 4, emoji: '😊', label: '良い' },
  { rating: 5, emoji: '😄', label: '最高' },
];

export default function MoodWidget({ value, onChange }: MoodWidgetProps) {
  const [selected, setSelected] = useState<number>(value?.rating ?? 0);

  const handleSelect = (rating: number) => {
    setSelected(rating);
    onChange({ rating });
  };

  return (
    <div>
      <p className="label-base mb-4">今日の気分は？</p>
      <div className="flex justify-between gap-2">
        {MOODS.map(({ rating, emoji, label }) => (
          <button
            key={rating}
            onClick={() => handleSelect(rating)}
            className="flex flex-col items-center gap-1 flex-1 py-3 rounded transition-all"
            style={{
              border: `1px solid ${selected === rating ? 'var(--accent)' : 'var(--border)'}`,
              backgroundColor: selected === rating ? 'var(--bg-hover)' : 'transparent',
              transform: selected === rating ? 'scale(1.05)' : 'scale(1)',
            }}
          >
            <span className="text-2xl">{emoji}</span>
            <span
              className="text-xs"
              style={{ color: selected === rating ? 'var(--text)' : 'var(--text-muted)' }}
            >
              {label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
