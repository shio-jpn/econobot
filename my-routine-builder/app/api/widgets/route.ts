import { NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase-server';
import type { WidgetType, WidgetConfig } from '@/types';
import { FREE_WIDGET_LIMIT } from '@/types';

export async function GET() {
  try {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    // Get user's dashboard
    const { data: dashboard } = await supabase
      .from('dashboards')
      .select('id')
      .eq('user_id', user.id)
      .single();

    if (!dashboard) {
      return NextResponse.json({ widgets: [] });
    }

    const { data: widgets, error } = await supabase
      .from('widgets')
      .select('*')
      .eq('dashboard_id', dashboard.id)
      .order('position');

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ widgets: widgets ?? [] });
  } catch (e) {
    console.error('GET /api/widgets error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body: { type: WidgetType; label: string; icon: string; unit?: string; config?: WidgetConfig } = await request.json();

    // Get user's dashboard
    const { data: dashboard } = await supabase
      .from('dashboards')
      .select('id')
      .eq('user_id', user.id)
      .single();

    if (!dashboard) {
      return NextResponse.json({ error: 'Dashboard not found' }, { status: 404 });
    }

    // Check subscription plan
    const { data: subscription } = await supabase
      .from('subscriptions')
      .select('plan')
      .eq('user_id', user.id)
      .single();

    const plan = subscription?.plan ?? 'free';

    // Check widget count limit for free plan
    if (plan === 'free') {
      const { count } = await supabase
        .from('widgets')
        .select('id', { count: 'exact', head: true })
        .eq('dashboard_id', dashboard.id);

      if ((count ?? 0) >= FREE_WIDGET_LIMIT) {
        return NextResponse.json(
          { error: 'Free plan limit reached. Upgrade to Pro for unlimited widgets.' },
          { status: 403 }
        );
      }
    }

    // Get max position
    const { data: last } = await supabase
      .from('widgets')
      .select('position')
      .eq('dashboard_id', dashboard.id)
      .order('position', { ascending: false })
      .limit(1)
      .single();

    const position = (last?.position ?? -1) + 1;

    const { data: widget, error } = await supabase
      .from('widgets')
      .insert({
        dashboard_id: dashboard.id,
        type: body.type,
        label: body.label,
        icon: body.icon || '📊',
        unit: body.unit || null,
        position,
        config: body.config || {},
      })
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ widget }, { status: 201 });
  } catch (e) {
    console.error('POST /api/widgets error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const widgetId = searchParams.get('id');

    if (!widgetId) {
      return NextResponse.json({ error: 'Widget ID required' }, { status: 400 });
    }

    // Verify ownership via dashboard join
    const { data: widget } = await supabase
      .from('widgets')
      .select('id, dashboard_id, dashboards!inner(user_id)')
      .eq('id', widgetId)
      .single();

    const widgetWithDashboard = widget as unknown as {
      id: string;
      dashboard_id: string;
      dashboards: { user_id: string };
    } | null;

    if (!widgetWithDashboard || widgetWithDashboard.dashboards.user_id !== user.id) {
      return NextResponse.json({ error: 'Widget not found' }, { status: 404 });
    }

    const { error } = await supabase.from('widgets').delete().eq('id', widgetId);

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ success: true });
  } catch (e) {
    console.error('DELETE /api/widgets error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
