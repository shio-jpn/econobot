'use client';

import { useState } from 'react';
import type { RecordValue } from '@/types';

interface ProgressWidgetProps {
  label: string;
  value?: RecordValue;
  onChange: (value: RecordValue) => void;
}

export default function ProgressWidget({ label, value, onChange }: ProgressWidgetProps) {
  const [percent, setPercent] = useState<number>(value?.percent ?? 0);

  const handleChange = (val: number) => {
    setPercent(val);
    onChange({ percent: val });
  };

  const handleQuickSet = (v: number) => handleChange(v);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="label-base">{label}</p>
        <span
          className="text-2xl font-light"
          style={{ color: 'var(--accent)', fontVariantNumeric: 'tabular-nums' }}
        >
          {percent}%
        </span>
      </div>

      {/* Progress bar display */}
      <div
        className="mb-4"
        style={{
          height: 6,
          backgroundColor: 'var(--border)',
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${percent}%`,
            height: '100%',
            backgroundColor: 'var(--accent)',
            borderRadius: 3,
            transition: 'width 0.15s ease',
          }}
        />
      </div>

      {/* Slider */}
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={percent}
        onChange={(e) => handleChange(parseInt(e.target.value))}
        className="w-full mb-4"
      />

      {/* Quick set buttons */}
      <div className="flex gap-2">
        {[0, 25, 50, 75, 100].map((v) => (
          <button
            key={v}
            onClick={() => handleQuickSet(v)}
            className="flex-1 py-1 text-xs rounded transition-all"
            style={{
              border: `1px solid ${percent === v ? 'var(--accent)' : 'var(--border)'}`,
              backgroundColor: percent === v ? 'var(--bg-hover)' : 'transparent',
              color: percent === v ? 'var(--text)' : 'var(--text-muted)',
            }}
          >
            {v}%
          </button>
        ))}
      </div>
    </div>
  );
}
