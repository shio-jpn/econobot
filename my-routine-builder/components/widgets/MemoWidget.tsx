'use client';

import { useState } from 'react';
import type { RecordValue } from '@/types';

interface MemoWidgetProps {
  label: string;
  value?: RecordValue;
  onChange: (value: RecordValue) => void;
}

export default function MemoWidget({ label, value, onChange }: MemoWidgetProps) {
  const [text, setText] = useState<string>(value?.text ?? '');

  const handleChange = (val: string) => {
    setText(val);
    onChange({ text: val });
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="label-base">{label}</p>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {text.length} 文字
        </span>
      </div>
      <textarea
        value={text}
        onChange={(e) => handleChange(e.target.value)}
        className="input-base"
        rows={5}
        placeholder="今日の記録を書いてください..."
        style={{ resize: 'vertical', minHeight: 100 }}
      />
    </div>
  );
}
