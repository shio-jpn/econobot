'use client';

import { useState, useEffect } from 'react';
import type { WidgetWithRecord, RecordValue } from '@/types';
import MoodWidget from './widgets/MoodWidget';
import NumberWidget from './widgets/NumberWidget';
import HabitsWidget from './widgets/HabitsWidget';
import ProgressWidget from './widgets/ProgressWidget';
import MemoWidget from './widgets/MemoWidget';

interface RecordModalProps {
  widget: WidgetWithRecord;
  date: string;
  onClose: () => void;
  onSaved: (widgetId: string, value: RecordValue) => void;
}

export default function RecordModal({ widget, date, onClose, onSaved }: RecordModalProps) {
  const [currentValue, setCurrentValue] = useState<RecordValue>(
    widget.record?.value ?? {}
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Close on backdrop click
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`/api/records/${widget.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date, value: currentValue }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Save failed');
      }

      onSaved(widget.id, currentValue);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'エラーが発生しました');
    } finally {
      setSaving(false);
    }
  };

  const isValid = () => {
    switch (widget.type) {
      case 'mood':
        return (currentValue.rating ?? 0) > 0;
      case 'number':
        return currentValue.value !== undefined && !isNaN(currentValue.value);
      case 'habits':
        return true; // Can save with 0 checked
      case 'progress':
        return currentValue.percent !== undefined;
      case 'memo':
        return (currentValue.text ?? '').trim().length > 0;
      default:
        return false;
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center"
      style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
      onClick={handleBackdropClick}
    >
      <div
        className="w-full animate-slide-up"
        style={{
          maxWidth: 480,
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '8px 8px 0 0',
          padding: '0 0 env(safe-area-inset-bottom, 0)',
        }}
      >
        {/* Modal header */}
        <div
          className="flex items-center justify-between px-4 py-4"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2">
            <span className="text-lg">{widget.icon}</span>
            <span className="text-sm font-medium">{widget.label}</span>
          </div>
          <button onClick={onClose} className="btn-ghost text-base w-8 h-8 flex items-center justify-center">
            ×
          </button>
        </div>

        {/* Widget input */}
        <div className="px-4 py-5">
          {widget.type === 'mood' && (
            <MoodWidget value={currentValue} onChange={setCurrentValue} />
          )}
          {widget.type === 'number' && (
            <NumberWidget
              label={widget.label}
              unit={widget.unit}
              config={widget.config}
              value={currentValue}
              onChange={setCurrentValue}
            />
          )}
          {widget.type === 'habits' && (
            <HabitsWidget
              config={widget.config}
              value={currentValue}
              onChange={setCurrentValue}
            />
          )}
          {widget.type === 'progress' && (
            <ProgressWidget
              label={widget.label}
              value={currentValue}
              onChange={setCurrentValue}
            />
          )}
          {widget.type === 'memo' && (
            <MemoWidget
              label={widget.label}
              value={currentValue}
              onChange={setCurrentValue}
            />
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="mx-4 mb-3 p-2 text-xs rounded" style={{ color: 'var(--danger)', backgroundColor: 'rgba(248, 113, 113, 0.1)', border: '1px solid var(--danger)' }}>
            {error}
          </div>
        )}

        {/* Footer */}
        <div className="px-4 pb-5 flex gap-3">
          <button onClick={onClose} className="btn-secondary flex-1">
            キャンセル
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !isValid()}
            className="btn-primary flex-1"
          >
            {saving ? '保存中...' : '記録する'}
          </button>
        </div>
      </div>
    </div>
  );
}
