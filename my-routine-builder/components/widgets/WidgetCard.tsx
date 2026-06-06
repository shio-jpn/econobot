'use client';

import type { WidgetWithRecord } from '@/types';

interface WidgetCardProps {
  widget: WidgetWithRecord;
  onClick: () => void;
}

export default function WidgetCard({ widget, onClick }: WidgetCardProps) {
  const isDone = !!widget.record;

  return (
    <div
      className="card-hover p-4 relative"
      onClick={onClick}
      style={{ cursor: 'pointer' }}
    >
      {/* Done badge */}
      {isDone && (
        <span className="badge-done absolute top-3 right-3">DONE</span>
      )}

      {/* Icon + Label */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">{widget.icon}</span>
        <span className="text-sm font-medium">{widget.label}</span>
      </div>

      {/* Preview of current value */}
      <div
        className="text-xs"
        style={{ color: isDone ? 'var(--text-muted)' : 'var(--text-muted)' }}
      >
        {isDone ? (
          <RecordPreview widget={widget} />
        ) : (
          <span>タップして記録</span>
        )}
      </div>

      {/* Type badge */}
      <div className="mt-3">
        <span
          className="text-xs"
          style={{
            color: 'var(--text-muted)',
            fontSize: 10,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        >
          {widget.type}
          {widget.unit ? ` · ${widget.unit}` : ''}
        </span>
      </div>
    </div>
  );
}

function RecordPreview({ widget }: { widget: WidgetWithRecord }) {
  const val = widget.record?.value;
  if (!val) return null;

  switch (widget.type) {
    case 'mood':
      const moods = ['', '😞', '😕', '😐', '😊', '😄'];
      return <span className="text-base">{moods[val.rating ?? 0]}</span>;

    case 'number':
      return (
        <span>
          {val.value} {widget.unit}
        </span>
      );

    case 'habits': {
      const habits = widget.config?.habits ?? [];
      const checked = val.checked ?? [];
      return (
        <span>
          {checked.length}/{habits.length} 完了
        </span>
      );
    }

    case 'progress':
      return (
        <div className="flex items-center gap-2">
          <div
            style={{
              flex: 1,
              height: 4,
              backgroundColor: 'var(--border)',
              borderRadius: 2,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${val.percent ?? 0}%`,
                height: '100%',
                backgroundColor: 'var(--accent)',
                borderRadius: 2,
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <span>{val.percent}%</span>
        </div>
      );

    case 'memo':
      const text = val.text ?? '';
      return <span>{text.length > 30 ? text.slice(0, 30) + '…' : text}</span>;

    default:
      return null;
  }
}
