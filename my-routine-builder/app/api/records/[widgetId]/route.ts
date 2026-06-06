import { NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase-server';
import type { RecordValue } from '@/types';

interface Params {
  params: Promise<{ widgetId: string }>;
}

export async function POST(request: Request, { params }: Params) {
  try {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { widgetId } = await params;
    const body: { date: string; value: RecordValue } = await request.json();
    const { date, value } = body;

    if (!date || value === undefined) {
      return NextResponse.json({ error: 'date and value are required' }, { status: 400 });
    }

    // Verify the widget belongs to the user's dashboard
    const { data: widget, error: widgetError } = await supabase
      .from('widgets')
      .select('id, dashboard_id, dashboards!inner(user_id)')
      .eq('id', widgetId)
      .single();

    if (widgetError || !widget) {
      return NextResponse.json({ error: 'Widget not found' }, { status: 404 });
    }

    // Type assertion for the join
    const widgetWithDashboard = widget as unknown as {
      id: string;
      dashboard_id: string;
      dashboards: { user_id: string };
    };

    if (widgetWithDashboard.dashboards.user_id !== user.id) {
      return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
    }

    // Upsert record
    const { data: record, error } = await supabase
      .from('records')
      .upsert(
        {
          widget_id: widgetId,
          user_id: user.id,
          date,
          value,
          updated_at: new Date().toISOString(),
        },
        { onConflict: 'widget_id,user_id,date' }
      )
      .select()
      .single();

    if (error) {
      console.error('Upsert record error:', error);
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ record });
  } catch (e) {
    console.error('POST /api/records/[widgetId] error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
