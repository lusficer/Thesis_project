'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { dssAPI } from '@/lib/api';
import {
  ResponsiveContainer,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  BarChart,
  Bar,
  Cell,
  Legend,
  PieChart,
  Pie,
} from 'recharts';

interface PortfolioItem {
  product_id: number;
  product_name: string;
  category: string;
  current_stock: number;
  current_price: number | null;
  avg_daily_forecast: number | null;
  reorder_point: number | null;
  safety_stock: number | null;
  stockout_probability: number | null;   // 0-100
  velocity_ratio: number | null;
  recommended_action: 'ORDER_NOW' | 'LOW_STOCK' | 'HOLD' | null;
  price_change_pct: number | null;
  status: 'ok' | 'insufficient_data' | 'error';
}

interface PortfolioMeta {
  last_computed_at: string | null;   // ISO
  products_cached: number;
  total_products: number;
  model_version: string;
}

interface CategoryRollup {
  category: string;
  product_count: number;
  avg_mae: number;
  avg_rmse: number;
  avg_under_forecast_pct: number;
  avg_dss_service_level: number;
  avg_naive_service_level: number;
  at_risk_count: number;
  products: {
    product_id: number;
    product_name: string;
    mae: number | null;
    dss_service_level: number | null;
    naive_service_level: number | null;
  }[];
}

interface ModelPerformanceProduct {
  product_id: number;
  product_name: string;
  category: string;
  mae: number;
  rmse: number;
  mape: number;
  under_forecast_pct: number;
  over_forecast_pct: number;
  dss_service_level: number;
  naive_service_level: number;
  dss_stockout_days: number;
  naive_stockout_days: number;
}

interface ModelPerformance {
  products: ModelPerformanceProduct[];
  summary: {
    avg_mae: number;
    avg_under_forecast_pct: number;
    median_under_forecast_pct: number;
    products_above_safety_threshold: number;
    safety_threshold: number;
  };
}

const C = {
  bg:       '#f8f9fb',
  surface:  '#ffffff',
  border:   '#e8eaef',
  accent:   '#6366f1',
  accentLt: '#818cf8',
  success:  '#059669',
  warn:     '#d97706',
  danger:   '#dc2626',
  text:     '#1a1a2e',
  muted:    '#64748b',
  subtle:   '#94a3b8',
};

const Card = ({ children, style = {} }: any) => (
  <div style={{
    background: C.surface, border: `1px solid ${C.border}`,
    borderRadius: 14, padding: 24, ...style,
  }}>{children}</div>
);

// Row tint by action
const actionTint: Record<string, string> = {
  ORDER_NOW: '#fee2e2',   // light red
  LOW_STOCK: '#fef3c7',   // light orange
  HOLD:      'transparent',
};

const actionPillStyle = (action: string | null): React.CSSProperties => {
  const map: Record<string, [string, string]> = {
    ORDER_NOW: [C.danger, '#fee2e222'],
    LOW_STOCK: [C.warn, '#fef3c722'],
    HOLD: [C.success, '#d1fae522'],
  };
  const [color, bg] = map[action ?? ''] ?? [C.muted, '#64748b22'];
  return {
    display: 'inline-flex', alignItems: 'center',
    padding: '3px 10px', borderRadius: 20,
    fontSize: 11, fontWeight: 700, letterSpacing: '0.04em',
    color, background: bg, border: `1px solid ${color}33`,
  };
};

const velocityLabel = (ratio: number | null): { text: string; color: string } => {
  if (ratio == null) return { text: '—', color: C.subtle };
  if (ratio > 1.2) return { text: 'Fast', color: C.success };
  if (ratio < 0.8) return { text: 'Slow', color: C.warn };
  return { text: 'Normal', color: C.muted };
};

const stockoutColor = (p: number | null): string => {
  if (p == null) return C.subtle;
  if (p > 50) return C.danger;
  if (p >= 30) return C.warn;
  return C.success;
};

const formatNum = (n: number | null, digits = 0): string =>
  n == null ? '—' : n.toFixed(digits);

const formatPct = (n: number | null): string =>
  n == null ? '—' : `${n.toFixed(1)}%`;

const formatSigned = (n: number | null): string => {
  if (n == null) return '—';
  if (n === 0) return '0%';
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%';
};

function timeAgo(iso: string | null): string {
  if (!iso) return 'never';
  const then = new Date(iso).getTime();
  const now  = Date.now();
  const diff = Math.max(0, now - then);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? '' : 's'} ago`;
  const days = Math.floor(hrs / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

function renderMarkdown(md: string): string {
  return md
    .replace(/^### (.+)$/gm, '<h3 style="margin:28px 0 12px;font-size:24px;font-weight:700;line-height:1.35">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 style="margin:32px 0 14px;font-size:28px;font-weight:700;line-height:1.3">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 style="margin:0 0 20px;font-size:34px;font-weight:800;line-height:1.2">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.+)$/gm, '<div style="padding-left:24px;margin:8px 0">• $1</div>')
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>');
}

export default function StatisticsPage() {
  const router = useRouter();

  const [items, setItems]           = useState<PortfolioItem[]>([]);
  const [meta, setMeta]             = useState<PortfolioMeta | null>(null);
  const [rollup, setRollup]         = useState<CategoryRollup[]>([]);
  const [perfData, setPerfData]     = useState<ModelPerformance | null>(null);
  const [loading, setLoading]       = useState(true);
  const [rollupLoading, setRollupLoading] = useState(true);
  const [perfLoading, setPerfLoading] = useState(true);
  const [error, setError]           = useState<string | null>(null);

  // Recompute state
  const [recomputing, setRecomputing]   = useState(false);
  const [recomputeProgress, setRecomputeProgress] = useState<number>(0);
  const [recomputeMessage, setRecomputeMessage]   = useState<string>('');
  const [pmReportOpen, setPmReportOpen] = useState(false);
  const [pmReportLoading, setPmReportLoading] = useState(false);
  const [pmReportMarkdown, setPmReportMarkdown] = useState<string | null>(null);
  const [pmReportError, setPmReportError] = useState<string | null>(null);
  const [pmReportCopied, setPmReportCopied] = useState(false);
  const [pmProductId, setPmProductId] = useState<number | null>(null);
  const [pmReportScope, setPmReportScope] = useState<number | null>(null);

  // Filter state
  const [filterCategory, setFilterCategory] = useState<string>('ALL');
  const [filterAction, setFilterAction] = useState<string>('ALL');
  const [search, setSearch] = useState<string>('');

  // Sort state
  type SortKey =
    | 'product_name' | 'current_stock' | 'reorder_point'
    | 'stockout_probability' | 'velocity_ratio'
    | 'recommended_action' | 'price_change_pct';
  const [sortKey, setSortKey] = useState<SortKey>('stockout_probability');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  // Derive category list from data
  const categories = Array.from(
    new Set(items.map(i => i.category))
  ).sort();
  const pmProductOptions = [...items]
    .filter((i) => i.status === 'ok')
    .sort((a, b) => a.product_name.localeCompare(b.product_name));
  const selectedPmProduct = pmProductId == null
    ? null
    : pmProductOptions.find((i) => i.product_id === pmProductId) ?? null;
  const pmReportScopeProduct = pmReportScope == null
    ? null
    : pmProductOptions.find((i) => i.product_id === pmReportScope) ?? null;

  // Action severity order (for sorting)
  const actionOrder: Record<string, number> = {
    ORDER_NOW: 0, LOW_STOCK: 1, HOLD: 2,
  };

  const filteredSortedItems = (() => {
    let result = items;

    if (filterCategory !== 'ALL') {
      result = result.filter(i => i.category === filterCategory);
    }
    if (filterAction !== 'ALL') {
      result = result.filter(i => i.recommended_action === filterAction);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(i => i.product_name.toLowerCase().includes(q));
    }

    const dir = sortDir === 'asc' ? 1 : -1;
    result = [...result].sort((a, b) => {
      let av: any, bv: any;
      if (sortKey === 'recommended_action') {
        av = actionOrder[a.recommended_action ?? ''] ?? 99;
        bv = actionOrder[b.recommended_action ?? ''] ?? 99;
      } else {
        av = (a as any)[sortKey];
        bv = (b as any)[sortKey];
      }
      // Nulls always sort to the end, regardless of direction
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    });

    return result;
  })();

  const loadData = useCallback(async () => {
    setLoading(true);
    setRollupLoading(true);
    setPerfLoading(true);
    setError(null);
    try {
      const [pRes, mRes, rRes, perfRes] = await Promise.all([
        dssAPI.portfolio(),
        dssAPI.portfolioMeta(),
        dssAPI.categoryRollup(),
        dssAPI.modelPerformance(),
      ]);
      setItems(pRes.data as PortfolioItem[]);
      setMeta(mRes.data as PortfolioMeta);
      setRollup(rRes.data as CategoryRollup[]);
      setPerfData(perfRes.data as ModelPerformance);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Failed to load portfolio');
    } finally {
      setLoading(false);
      setRollupLoading(false);
      setPerfLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (pmProductId == null) return;
    const exists = pmProductOptions.some((p) => p.product_id === pmProductId);
    if (!exists) setPmProductId(null);
  }, [pmProductId, pmProductOptions]);

  const handleRecompute = useCallback(async () => {
    if (recomputing) return;
    setRecomputing(true);
    setRecomputeProgress(0);
    setRecomputeMessage('Starting recompute...');

    try {
      const { data } = await dssAPI.recomputeForecasts();
      const jobId = (data as any).job_id;
      if (!jobId) throw new Error('No job_id returned');

      // Poll the SSE endpoint with fetch + reader (simpler than EventSource
      // for JWT-authenticated streams).
      const resp = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'}/dss/recompute-forecasts/${jobId}/progress`,
      );
      if (!resp.body) throw new Error('No response body');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const job = JSON.parse(line.slice(6));
            if (typeof job.progress === 'number') setRecomputeProgress(job.progress);
            const status = job.status as string | undefined;
            setRecomputeMessage(
              status === 'done'
                ? `Done — processed ${job.products_processed ?? '?'} products in ${job.duration_seconds ?? '?'}s`
                : status === 'error'
                ? `Error: ${job.error ?? 'unknown'}`
                : `${status} — ${job.products_processed ?? 0}/${job.products_total ?? '?'}`,
            );
            if (status === 'done' || status === 'error') {
              reader.cancel();
              if (status === 'done') {
                await loadData();  // refresh portfolio with fresh cache
              }
              return;
            }
          } catch {
            // ignore malformed SSE frame
          }
        }
      }
    } catch (e: any) {
      setRecomputeMessage(`Error: ${e?.message ?? 'recompute failed'}`);
    } finally {
      setRecomputing(false);
    }
  }, [recomputing, loadData]);

  const generatePMReport = useCallback(async () => {
    if (pmProductId == null) return;
    const sameScope = pmReportScope === pmProductId;
    if (pmReportMarkdown && sameScope && !pmReportLoading && !pmReportOpen) {
      setPmReportOpen(true);
      return;
    }
    setPmReportLoading(true);
    setPmReportError(null);
    setPmReportMarkdown(null);
    setPmReportOpen(true);
    setPmReportCopied(false);
    try {
      const res = await dssAPI.generatePMReport({ product_id: pmProductId });
      setPmReportMarkdown((res.data as any).markdown ?? 'No content returned.');
      setPmReportScope(pmProductId);
    } catch (e: any) {
      setPmReportError(e?.response?.data?.detail ?? e?.message ?? 'Failed to generate report');
      setPmReportScope(null);
    } finally {
      setPmReportLoading(false);
    }
  }, [pmProductId, pmReportLoading, pmReportOpen, pmReportMarkdown, pmReportScope]);

  const copyPMReport = useCallback(() => {
    if (!pmReportMarkdown || !navigator?.clipboard) return;
    navigator.clipboard.writeText(pmReportMarkdown).then(() => {
      setPmReportCopied(true);
      setTimeout(() => setPmReportCopied(false), 2000);
    });
  }, [pmReportMarkdown]);


  // Header (always visible)
  const Header = (
    <div style={{
      display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
      marginBottom: 24, gap: 16, flexWrap: 'wrap',
    }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: C.text }}>
          Portfolio Health
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: 14, color: C.muted }}>
          {meta
            ? `${meta.products_cached} of ${meta.total_products} products • last updated ${timeAgo(meta.last_computed_at)}`
            : 'Loading…'}
        </p>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {recomputing && (
          <span style={{ fontSize: 12, color: C.muted }}>
            {recomputeMessage} ({recomputeProgress}%)
          </span>
        )}
        <select
          value={pmProductId == null ? '' : String(pmProductId)}
          onChange={(e) => {
            const v = e.target.value;
            setPmProductId(v ? Number(v) : null);
          }}
          disabled={pmReportLoading || loading || pmProductOptions.length === 0}
          style={{
            padding: '8px 10px',
            borderRadius: 8,
            border: `1px solid ${C.border}`,
            background: C.surface,
            color: C.text,
            fontSize: 13,
            cursor: (pmReportLoading || loading || pmProductOptions.length === 0) ? 'not-allowed' : 'pointer',
            minWidth: 220,
            opacity: (pmReportLoading || loading || pmProductOptions.length === 0) ? 0.65 : 1,
          }}
          title="Choose product focus for PM report"
        >
          <option value="" disabled>Select a product</option>
          {pmProductOptions.map((p) => (
            <option key={p.product_id} value={String(p.product_id)}>
              {p.product_name}
            </option>
          ))}
        </select>
        <button
          onClick={generatePMReport}
          disabled={pmReportLoading || loading || pmProductOptions.length === 0 || pmProductId == null}
          style={{
            padding: '8px 16px', borderRadius: 8,
            border: `1px solid ${C.accent}`,
            background: C.accent,
            color: '#fff',
            fontSize: 13, fontWeight: 600,
            cursor: (pmReportLoading || loading || pmProductOptions.length === 0 || pmProductId == null) ? 'not-allowed' : 'pointer',
            transition: 'background 0.15s',
            opacity: (pmReportLoading || loading || pmProductOptions.length === 0 || pmProductId == null) ? 0.6 : 1,
          }}
        >
          {pmReportLoading ? 'Generating…' : '📋 PM Report'}
        </button>
        <button
          onClick={handleRecompute}
          disabled={recomputing}
          style={{
            padding: '8px 16px', borderRadius: 8,
            border: `1px solid ${C.border}`,
            background: recomputing ? C.border : C.surface,
            color: recomputing ? C.muted : C.text,
            fontSize: 13, fontWeight: 600,
            cursor: recomputing ? 'wait' : 'pointer',
            transition: 'background 0.15s',
          }}
        >
          {recomputing ? 'Recomputing…' : 'Recompute forecasts'}
        </button>
      </div>
    </div>
  );

  // Body states
  let body: React.ReactNode;

  if (loading && items.length === 0) {
    body = (
      <Card>
        <div style={{
          minHeight: 200, display: 'flex', alignItems: 'center',
          justifyContent: 'center', color: C.muted, fontSize: 14,
        }}>
          Loading portfolio…
        </div>
      </Card>
    );
  } else if (error) {
    body = (
      <Card>
        <div style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div style={{ color: C.danger, fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
            Failed to load portfolio
          </div>
          <div style={{ color: C.muted, fontSize: 13, marginBottom: 16 }}>
            {error}
          </div>
          <button
            onClick={loadData}
            style={{
              padding: '8px 20px', borderRadius: 8,
              border: `1px solid ${C.accent}`,
              background: C.accent, color: '#fff',
              fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      </Card>
    );
  } else if (items.length === 0) {
    body = (
      <Card>
        <div style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div style={{ color: C.text, fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
            No products in portfolio
          </div>
          <div style={{ color: C.muted, fontSize: 13, marginBottom: 16 }}>
            Upload sales data first to populate the portfolio.
          </div>
          <button
            onClick={() => router.push('/products')}
            style={{
              padding: '8px 20px', borderRadius: 8,
              border: `1px solid ${C.accent}`,
              background: C.accent, color: '#fff',
              fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            Go to products
          </button>
        </div>
      </Card>
    );
  } else {
    const categoryColor = (category: string) => {
      const key = category.toLowerCase();
      if (key.includes('accessor')) return '#6366f1';
      if (key.includes('clothing') || key.includes('apparel')) return '#0ea5e9';
      if (key.includes('electronic')) return '#f59e0b';
      if (key.includes('footwear')) return '#10b981';
      return C.accent;
    };

    const chartRows = rollup.map((r) => ({
      category: r.category,
      shortCategory: r.category.length > 14 ? `${r.category.slice(0, 14)}…` : r.category,
      dss: r.avg_dss_service_level,
      naive: r.avg_naive_service_level,
    }));
    const minChartValue = chartRows.length
      ? Math.min(...chartRows.flatMap((r) => [r.dss, r.naive]))
      : 0;
    const yMin = Math.max(0, Math.floor(minChartValue - 2));
    const histogramBins = (() => {
      if (!perfData?.products?.length) return [];
      const bins = Array.from({ length: 10 }, (_, i) => ({
        label: `${i * 10}-${(i + 1) * 10}`,
        min: i * 10,
        max: (i + 1) * 10,
        count: 0,
      }));
      perfData.products.forEach((p) => {
        const idx = Math.min(Math.floor(p.under_forecast_pct / 10), 9);
        bins[idx].count += 1;
      });
      return bins;
    })();

    const actionCounts = items.reduce((acc, item) => {
      const action = item.recommended_action ?? 'N_A';
      acc[action] = (acc[action] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    const atRiskCount = items.filter(
      (item) => item.status === 'ok' && (item.stockout_probability ?? 0) > 50
    ).length;

    const donutData = [
      { name: 'ORDER_NOW', value: actionCounts.ORDER_NOW || 0, color: C.danger },
      { name: 'LOW_STOCK', value: actionCounts.LOW_STOCK || 0, color: C.warn },
      { name: 'HOLD', value: actionCounts.HOLD || 0, color: C.success },
    ].filter((d) => d.value > 0);
    const donutTotal = donutData.reduce((s, d) => s + d.value, 0);

    body = (
      <>
        {!rollupLoading && rollup.length > 0 && (
          <Card style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 14 }}>
              <h2 style={{ margin: 0, color: C.text, fontSize: 18, fontWeight: 700 }}>
                Category Performance
              </h2>
              <p style={{ margin: '6px 0 0', color: C.muted, fontSize: 13 }}>
                Argument #3 evidence: model and policy behavior varies by category (No Free Lunch).
              </p>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 12,
                marginBottom: 16,
              }}
            >
              {rollup.map((r) => {
                const delta = (r.avg_dss_service_level ?? 0) - (r.avg_naive_service_level ?? 0);
                const deltaColor = delta >= 0 ? C.success : C.danger;
                return (
                  <div
                    key={r.category}
                    style={{
                      border: `1px solid ${C.border}`,
                      borderLeft: `4px solid ${categoryColor(r.category)}`,
                      borderRadius: 10,
                      background: C.surface,
                      padding: 12,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                      <div>
                        <div style={{ color: C.text, fontSize: 14, fontWeight: 700 }}>{r.category}</div>
                        <div style={{ color: C.muted, fontSize: 12 }}>{r.product_count} products</div>
                      </div>
                      {r.at_risk_count > 0 && (
                        <span
                          style={{
                            padding: '2px 8px',
                            borderRadius: 999,
                            border: `1px solid ${C.danger}33`,
                            background: '#fee2e2',
                            color: C.danger,
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          {r.at_risk_count} at risk
                        </span>
                      )}
                    </div>

                    <div
                      style={{
                        marginTop: 10,
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: 8,
                      }}
                    >
                      <div>
                        <div style={{ color: C.subtle, fontSize: 11 }}>Avg MAE</div>
                        <div style={{ color: C.text, fontSize: 14, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>
                          {r.avg_mae.toFixed(2)}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: C.subtle, fontSize: 11 }}>Under-Forecast %</div>
                        <div style={{ color: C.text, fontSize: 14, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>
                          {r.avg_under_forecast_pct.toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div style={{ color: C.subtle, fontSize: 11 }}>DSS Service Level</div>
                        <div style={{ color: C.text, fontSize: 14, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>
                          {r.avg_dss_service_level.toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div style={{ color: C.subtle, fontSize: 11 }}>DSS vs Naive</div>
                        <div style={{ color: deltaColor, fontSize: 14, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>
                          {delta >= 0 ? '+' : ''}
                          {delta.toFixed(1)}%
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: 12, background: C.surface }}>
              <div style={{ color: C.text, fontSize: 14, fontWeight: 700, marginBottom: 2 }}>
                Service Level Comparison by Category
              </div>
              <div style={{ color: C.muted, fontSize: 12, marginBottom: 8 }}>
                DSS (green) vs Naive baseline (amber) — average service level from 30-day backtest simulation
              </div>
              <div style={{ width: '100%', height: 280 }}>
                <ResponsiveContainer>
                  <BarChart data={chartRows} barCategoryGap={18}>
                    <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="shortCategory"
                      tick={{ fill: C.muted, fontSize: 11 }}
                      axisLine={{ stroke: C.border }}
                      tickLine={{ stroke: C.border }}
                    />
                    <YAxis
                      domain={[yMin, 100]}
                      tick={{ fill: C.muted, fontSize: 11 }}
                      axisLine={{ stroke: C.border }}
                      tickLine={{ stroke: C.border }}
                    />
                    <Tooltip
                      contentStyle={{
                        border: `1px solid ${C.border}`,
                        borderRadius: 8,
                        background: C.surface,
                        color: C.text,
                      }}
                      formatter={(value: any, name: any) => [
                        `${Number(value).toFixed(1)}%`,
                        name === 'dss' ? 'DSS' : 'Naive',
                      ]}
                      labelFormatter={(label: any) => {
                        const row = chartRows.find((r) => r.shortCategory === label);
                        return row?.category ?? label;
                      }}
                    />
                    <Legend formatter={(value) => (value === 'dss' ? 'DSS' : 'Naive')} />
                    <Bar dataKey="dss" fill={C.success}>
                      {chartRows.map((r) => (
                        <Cell key={`${r.category}-dss`} fill={C.success} />
                      ))}
                    </Bar>
                    <Bar dataKey="naive" fill={C.warn}>
                      {chartRows.map((r) => (
                        <Cell key={`${r.category}-naive`} fill={C.warn} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </Card>
        )}

        {rollupLoading && (
          <Card style={{ marginBottom: 16 }}>
            <div style={{ minHeight: 110, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: 14 }}>
              Loading category analysis…
            </div>
          </Card>
        )}

        {perfLoading && (
          <Card style={{ marginBottom: 16 }}>
            <div style={{ minHeight: 110, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: 14 }}>
              Loading model performance…
            </div>
          </Card>
        )}

        {!perfLoading && perfData && perfData.products.length > 0 && (
          <Card style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 12 }}>
              <h2 style={{ margin: 0, color: C.text, fontSize: 18, fontWeight: 700 }}>
                Model Performance Monitor
              </h2>
              <p style={{ margin: '6px 0 0', color: C.muted, fontSize: 13 }}>
                Forecast accuracy distribution across 49 products — supports Argument #1 (Accuracy ≠ Inventory Safety).
              </p>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 10,
                marginBottom: 12,
              }}
            >
              <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: 10 }}>
                <div style={{ color: C.subtle, fontSize: 11 }}>Avg MAE</div>
                <div style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace', fontSize: 16, fontWeight: 700 }}>
                  {perfData.summary.avg_mae.toFixed(2)}
                </div>
              </div>
              <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: 10 }}>
                <div style={{ color: C.subtle, fontSize: 11 }}>Avg Under-Forecast %</div>
                <div style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace', fontSize: 16, fontWeight: 700 }}>
                  {perfData.summary.avg_under_forecast_pct.toFixed(1)}%
                </div>
              </div>
              <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: 10 }}>
                <div style={{ color: C.subtle, fontSize: 11 }}>
                  Products At Risk (&gt;50% stockout)
                </div>
                <div style={{ color: C.danger, fontFamily: 'JetBrains Mono, monospace', fontSize: 16, fontWeight: 700 }}>
                  {atRiskCount}
                </div>
              </div>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
                gap: 16,
              }}
            >
              <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: 12 }}>
                <div style={{ color: C.text, fontSize: 14, fontWeight: 700, marginBottom: 2 }}>
                  Under-Forecast Distribution
                </div>
                <div style={{ color: C.muted, fontSize: 12, marginBottom: 8 }}>
                  Products that under-forecast &gt;50% of days face higher stockout risk
                </div>
                <div style={{ width: '100%', height: 260 }}>
                  <ResponsiveContainer>
                    <BarChart data={histogramBins}>
                      <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="label" tick={{ fill: C.muted, fontSize: 11 }} />
                      <YAxis allowDecimals={false} tick={{ fill: C.muted, fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{
                          border: `1px solid ${C.border}`,
                          borderRadius: 8,
                          background: C.surface,
                        }}
                        formatter={(value: any) => [`${value}`, 'Products']}
                        labelFormatter={(label: any) => `Under-forecast ${label}%`}
                      />
                      <ReferenceLine
                        x="50-60"
                        stroke={C.danger}
                        strokeDasharray="5 5"
                        label={{ value: 'Safety threshold (50%)', fill: C.danger, fontSize: 11, position: 'top' }}
                      />
                      <Bar dataKey="count">
                        {histogramBins.map((bin) => (
                          <Cell
                            key={bin.label}
                            fill={bin.min >= 50 ? C.danger : C.success}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: 12 }}>
                <div style={{ color: C.text, fontSize: 14, fontWeight: 700, marginBottom: 2 }}>
                  Decision Distribution
                </div>
                <div style={{ color: C.muted, fontSize: 12, marginBottom: 8 }}>
                  Current portfolio action breakdown
                </div>
                <div style={{ width: '100%', height: 260 }}>
                  <ResponsiveContainer>
                    <PieChart>
                      <Pie
                        data={donutData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={90}
                        paddingAngle={2}
                      >
                        {donutData.map((entry) => (
                          <Cell key={entry.name} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value: any, name: any) => [`${value}`, `${name}`]}
                        contentStyle={{
                          border: `1px solid ${C.border}`,
                          borderRadius: 8,
                          background: C.surface,
                        }}
                      />
                      <text
                        x="50%"
                        y="50%"
                        textAnchor="middle"
                        dominantBaseline="middle"
                        style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 18, fontWeight: 700, fill: C.text }}
                      >
                        {donutTotal}
                      </text>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                  {donutData.map((d) => (
                    <span key={d.name} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12, color: C.muted }}>
                      <span style={{ width: 10, height: 10, borderRadius: 999, display: 'inline-block', background: d.color }} />
                      {d.name}: {d.value}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </Card>
        )}

        {/* Filter bar */}
        <Card style={{ marginBottom: 16, padding: 16 }}>
          <div style={{
            display: 'flex', gap: 12, alignItems: 'center',
            flexWrap: 'wrap',
          }}>
            <input
              type="text"
              placeholder="Search product name…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                flex: '1 1 240px', minWidth: 200,
                padding: '8px 12px', borderRadius: 8,
                border: `1px solid ${C.border}`, background: C.surface,
                color: C.text, fontSize: 13, outline: 'none',
              }}
              onFocus={e => e.target.style.borderColor = C.accent}
              onBlur={e => e.target.style.borderColor = C.border}
            />
            <select
              value={filterCategory}
              onChange={e => setFilterCategory(e.target.value)}
              style={{
                padding: '8px 12px', borderRadius: 8,
                border: `1px solid ${C.border}`, background: C.surface,
                color: C.text, fontSize: 13, cursor: 'pointer',
              }}
            >
              <option value="ALL">All categories</option>
              {categories.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <select
              value={filterAction}
              onChange={e => setFilterAction(e.target.value)}
              style={{
                padding: '8px 12px', borderRadius: 8,
                border: `1px solid ${C.border}`, background: C.surface,
                color: C.text, fontSize: 13, cursor: 'pointer',
              }}
            >
              <option value="ALL">All actions</option>
              <option value="ORDER_NOW">ORDER_NOW</option>
              <option value="LOW_STOCK">LOW_STOCK</option>
              <option value="HOLD">HOLD</option>
            </select>
            <button
              onClick={() => {
                setFilterCategory('ALL');
                setFilterAction('ALL');
                setSearch('');
              }}
              style={{
                padding: '8px 14px', borderRadius: 8,
                border: `1px solid ${C.border}`, background: C.surface,
                color: C.muted, fontSize: 12, cursor: 'pointer',
              }}
            >
              Clear
            </button>
            <span style={{
              marginLeft: 'auto', fontSize: 12, color: C.muted,
            }}>
              {filteredSortedItems.length} of {items.length} products
            </span>
          </div>
        </Card>

        {/* Empty-after-filter state */}
        {filteredSortedItems.length === 0 ? (
          <Card>
            <div style={{ textAlign: 'center', padding: '40px 20px' }}>
              <div style={{ color: C.text, fontSize: 15, fontWeight: 600, marginBottom: 6 }}>
                No products match current filters
              </div>
              <div style={{ color: C.muted, fontSize: 12, marginBottom: 14 }}>
                {filterAction === 'LOW_STOCK' && (
                  <>LOW_STOCK is a transitional state and rarely observed — the DSS engine preempts borderline cases to ORDER_NOW when stock falls below the reorder point. Verified via sensitivity experiment (penalty_under ∈ {'{1.0, 5.0}'}, both produced zero LOW_STOCK).</>
                )}
              </div>
              <button
                onClick={() => {
                  setFilterCategory('ALL');
                  setFilterAction('ALL');
                  setSearch('');
                }}
                style={{
                  padding: '8px 16px', borderRadius: 8,
                  border: `1px solid ${C.accent}`, background: C.accent,
                  color: '#fff', fontSize: 13, fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Clear filters
              </button>
            </div>
          </Card>
        ) : (
          <Card style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{
                width: '100%', borderCollapse: 'collapse',
                fontSize: 13, color: C.text,
              }}>
                <thead>
                  <tr style={{
                    background: C.bg,
                    borderBottom: `1px solid ${C.border}`,
                  }}>
                    {[
                      { key: 'product_name' as SortKey, label: 'Product', align: 'left', width: undefined },
                      { key: null, label: 'Category', align: 'left', width: 120 },
                      { key: 'current_stock' as SortKey, label: 'Stock', align: 'right', width: 90 },
                      { key: 'reorder_point' as SortKey, label: 'ROP', align: 'right', width: 90 },
                      { key: 'stockout_probability' as SortKey, label: 'Stockout Risk', align: 'right', width: 130 },
                      { key: 'velocity_ratio' as SortKey, label: 'Velocity', align: 'left', width: 100 },
                      { key: 'recommended_action' as SortKey, label: 'Action', align: 'left', width: 140 },
                      { key: 'price_change_pct' as SortKey, label: 'Price Δ', align: 'right', width: 90 },
                    ].map((col) => {
                      const sortable = col.key !== null;
                      const active = sortable && col.key === sortKey;
                      const indicator = active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';
                      return (
                        <th
                          key={col.label}
                          onClick={sortable ? () => toggleSort(col.key as SortKey) : undefined}
                          style={{
                            padding: '12px 14px',
                            textAlign: col.align as any,
                            fontSize: 11, fontWeight: 700,
                            letterSpacing: '0.06em', textTransform: 'uppercase',
                            color: active ? C.accent : C.muted,
                            cursor: sortable ? 'pointer' : 'default',
                            userSelect: 'none',
                            width: col.width,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {col.label}{indicator}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {filteredSortedItems.map((it) => {
                    const isDimmed = it.status !== 'ok';
                    const isClickable = it.status === 'ok';
                    const rowBg = isDimmed
                      ? C.bg
                      : actionTint[it.recommended_action ?? ''] ?? 'transparent';
                    const hoverBg = `color-mix(in srgb, ${rowBg === 'transparent' ? C.surface : rowBg} 88%, ${C.border} 12%)`;
                    const textMuted = isDimmed ? C.subtle : C.text;
                    const v = velocityLabel(it.velocity_ratio);
                    const stockoutC = stockoutColor(it.stockout_probability);
                    const priceColor =
                      it.price_change_pct == null || it.price_change_pct === 0
                        ? C.muted
                        : it.price_change_pct > 0
                        ? C.success
                        : C.danger;

                    const truncatedName =
                      it.product_name.length > 30
                        ? it.product_name.slice(0, 30) + '…'
                        : it.product_name;

                    return (
                      <tr
                        key={it.product_id}
                        onClick={() => {
                          if (!isClickable) return;
                          router.push(`/dss?product_id=${it.product_id}`);
                        }}
                        onMouseEnter={(e) => {
                          if (!isClickable) return;
                          e.currentTarget.style.background = hoverBg;
                        }}
                        onMouseLeave={(e) => {
                          if (!isClickable) return;
                          e.currentTarget.style.background = rowBg;
                        }}
                        title={it.status !== 'ok'
                          ? (it.status === 'insufficient_data'
                              ? `${it.product_name} — not enough sales history`
                              : `${it.product_name} — error computing DSS`)
                          : it.product_name}
                        style={{
                          background: rowBg,
                          borderBottom: `1px solid ${C.border}`,
                          transition: 'background 0.12s',
                          cursor: isClickable ? 'pointer' : 'default',
                        }}
                      >
                        <td style={{ padding: '12px 14px', color: textMuted }}>
                          {truncatedName}
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <span style={{
                            display: 'inline-block',
                            padding: '2px 8px', borderRadius: 10,
                            background: C.bg, border: `1px solid ${C.border}`,
                            fontSize: 11, color: C.muted,
                          }}>
                            {it.category}
                          </span>
                        </td>
                        <td style={{
                          padding: '12px 14px', textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums', color: textMuted,
                        }}>
                          {it.current_stock}
                        </td>
                        <td style={{
                          padding: '12px 14px', textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums', color: C.muted,
                        }}>
                          {isDimmed ? '—' : formatNum(it.reorder_point, 0)}
                        </td>
                        <td style={{
                          padding: '12px 14px', textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums',
                          color: isDimmed ? C.subtle : stockoutC, fontWeight: 600,
                        }}>
                          {isDimmed ? '—' : formatPct(it.stockout_probability)}
                        </td>
                        <td style={{ padding: '12px 14px', color: isDimmed ? C.subtle : v.color, fontWeight: 500 }}>
                          {isDimmed ? '—' : v.text}
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          {isDimmed
                            ? <span style={{ color: C.subtle }}>—</span>
                            : it.recommended_action
                            ? <span style={actionPillStyle(it.recommended_action)}>
                                {it.recommended_action}
                              </span>
                            : <span style={{ color: C.subtle }}>—</span>}
                        </td>
                        <td style={{
                          padding: '12px 14px', textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums',
                          color: isDimmed ? C.subtle : priceColor, fontWeight: 600,
                        }}>
                          {isDimmed ? '—' : formatSigned(it.price_change_pct)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </>
    );
  }

  return (
    <div style={{
      minHeight: '100vh', background: C.bg, padding: '32px 24px',
    }}>
      <div style={{ maxWidth: 1400, margin: '0 auto' }}>
        {Header}
        {body}
      </div>

      {pmReportOpen && (
        <div
          onClick={() => {
            setPmReportOpen(false);
            setPmReportError(null);
            setPmReportCopied(false);
          }}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.5)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 30,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '100%',
              maxWidth: 1120,
              maxHeight: '90vh',
              overflowY: 'auto',
              borderRadius: 20,
              background: C.surface,
              boxShadow: '0 20px 50px rgba(0,0,0,0.2)',
              padding: 36,
              animation: 'pmFadeIn 0.18s ease-out',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, gap: 12 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 36, color: C.text, fontWeight: 800, lineHeight: 1.1 }}>PM Report</h3>
                <div style={{ marginTop: 8, fontSize: 18, color: C.muted }}>
                  {pmReportScopeProduct ? `Focus product: ${pmReportScopeProduct.product_name}` : 'No product selected'}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={copyPMReport}
                  disabled={!pmReportMarkdown}
                  style={{
                    padding: '11px 16px',
                    borderRadius: 10,
                    border: `1px solid ${C.border}`,
                    background: C.surface,
                    color: pmReportCopied ? C.success : C.text,
                    fontSize: 16,
                    fontWeight: 600,
                    cursor: pmReportMarkdown ? 'pointer' : 'not-allowed',
                  }}
                >
                  {pmReportCopied ? 'Copied!' : 'Copy Markdown'}
                </button>
                <button
                  onClick={() => {
                    setPmReportOpen(false);
                    setPmReportError(null);
                    setPmReportCopied(false);
                  }}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 10,
                    border: `1px solid ${C.border}`,
                    background: C.surface,
                    color: C.muted,
                    fontSize: 20,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  ×
                </button>
              </div>
            </div>

            {pmReportLoading && (
              <div style={{ minHeight: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: 19 }}>
                <span style={{ animation: 'pmPulse 1.4s ease-in-out infinite' }}>
                  Generating report… This may take up to 60 seconds.
                </span>
              </div>
            )}

            {!pmReportLoading && pmReportError && (
              <div style={{ border: `1px solid ${C.danger}33`, borderRadius: 12, background: '#fee2e2', padding: 18 }}>
                <div style={{ color: C.danger, fontWeight: 700, fontSize: 20, marginBottom: 10 }}>Failed to generate report</div>
                <div style={{ color: C.text, fontSize: 16, marginBottom: 14 }}>{pmReportError}</div>
                <button
                  onClick={generatePMReport}
                  style={{
                    padding: '10px 16px',
                    borderRadius: 10,
                    border: `1px solid ${C.accent}`,
                    background: C.accent,
                    color: '#fff',
                    fontSize: 15,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Retry
                </button>
              </div>
            )}

            {!pmReportLoading && !pmReportError && pmReportMarkdown && (
              <div
                style={{ lineHeight: 1.92, fontSize: 20, color: C.text }}
                dangerouslySetInnerHTML={{ __html: renderMarkdown(pmReportMarkdown) }}
              />
            )}
          </div>
        </div>
      )}

      <style jsx global>{`
        @keyframes pmPulse {
          0%, 100% { opacity: 0.55; }
          50% { opacity: 1; }
        }
        @keyframes pmFadeIn {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
