import { NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase-server';
import type { OnboardingData, Widget, WidgetType } from '@/types';

interface WidgetDef {
  type: WidgetType;
  label: string;
  icon: string;
  unit: string | null;
  position: number;
  config: Record<string, unknown>;
}

function generateWidgets(data: OnboardingData): WidgetDef[] {
  const widgets: WidgetDef[] = [];
  let pos = 0;

  const addWidget = (def: Omit<WidgetDef, 'position'>) => {
    widgets.push({ ...def, position: pos++ });
  };

  // Base widgets by metric
  switch (data.metric) {
    case '健康':
      addWidget({
        type: 'habits',
        label: '健康習慣',
        icon: '💪',
        unit: null,
        config: { habits: ['運動 30分', '水 2L', '野菜を食べる'] },
      });
      addWidget({ type: 'mood', label: '今日の気分', icon: '😊', unit: null, config: {} });
      break;

    case '睡眠':
      addWidget({
        type: 'number',
        label: '睡眠時間',
        icon: '😴',
        unit: 'h',
        config: { min: 0, max: 12, step: 0.5 },
      });
      addWidget({ type: 'mood', label: '今日の気分', icon: '😊', unit: null, config: {} });
      break;

    case 'メンタル':
      addWidget({ type: 'mood', label: '今日の気分', icon: '🧘', unit: null, config: {} });
      addWidget({ type: 'memo', label: '日記・メモ', icon: '📝', unit: null, config: {} });
      break;

    case '学習':
      addWidget({
        type: 'habits',
        label: '学習習慣',
        icon: '📚',
        unit: null,
        config: { habits: ['読書 30分', '勉強・復習', 'メモを取る'] },
      });
      addWidget({
        type: 'progress',
        label: '目標進捗',
        icon: '🎯',
        unit: null,
        config: { min: 0, max: 100 },
      });
      break;

    case '体重':
      addWidget({
        type: 'number',
        label: '体重',
        icon: '⚖️',
        unit: 'kg',
        config: { min: 30, max: 150, step: 0.1 },
      });
      addWidget({
        type: 'habits',
        label: '運動記録',
        icon: '🏃',
        unit: null,
        config: { habits: ['有酸素運動', '筋トレ', '歩数 8000歩'] },
      });
      break;

    case '自由':
    default:
      addWidget({ type: 'memo', label: '今日のメモ', icon: '✨', unit: null, config: {} });
      addWidget({
        type: 'habits',
        label: '今日のタスク',
        icon: '✅',
        unit: null,
        config: { habits: ['タスク1', 'タスク2', 'タスク3'] },
      });
      break;
  }

  // Additional widgets from trackItems (avoid duplicates)
  const existingTypes = new Set(widgets.map((w) => w.type));

  for (const item of data.trackItems) {
    if (widgets.length >= 3) break; // Free plan limit (server enforces, but be nice)

    switch (item) {
      case '睡眠時間':
        if (!widgets.find((w) => w.label === '睡眠時間')) {
          addWidget({ type: 'number', label: '睡眠時間', icon: '😴', unit: 'h', config: { min: 0, max: 12, step: 0.5 } });
        }
        break;
      case '体重':
        if (!widgets.find((w) => w.label === '体重')) {
          addWidget({ type: 'number', label: '体重', icon: '⚖️', unit: 'kg', config: { min: 30, max: 150, step: 0.1 } });
        }
        break;
      case '気分・ムード':
        if (!existingTypes.has('mood')) {
          addWidget({ type: 'mood', label: '今日の気分', icon: '😊', unit: null, config: {} });
          existingTypes.add('mood');
        }
        break;
      case 'メモ・日記':
        if (!existingTypes.has('memo')) {
          addWidget({ type: 'memo', label: '日記', icon: '📝', unit: null, config: {} });
          existingTypes.add('memo');
        }
        break;
    }
  }

  // Safety cap; free plan limit (3) is enforced in the POST handler
  return widgets.slice(0, 10);
}

export async function POST(request: Request) {
  try {
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body: OnboardingData = await request.json();
    const { metric, rhythm, trackItems, goal, theme } = body;

    if (!metric || !rhythm || !trackItems || !theme) {
      return NextResponse.json({ error: 'Missing required fields' }, { status: 400 });
    }

    // Check if user already has a dashboard
    const { data: existing } = await supabase
      .from('dashboards')
      .select('id')
      .eq('user_id', user.id)
      .single();

    if (existing) {
      return NextResponse.json({ error: 'Dashboard already exists' }, { status: 409 });
    }

    // Check subscription for widget limit
    const { data: subscription } = await supabase
      .from('subscriptions')
      .select('plan')
      .eq('user_id', user.id)
      .single();

    const plan = subscription?.plan ?? 'free';

    // Create dashboard
    const { data: dashboard, error: dashError } = await supabase
      .from('dashboards')
      .insert({
        user_id: user.id,
        name: `${metric}ダッシュボード`,
        theme,
        goal: goal || null,
        metric,
      })
      .select()
      .single();

    if (dashError || !dashboard) {
      console.error('Dashboard error:', dashError);
      return NextResponse.json({ error: 'Failed to create dashboard' }, { status: 500 });
    }

    // Generate and insert widgets
    const widgetDefs = generateWidgets(body);
    const widgetsToInsert = plan === 'free' ? widgetDefs.slice(0, 3) : widgetDefs;

    const { data: widgets, error: widgetsError } = await supabase
      .from('widgets')
      .insert(
        widgetsToInsert.map((w) => ({
          dashboard_id: dashboard.id,
          type: w.type,
          label: w.label,
          icon: w.icon,
          unit: w.unit,
          position: w.position,
          config: w.config,
        }))
      )
      .select();

    if (widgetsError) {
      console.error('Widgets error:', widgetsError);
      // Rollback dashboard
      await supabase.from('dashboards').delete().eq('id', dashboard.id);
      return NextResponse.json({ error: 'Failed to create widgets' }, { status: 500 });
    }

    // Ensure subscription row exists
    const { error: subError } = await supabase
      .from('subscriptions')
      .upsert({ user_id: user.id, plan: 'free' }, { onConflict: 'user_id' });

    if (subError) {
      console.warn('Subscription upsert warning:', subError);
    }

    return NextResponse.json({ dashboard, widgets } as { dashboard: typeof dashboard; widgets: Widget[] });
  } catch (e) {
    console.error('Onboarding error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
