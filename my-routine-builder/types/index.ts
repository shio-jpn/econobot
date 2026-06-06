// ============================================================
// Core Domain Types
// ============================================================

export type Theme = 'dark' | 'light' | 'sage';

export type WidgetType = 'mood' | 'number' | 'habits' | 'progress' | 'memo';

export type Plan = 'free' | 'pro';

export type Metric =
  | '健康'
  | '睡眠'
  | 'メンタル'
  | '学習'
  | '体重'
  | '自由';

export type RhythmType = '朝型' | '夜型' | '不規則';

// ============================================================
// Database Row Types
// ============================================================

export interface Dashboard {
  id: string;
  user_id: string;
  name: string;
  theme: Theme;
  goal: string | null;
  metric: Metric | null;
  created_at: string;
}

export interface WidgetConfig {
  habits?: string[];        // for habits widget: list of habit labels
  min?: number;             // for number/progress: min value
  max?: number;             // for number/progress: max value
  step?: number;            // for number: step value
}

export interface Widget {
  id: string;
  dashboard_id: string;
  type: WidgetType;
  label: string;
  icon: string;
  unit: string | null;
  position: number;
  config: WidgetConfig;
}

export interface RecordValue {
  // mood: 1-5
  rating?: number;
  // number: decimal
  value?: number;
  // habits: checked indices or labels
  checked?: string[];
  // progress: 0-100
  percent?: number;
  // memo: text
  text?: string;
}

export interface DailyRecord {
  id: string;
  widget_id: string;
  user_id: string;
  date: string; // YYYY-MM-DD
  value: RecordValue;
  created_at: string;
  updated_at: string;
}

export interface Subscription {
  id: string;
  user_id: string;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  plan: Plan;
  current_period_end: string | null;
  created_at: string;
}

// ============================================================
// Onboarding Types
// ============================================================

export interface OnboardingData {
  metric: Metric;
  rhythm: RhythmType;
  trackItems: string[];
  goal?: string;
  theme: Theme;
}

export type OnboardingStep = 1 | 2 | 3 | 4 | 5;

// ============================================================
// API Response Types
// ============================================================

export interface ApiResponse<T = unknown> {
  data?: T;
  error?: string;
}

export interface OnboardingResponse {
  dashboard: Dashboard;
  widgets: Widget[];
}

export interface RecordsResponse {
  records: DailyRecord[];
}

// ============================================================
// UI / Component Types
// ============================================================

export interface WidgetWithRecord extends Widget {
  record?: DailyRecord;
}

export interface DashboardWithWidgets extends Dashboard {
  widgets: WidgetWithRecord[];
}

export interface HistoryEntry {
  date: string; // YYYY-MM-DD
  records: DailyRecord[];
  completionRate: number; // 0-100
}

export interface StreakData {
  currentStreak: number;
  longestStreak: number;
  last7Days: HistoryEntry[];
  totalRecorded: number;
}

// ============================================================
// Freemium Limits
// ============================================================

export const FREE_WIDGET_LIMIT = 3;
export const FREE_DASHBOARD_LIMIT = 1;
export const PRO_PRICE_JPY = 480;
