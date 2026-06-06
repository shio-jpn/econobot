'use client';

import { useState } from 'react';
import type { RecordValue, WidgetConfig } from '@/types';

interface HabitsWidgetProps {
  config?: WidgetConfig;
  value?: RecordValue;
  onChange: (value: RecordValue) => void;
}

export default function HabitsWidget({ config, value, onChange }: HabitsWidgetProps) {
  const habits = config?.habits ?? [];
  const [checked, setChecked] = useState<string[]>(value?.checked ?? []);

  const toggle = (habit: string) => {
    const next = checked.includes(habit)
      ? checked.filter((h) => h !== habit)
      : [...checked, habit];
    setChecked(next);
    onChange({ checked: next });
  };

  const allDone = habits.length > 0 && checked.length === habits.length;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="label-base">習慣チェック</p>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {checked.length}/{habits.length}
        </span>
      </div>

      {habits.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          習慣が設定されていません
        </p>
      ) : (
        <div className="space-y-2">
          {habits.map((habit) => {
            const isChecked = checked.includes(habit);
            return (
              <label
                key={habit}
                className="flex items-center gap-3 py-2 px-3 rounded cursor-pointer transition-colors"
                style={{
                  border: `1px solid ${isChecked ? 'var(--accent)' : 'var(--border)'}`,
                  backgroundColor: isChecked ? 'var(--bg-hover)' : 'transparent',
                }}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggle(habit)}
                  className="flex-shrink-0"
                />
                <span
                  className="text-sm"
                  style={{
                    textDecoration: isChecked ? 'line-through' : 'none',
                    color: isChecked ? 'var(--text-muted)' : 'var(--text)',
                  }}
                >
                  {habit}
                </span>
              </label>
            );
          })}
        </div>
      )}

      {allDone && (
        <div
          className="mt-4 py-2 px-3 text-center text-xs font-medium rounded animate-fade-in"
          style={{
            backgroundColor: 'rgba(74, 222, 128, 0.1)',
            color: 'var(--success)',
            border: '1px solid var(--success)',
          }}
        >
          すべて完了！
        </div>
      )}
    </div>
  );
}
