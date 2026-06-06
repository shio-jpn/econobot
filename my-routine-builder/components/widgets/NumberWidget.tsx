'use client';

import { useState } from 'react';
import type { RecordValue, WidgetConfig } from '@/types';

interface NumberWidgetProps {
  label: string;
  unit?: string | null;
  config?: WidgetConfig;
  value?: RecordValue;
  onChange: (value: RecordValue) => void;
}

export default function NumberWidget({
  label,
  unit,
  config,
  value,
  onChange,
}: NumberWidgetProps) {
  const step = config?.step ?? 1;
  const min = config?.min ?? 0;
  const max = config?.max ?? 999;

  const [numValue, setNumValue] = useState<string>(
    value?.value !== undefined ? String(value.value) : ''
  );

  const handleChange = (raw: string) => {
    setNumValue(raw);
    const parsed = parseFloat(raw);
    if (!isNaN(parsed)) {
      onChange({ value: parsed });
    }
  };

  const handleIncrement = (delta: number) => {
    const current = parseFloat(numValue) || 0;
    const next = Math.min(max, Math.max(min, parseFloat((current + delta).toFixed(2))));
    setNumValue(String(next));
    onChange({ value: next });
  };

  return (
    <div>
      <p className="label-base mb-4">{label}を入力</p>
      <div className="flex items-center gap-3">
        <button
          onClick={() => handleIncrement(-step)}
          className="btn-secondary w-10 h-10 text-lg font-light"
          style={{ flexShrink: 0 }}
        >
          −
        </button>
        <div className="flex-1 relative">
          <input
            type="number"
            value={numValue}
            onChange={(e) => handleChange(e.target.value)}
            min={min}
            max={max}
            step={step}
            className="input-base text-center text-xl font-light"
            style={{ paddingRight: unit ? 36 : 12 }}
            placeholder="0"
          />
          {unit && (
            <span
              className="absolute right-3 top-1/2 -translate-y-1/2 text-sm"
              style={{ color: 'var(--text-muted)' }}
            >
              {unit}
            </span>
          )}
        </div>
        <button
          onClick={() => handleIncrement(step)}
          className="btn-secondary w-10 h-10 text-lg font-light"
          style={{ flexShrink: 0 }}
        >
          +
        </button>
      </div>
      <p className="text-center text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
        範囲: {min} – {max}{unit ? ` ${unit}` : ''}
      </p>
    </div>
  );
}
