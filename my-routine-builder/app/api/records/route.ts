import { NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase-server';

export async function GET(request: Request) {
  try {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const date = searchParams.get('date') ?? new Date().toISOString().split('T')[0];

    const { data: records, error } = await supabase
      .from('records')
      .select('*')
      .eq('user_id', user.id)
      .eq('date', date);

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ records: records ?? [] });
  } catch (e) {
    console.error('GET /api/records error:', e);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
