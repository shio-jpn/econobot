-- ============================================================
-- My Routine Builder - Initial Database Schema
-- ============================================================

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- ============================================================
-- DASHBOARDS
-- ============================================================

create table if not exists dashboards (
  id            uuid primary key default uuid_generate_v4(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  name          text not null,
  theme         text not null default 'dark'
                  check (theme in ('dark', 'light', 'sage')),
  goal          text,
  metric        text
                  check (metric in ('健康', '睡眠', 'メンタル', '学習', '体重', '自由')),
  created_at    timestamptz not null default now()
);

create index if not exists dashboards_user_id_idx on dashboards(user_id);

-- RLS
alter table dashboards enable row level security;

create policy "Users can view own dashboards"
  on dashboards for select
  using (auth.uid() = user_id);

create policy "Users can insert own dashboards"
  on dashboards for insert
  with check (auth.uid() = user_id);

create policy "Users can update own dashboards"
  on dashboards for update
  using (auth.uid() = user_id);

create policy "Users can delete own dashboards"
  on dashboards for delete
  using (auth.uid() = user_id);

-- ============================================================
-- WIDGETS
-- ============================================================

create table if not exists widgets (
  id              uuid primary key default uuid_generate_v4(),
  dashboard_id    uuid not null references dashboards(id) on delete cascade,
  type            text not null
                    check (type in ('mood', 'number', 'habits', 'progress', 'memo')),
  label           text not null,
  icon            text not null default '📊',
  unit            text,
  position        integer not null default 0,
  config          jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

create index if not exists widgets_dashboard_id_idx on widgets(dashboard_id);
create index if not exists widgets_position_idx on widgets(dashboard_id, position);

-- RLS
alter table widgets enable row level security;

create policy "Users can view own widgets"
  on widgets for select
  using (
    exists (
      select 1 from dashboards
      where dashboards.id = widgets.dashboard_id
        and dashboards.user_id = auth.uid()
    )
  );

create policy "Users can insert own widgets"
  on widgets for insert
  with check (
    exists (
      select 1 from dashboards
      where dashboards.id = widgets.dashboard_id
        and dashboards.user_id = auth.uid()
    )
  );

create policy "Users can update own widgets"
  on widgets for update
  using (
    exists (
      select 1 from dashboards
      where dashboards.id = widgets.dashboard_id
        and dashboards.user_id = auth.uid()
    )
  );

create policy "Users can delete own widgets"
  on widgets for delete
  using (
    exists (
      select 1 from dashboards
      where dashboards.id = widgets.dashboard_id
        and dashboards.user_id = auth.uid()
    )
  );

-- ============================================================
-- RECORDS
-- ============================================================

create table if not exists records (
  id          uuid primary key default uuid_generate_v4(),
  widget_id   uuid not null references widgets(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  date        date not null,
  value       jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  -- One record per widget per user per day
  unique (widget_id, user_id, date)
);

create index if not exists records_user_date_idx on records(user_id, date);
create index if not exists records_widget_id_idx on records(widget_id);
create index if not exists records_date_idx on records(date);

-- RLS
alter table records enable row level security;

create policy "Users can view own records"
  on records for select
  using (auth.uid() = user_id);

create policy "Users can insert own records"
  on records for insert
  with check (auth.uid() = user_id);

create policy "Users can update own records"
  on records for update
  using (auth.uid() = user_id);

create policy "Users can delete own records"
  on records for delete
  using (auth.uid() = user_id);

-- Auto-update updated_at trigger
create or replace function update_updated_at_column()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger records_updated_at
  before update on records
  for each row
  execute function update_updated_at_column();

-- ============================================================
-- SUBSCRIPTIONS
-- ============================================================

create table if not exists subscriptions (
  id                      uuid primary key default uuid_generate_v4(),
  user_id                 uuid not null references auth.users(id) on delete cascade,
  stripe_customer_id      text,
  stripe_subscription_id  text,
  plan                    text not null default 'free'
                            check (plan in ('free', 'pro')),
  current_period_end      timestamptz,
  created_at              timestamptz not null default now(),

  unique (user_id)
);

create index if not exists subscriptions_user_id_idx on subscriptions(user_id);
create index if not exists subscriptions_stripe_customer_idx on subscriptions(stripe_customer_id);

-- RLS
alter table subscriptions enable row level security;

create policy "Users can view own subscriptions"
  on subscriptions for select
  using (auth.uid() = user_id);

create policy "Users can insert own subscriptions"
  on subscriptions for insert
  with check (auth.uid() = user_id);

create policy "Users can update own subscriptions"
  on subscriptions for update
  using (auth.uid() = user_id);

-- Allow service role to manage subscriptions (for Stripe webhook)
-- Note: service role bypasses RLS by default

-- ============================================================
-- HELPER VIEWS (optional, for convenience)
-- ============================================================

-- Dashboard with widget count
create or replace view dashboard_summary as
  select
    d.*,
    count(w.id) as widget_count
  from dashboards d
  left join widgets w on w.dashboard_id = d.id
  group by d.id;
