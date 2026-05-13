'use client';

import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { productsAPI, dssAPI, salesAPI } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────
interface Product {
  id: number; sku: string; name: string;
  current_stock?: number; current_price?: number;
  sales_7d?: number; category_name?: string;
}

interface ConfirmOrderForm {
  quantity: string;
  supplier: string;
  unit_cost: string;
  notes: string;
}

// ─── Design tokens ────────────────────────────────────────────────────
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

const tag = (color: string, bg: string, text: string) => ({
  display: 'inline-flex', alignItems: 'center', gap: 5,
  padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700,
  letterSpacing: '0.04em', textTransform: 'uppercase' as const,
  color, background: bg, border: `1px solid ${color}33`,
});

const actionColors: Record<string, [string, string]> = {
  ORDER_NOW:  [C.danger,   '#ef444422'],
  LOW_STOCK:  [C.warn,     '#f59e0b22'],
  HOLD:       [C.success,  '#10b98122'],
  INCREASE:   [C.success,  '#10b98122'],
  DECREASE:   [C.danger,   '#ef444422'],
  N_A:        [C.muted,    '#64748b22'],
};
const getColor = (s?: string) => actionColors[s?.replace(/\s/g,'_') ?? ''] ?? [C.muted, '#64748b22'];

const formatApiErrorDetail = (detail: any): string => {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => formatApiErrorDetail(item))
      .filter(Boolean)
      .join(' | ');
  }
  if (typeof detail === 'object') {
    if (typeof detail.msg === 'string') {
      const loc = Array.isArray(detail.loc) ? detail.loc.join('.') : '';
      return loc ? `${loc}: ${detail.msg}` : detail.msg;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return String(detail);
    }
  }
  return String(detail);
};

const getApiErrorMessage = (error: any, fallback: string): string => {
  const detailMessage = formatApiErrorDetail(error?.response?.data?.detail).trim();
  return detailMessage || error?.message || fallback;
};

// ─── Tiny components ──────────────────────────────────────────────────
const Card = ({ children, style = {} }: any) => (
  <div style={{
    background: C.surface, border: `1px solid ${C.border}`,
    borderRadius: 14, padding: 24, ...style,
  }}>{children}</div>
);

const Label = ({ children }: any) => (
  <p style={{ margin: '0 0 6px', fontSize: 11, fontWeight: 600, color: C.muted, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{children}</p>
);

const Input = ({ label, ...props }: any) => (
  <div>
    <Label>{label}</Label>
    <input {...props} style={{
      width: '100%', padding: '9px 12px', borderRadius: 8,
      border: `1px solid ${C.border}`, background: '#ffffff',
      color: C.text, fontSize: 14, outline: 'none', boxSizing: 'border-box' as const,
      transition: 'border-color 0.2s',
      ...props.style,
    }}
      onFocus={e => e.target.style.borderColor = C.accent}
      onBlur={e => e.target.style.borderColor = C.border}
    />
  </div>
);

const Btn = ({ children, variant = 'primary', disabled = false, onClick, style = {} }: any) => {
  const base = {
    padding: '10px 20px', borderRadius: 9, fontWeight: 700, fontSize: 13,
    cursor: disabled ? 'not-allowed' : 'pointer', border: 'none',
    transition: 'all 0.15s', letterSpacing: '0.02em', ...style,
  };
  if (disabled) return <button style={{ ...base, background: C.border, color: C.muted }} disabled>{children}</button>;
  if (variant === 'primary')  return <button onClick={onClick} style={{ ...base, background: C.accent, color: '#fff' }}>{children}</button>;
  if (variant === 'success')  return <button onClick={onClick} style={{ ...base, background: C.success, color: '#fff' }}>{children}</button>;
  if (variant === 'danger')   return <button onClick={onClick} style={{ ...base, background: C.danger, color: '#fff' }}>{children}</button>;
  return <button onClick={onClick} style={{ ...base, background: 'transparent', color: C.subtle, border: `1px solid ${C.border}` }}>{children}</button>;
};

const StatBox = ({ label, value, sub, color = C.text }: any) => (
  <div style={{ padding: '16px 20px', background: '#0f1117', borderRadius: 10, border: `1px solid ${C.border}` }}>
    <Label>{label}</Label>
    <p style={{ margin: '4px 0 0', fontSize: 22, fontWeight: 800, color, fontVariantNumeric: 'tabular-nums' }}>{value ?? '—'}</p>
    {sub && <p style={{ margin: '4px 0 0', fontSize: 12, color: C.muted }}>{sub}</p>}
  </div>
);

const Spinner = () => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: 48 }}>
    <div style={{
      width: 44, height: 44, borderRadius: '50%',
      border: `3px solid ${C.border}`, borderTop: `3px solid ${C.accent}`,
      animation: 'spin 0.8s linear infinite',
    }} />
    <p style={{ color: C.muted, fontSize: 14, margin: 0 }}>Running DSS pipeline…</p>
  </div>
);

const ChartTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: '8px 14px', fontSize: 12 }}>
      <p style={{ color: C.muted, margin: '0 0 4px' }}>{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} style={{ color: p.color, margin: '2px 0', fontWeight: 600 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </p>
      ))}
    </div>
  );
};

// ─── Confirm Order Modal ───────────────────────────────────────────────
function ConfirmOrderModal({
  suggestedQty,
  onConfirm,
  onCancel,
  loading,
}: {
  suggestedQty: number;
  onConfirm: (form: ConfirmOrderForm) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [form, setForm] = useState<ConfirmOrderForm>({
    quantity:  String(suggestedQty),
    supplier:  '',
    unit_cost: '',
    notes:     '',
  });

  const set = (k: keyof ConfirmOrderForm) => (e: any) =>
    setForm(prev => ({ ...prev, [k]: e.target.value }));

  const fieldStyle = {
    width: '100%', padding: '9px 12px', borderRadius: 8,
    border: `1px solid ${C.border}`, background: C.surface,
    color: C.text, fontSize: 13, outline: 'none',
    boxSizing: 'border-box' as const, fontFamily: 'inherit',
    transition: 'border-color 0.2s',
  };

  const qty = parseInt(form.quantity) || 0;

  return (
    <div style={{
      position: 'fixed', inset: 0,
      background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 200, animation: 'fadeUp 0.2s ease',
    }} onClick={onCancel}>
      <div style={{
        background: C.surface, borderRadius: 16, padding: 28,
        width: 460, maxWidth: '90vw', boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
        border: `1px solid ${C.border}`, animation: 'fadeUp 0.25s ease',
      }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <p style={{ margin: 0, fontWeight: 800, fontSize: 16, color: C.text }}>Confirm Stock Order</p>
            <p style={{ margin: '3px 0 0', fontSize: 12, color: C.muted }}>
              DSS recommended <b style={{ color: C.success, fontFamily: 'JetBrains Mono, monospace' }}>+{suggestedQty} units</b> — adjust if needed
            </p>
          </div>
          <button onClick={onCancel} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.subtle, fontSize: 20, lineHeight: 1, padding: 4 }}>×</button>
        </div>

        {/* Fields */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Quantity — pre-filled from DSS suggestion */}
          <div>
            <Label>Order Quantity *</Label>
            <input
              type="number" min="1" value={form.quantity}
              onChange={set('quantity')} style={fieldStyle}
              onFocus={e => e.target.style.borderColor = C.success}
              onBlur={e => e.target.style.borderColor = C.border}
            />
            {qty !== suggestedQty && qty > 0 && (
              <p style={{ fontSize: 11, color: C.warn, margin: '4px 0 0' }}>
                ⚡ Overriding DSS suggestion ({suggestedQty} units)
              </p>
            )}
          </div>

          {/* Supplier — free text, maps to StockInRequest.supplier */}
          <div>
            <Label>Supplier (optional)</Label>
            <input
              type="text" value={form.supplier} placeholder="e.g. Acme Wholesale"
              onChange={set('supplier')} style={fieldStyle}
              onFocus={e => e.target.style.borderColor = C.accent}
              onBlur={e => e.target.style.borderColor = C.border}
            />
          </div>

          {/* Purchase cost — maps to StockInRequest.unit_cost */}
          <div>
            <Label>Purchase Cost per Unit (optional)</Label>
            <input
              type="number" min="0" step="0.01" value={form.unit_cost}
              placeholder="e.g. 12.50"
              onChange={set('unit_cost')} style={fieldStyle}
              onFocus={e => e.target.style.borderColor = C.accent}
              onBlur={e => e.target.style.borderColor = C.border}
            />
          </div>

          {/* Notes */}
          <div>
            <Label>Notes (optional)</Label>
            <textarea
              value={form.notes} rows={2}
              placeholder="e.g. Urgent restock per DSS recommendation"
              onChange={set('notes')}
              style={{ ...fieldStyle, resize: 'vertical' as const, fontFamily: 'inherit' }}
              onFocus={e => e.target.style.borderColor = C.accent}
              onBlur={e => e.target.style.borderColor = C.border}
            />
          </div>
        </div>

        {/* Summary row */}
        {qty > 0 && (
          <div style={{
            marginTop: 16, padding: '10px 14px', borderRadius: 8,
            background: '#f0fdf4', border: `1px solid ${C.success}33`,
            fontSize: 12, color: C.muted, display: 'flex', gap: 16, flexWrap: 'wrap' as const,
          }}>
            <span>📦 <b style={{ color: C.text }}>{qty}</b> units</span>
            {form.supplier  && <span>🏭 <b style={{ color: C.text }}>{form.supplier}</b></span>}
            {form.unit_cost && <span>💵 <b style={{ color: C.text }}>${parseFloat(form.unit_cost).toFixed(2)}/unit</b> → total <b style={{ color: C.success }}>${(qty * parseFloat(form.unit_cost)).toFixed(2)}</b></span>}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, marginTop: 20, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{
            padding: '10px 20px', borderRadius: 9, border: `1px solid ${C.border}`,
            background: 'white', color: C.muted, fontWeight: 700, fontSize: 13, cursor: 'pointer',
          }}>Cancel</button>
          <button
            disabled={loading || qty <= 0}
            onClick={() => onConfirm(form)}
            style={{
              padding: '10px 24px', borderRadius: 9, border: 'none', fontWeight: 800,
              fontSize: 13, cursor: loading || qty <= 0 ? 'not-allowed' : 'pointer',
              background: loading || qty <= 0 ? C.border : C.success,
              color: loading || qty <= 0 ? C.muted : '#fff',
              transition: 'all 0.15s',
            }}
          >
            {loading ? 'Processing…' : `✔ Confirm +${qty} units`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────
export default function DSSPage() {
  const searchParams = useSearchParams();
  const productIdFromUrl = searchParams.get('product_id');

  const [products, setProducts]           = useState<Product[]>([]);
  const [selected, setSelected]           = useState<Product | null>(null);
  const [loading, setLoading]             = useState(false);
  const [result, setResult]               = useState<any>(null);
  const [error, setError]                 = useState<string | null>(null);
  const [tab, setTab]                     = useState<'analysis'|'backtest'|'history'>('analysis');
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [priceLoading, setPriceLoading]   = useState(false);
  const [actionMsg, setActionMsg]         = useState<{text:string,ok:boolean}|null>(null);
  const [backtest, setBacktest]           = useState<any>(null);
  const [btLoading, setBtLoading]         = useState(false);
  const [history, setHistory]             = useState<any[]>([]);
  const [salesMeta, setSalesMeta]         = useState<{totalDays:number, firstDate:string, lastDate:string, trainDays:number, testDays:number, trainStart:string, trainEnd:string, testStart:string, testEnd:string} | null>(null);
  const [editingReportId, setEditingReportId] = useState<number | null>(null);
  const [editReasoning, setEditReasoning] = useState('');

  // Analysis inputs
  const [stock, setStock]               = useState('');
  const [price, setPrice]               = useState('');
  const [targetDays, setTargetDays]     = useState('30');
  const [forecastDays, setForecastDays] = useState('30');
  const [penaltyUnder, setPenaltyUnder] = useState('5.0');
  const [btDays, setBtDays]             = useState('90');
  const [btStock, setBtStock]           = useState('');
  const [forecastLimitModal, setForecastLimitModal] = useState<{ entered: number; adjusted: number } | null>(null);

  useEffect(() => {
    productsAPI.list({ page: 1, page_size: 200 })
      .then((r: any) => setProducts(r.data.items || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (productIdFromUrl && products.length > 0) {
      const p = products.find(p => p.id === parseInt(productIdFromUrl));
      if (p) selectProduct(p);
    }
  }, [productIdFromUrl, products]);

  const selectProduct = (p: Product) => {
    setSelected(p);
    setStock(p.current_stock?.toString() ?? '0');
    setPrice(p.current_price?.toFixed(2) ?? '');
    setBtStock(p.current_stock?.toString() ?? '100');
    setResult(null); setError(null); setActionMsg(null);
    setBacktest(null); setHistory([]); setSalesMeta(null);
    setShowConfirmModal(false);

    dssAPI.reports(p.id, 5)
      .then((r: any) => setHistory(r.data || []))
      .catch(() => {});

    salesAPI.daily(p.id, { limit: 9999 })
      .then((r: any) => {
        const rows: any[] = r.data?.data || r.data || [];
        if (rows.length < 2) return;
        const dates = rows.map((d: any) => (d.date || d.ds || '').slice(0,10)).filter(Boolean).sort();
        const total  = dates.length;
        const trainN = Math.floor(total * 0.7);
        const testN  = total - trainN;
        setSalesMeta({
          totalDays: total, firstDate: dates[0], lastDate: dates[total - 1],
          trainDays: trainN, testDays: testN,
          trainStart: dates[0], trainEnd: dates[trainN - 1],
          testStart: dates[trainN], testEnd: dates[total - 1],
        });
        setBtDays(String(testN));
      })
      .catch(() => {});
  };

  const runAnalysis = async () => {
    if (!selected) return;
    const parsedForecastDays = parseInt(forecastDays) || 30;
    if (parsedForecastDays < 7 || parsedForecastDays > 90) {
      const adjustedForecastDays = Math.min(90, Math.max(7, parsedForecastDays));
      setForecastDays(String(adjustedForecastDays));
      setForecastLimitModal({ entered: parsedForecastDays, adjusted: adjustedForecastDays });
      setError(null);
      return;
    }
    setLoading(true); setError(null); setResult(null); setActionMsg(null);
    try {
      const payload: any = {
        product_id: selected.id,
        future_days: parsedForecastDays,
        target_days_to_sell: parseInt(targetDays) || 30,
        penalty_under: parseFloat(penaltyUnder) || 5,
      };
      if (stock !== '') payload.current_stock = parseInt(stock);
      if (price !== '') payload.current_price = parseFloat(price);
      const r: any = await dssAPI.run(payload);
      setResult(r.data);
      setTab('analysis');
      dssAPI.reports(selected.id, 5).then((r: any) => setHistory(r.data || [])).catch(() => {});
    } catch (e: any) {
      setError(getApiErrorMessage(e, 'Analysis failed. Check sales history data.'));
    } finally {
      setLoading(false);
    }
  };

  // Opens the modal instead of confirming directly
  const openConfirmModal = () => {
    setActionMsg(null);
    setShowConfirmModal(true);
  };

  // Called when user submits the confirm modal
  const confirmOrder = async (form: ConfirmOrderForm) => {
    if (!result?.id) return;
    setConfirmLoading(true); setActionMsg(null);
    try {
      const payload: any = { report_id: result.id };

      // Override quantity if user changed it from DSS suggestion
      const qty = parseInt(form.quantity) || 0;
      const suggestedQty = result.inventory_advice?.suggested_order_qty ?? result.inventory_advice?.qty_to_order ?? 0;
      if (qty !== suggestedQty) payload.quantity = qty;

      // Pass supplier + cost through to the backend's confirm-order endpoint,
      // which forwards them to stock_in as StockInRequest.supplier / unit_cost
      if (form.supplier.trim())  payload.supplier  = form.supplier.trim();
      if (form.unit_cost.trim()) payload.unit_cost  = parseFloat(form.unit_cost);
      if (form.notes.trim())     payload.notes      = form.notes.trim();

      const r: any = await dssAPI.confirmOrder(payload);
      setActionMsg({ text: r.data.message, ok: true });
      setShowConfirmModal(false);

      // Update displayed stock with the actual confirmed quantity
      const confirmedQty = qty || suggestedQty;
      setStock(prev => String((parseInt(prev) || 0) + confirmedQty));
    } catch (e: any) {
      setActionMsg({ text: getApiErrorMessage(e, 'Order confirmation failed'), ok: false });
      setShowConfirmModal(false);
    } finally {
      setConfirmLoading(false);
    }
  };

  const applyPrice = async () => {
    if (!result?.id) return;
    setPriceLoading(true); setActionMsg(null);
    try {
      const r: any = await dssAPI.applyPrice({ report_id: result.id });
      setActionMsg({ text: r.data.message, ok: true });
      if (r.data.new_price) setPrice(r.data.new_price.toFixed(2));
    } catch (e: any) {
      setActionMsg({ text: getApiErrorMessage(e, 'Price update failed'), ok: false });
    } finally {
      setPriceLoading(false);
    }
  };

  const runBacktest = async () => {
    if (!selected) return;
    setBtLoading(true);
    try {
      const r: any = await dssAPI.backtest({
        product_id: selected.id,
        simulation_days: Math.max(7, parseInt(btDays) || 90),
        initial_stock: parseInt(btStock) || 100,
        penalty_under: parseFloat(penaltyUnder) || 5,
      });
      setBacktest(r.data);
    } catch (e: any) {
      setError(getApiErrorMessage(e, 'Backtest failed'));
    } finally {
      setBtLoading(false);
    }
  };

  const startEditReport = (report: any) => {
    setEditingReportId(report.id);
    setEditReasoning(report.ai_reasoning || '');
  };

  const cancelEditReport = () => { setEditingReportId(null); setEditReasoning(''); };

  const saveReportNote = async () => {
    if (!editingReportId) return;
    try {
      await dssAPI.updateReport(editingReportId, { ai_reasoning: editReasoning });
      if (selected) {
        const r: any = await dssAPI.reports(selected.id, 5);
        setHistory(r.data || []);
      }
      cancelEditReport();
    } catch (e: any) {
      setError(getApiErrorMessage(e, 'Update report failed'));
    }
  };

  const deleteReport = async (reportId: number) => {
    try {
      await dssAPI.deleteReport(reportId);
      if (selected) {
        const r: any = await dssAPI.reports(selected.id, 5);
        setHistory(r.data || []);
      }
    } catch (e: any) {
      setError(getApiErrorMessage(e, 'Delete report failed'));
    }
  };

  const forecastSeries = useMemo(() => {
    const d = result?.forecast_data;
    if (!d?.dates) return [];
    return d.dates.map((date: string, i: number) => ({
      date: date.slice(5),
      yhat:  +(d.yhat?.[i]  ?? 0).toFixed(2),
      lower: +(d.yhat_lower?.[i] ?? d.yhat?.[i] ?? 0).toFixed(2),
      upper: +(d.yhat_upper?.[i] ?? d.yhat?.[i] ?? 0).toFixed(2),
    }));
  }, [result]);

  const inv       = result?.inventory_advice || {};
  const price_adv = result?.pricing_advice   || {};
  const [invColor]   = getColor(inv.action);
  const [priceColor] = getColor(price_adv.action);
  const suggestedQty = inv.suggested_order_qty ?? inv.qty_to_order ?? 0;
  const needsOrder   = inv.action === 'ORDER_NOW' || inv.action === 'LOW_STOCK';

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.text, fontFamily: "'DM Sans', system-ui, sans-serif", padding: '28px 32px' }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
        @keyframes spin   { to { transform: rotate(360deg); } }
        @keyframes fadeUp { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: ${C.bg}; } ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 3px; }
        select option { background: ${C.surface}; color: ${C.text}; }
      `}</style>

      {/* ── Confirm Order Modal ── */}
      {showConfirmModal && (
        <ConfirmOrderModal
          suggestedQty={suggestedQty}
          loading={confirmLoading}
          onConfirm={confirmOrder}
          onCancel={() => setShowConfirmModal(false)}
        />
      )}
      {forecastLimitModal && (
        <div
          onClick={() => setForecastLimitModal(null)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.45)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 210,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: C.surface,
              borderRadius: 14,
              border: `1px solid ${C.border}`,
              boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
              width: 460,
              maxWidth: '90vw',
              padding: 22,
            }}
          >
            <p style={{ margin: 0, fontSize: 16, fontWeight: 800, color: C.text }}>Forecast Days limit</p>
            <p style={{ margin: '10px 0 0', fontSize: 13, color: C.muted, lineHeight: 1.55 }}>
              Forecast Days must be between <b style={{ color: C.text }}>7</b> and <b style={{ color: C.text }}>90</b>.
              Your input was auto-adjusted from <b style={{ color: C.warn }}>{forecastLimitModal.entered}</b> to{' '}
              <b style={{ color: C.accent }}>{forecastLimitModal.adjusted}</b>. Please review and click Run DSS Analysis again.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
              <button
                onClick={() => setForecastLimitModal(null)}
                style={{
                  padding: '9px 18px',
                  borderRadius: 8,
                  border: 'none',
                  background: C.accent,
                  color: '#fff',
                  fontWeight: 700,
                  fontSize: 13,
                  cursor: 'pointer',
                }}
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <div style={{ marginBottom: 28, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, padding: '6px 12px', borderRadius: 999, background: '#eef2ff', border: `1px solid ${C.border}` }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.accent }} />
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.accent }}>Decision Studio</span>
          </div>
          <h1 style={{ margin: '8px 0 0', fontSize: 26, fontWeight: 800, letterSpacing: '-0.5px' }}>Analysis</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.muted }}>
            Prophet + XGBoost hybrid · Velocity pricing · Inventory optimization
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6, background: C.surface, padding: 4, borderRadius: 10, border: `1px solid ${C.border}` }}>
          {(['analysis', 'backtest', 'history'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '7px 16px', borderRadius: 7, border: 'none', fontSize: 12, fontWeight: 700,
              cursor: 'pointer', letterSpacing: '0.04em', textTransform: 'capitalize',
              background: tab === t ? C.accent : 'transparent',
              color: tab === t ? '#fff' : C.muted,
              transition: 'all 0.15s',
            }}>{t}</button>
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 20 }}>

        {/* ── LEFT: Product + Params ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card>
            <Label>Select Product</Label>
            <select
              value={selected?.id || ''}
              onChange={e => {
                const p = products.find(p => p.id === parseInt(e.target.value));
                if (p) selectProduct(p);
              }}
              style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: `1px solid ${C.border}`, background: '#ffffff', color: C.text, fontSize: 13, outline: 'none' }}
            >
              <option value="">Choose a product…</option>
              {products.map(p => (
                <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
              ))}
            </select>

            {selected && (
              <div style={{ marginTop: 14, padding: 12, background: '#f8fafc', borderRadius: 9, border: `1px solid ${C.border}` }}>
                <p style={{ margin: '0 0 8px', fontWeight: 700, fontSize: 14 }}>{selected.name}</p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 12 }}>
                  {[
                    ['Stock', selected.current_stock ?? 0],
                    ['Price', `$${selected.current_price?.toFixed(2)}`],
                    ['7d Sales', selected.sales_7d ?? 0],
                    ['Category', selected.category_name || '—'],
                  ].map(([k, v]) => (
                    <div key={k as string}>
                      <span style={{ color: C.muted }}>{k}: </span>
                      <span style={{ fontWeight: 600 }}>{v as string}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>

          <Card>
            <p style={{ margin: '0 0 14px', fontWeight: 700, fontSize: 13, color: C.subtle }}>Analysis Parameters</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Input label="Current Stock" type="number" value={stock} onChange={(e: any) => setStock(e.target.value)} placeholder="e.g. 150" />
              <Input label="Current Price ($)" type="number" step="0.01" value={price} onChange={(e: any) => setPrice(e.target.value)} placeholder="e.g. 49.99" />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <Input label="Target Days" type="number" value={targetDays} onChange={(e: any) => setTargetDays(e.target.value)} />
                <Input label="Forecast Days" type="number" min="7" max="90" value={forecastDays} onChange={(e: any) => setForecastDays(e.target.value)} />
              </div>
              <Input label="Penalty Under-forecast" type="number" step="0.5" value={penaltyUnder} onChange={(e: any) => setPenaltyUnder(e.target.value)} placeholder="5.0" />
            </div>

            <button
              onClick={runAnalysis}
              disabled={!selected || loading}
              style={{
                marginTop: 18, width: '100%', padding: '12px 0', borderRadius: 9,
                background: !selected || loading ? '#e2e8f0' : C.accent,
                color: !selected || loading ? C.muted : '#fff',
                border: 'none', fontWeight: 800, fontSize: 14,
                cursor: !selected || loading ? 'not-allowed' : 'pointer',
                letterSpacing: '0.02em', transition: 'opacity 0.15s',
              }}
            >
              {loading ? 'Running…' : '▶ Run DSS Analysis'}
            </button>
          </Card>

          {/* Manager actions — shown after analysis */}
          {result && tab === 'analysis' && (
            <Card style={{ animation: 'fadeUp 0.3s ease' }}>
              <p style={{ margin: '0 0 12px', fontWeight: 700, fontSize: 14, color: C.subtle }}>Manager Actions</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {needsOrder ? (
                  <Btn variant="success" disabled={confirmLoading} onClick={openConfirmModal}>
                    {confirmLoading ? 'Processing…' : `✔ Confirm Order (+${suggestedQty} units)`}
                  </Btn>
                ) : (
                  <Btn variant="ghost" disabled>
                    ✔ Stock OK — No Order Needed
                  </Btn>
                )}
                {price_adv.action && price_adv.action !== 'HOLD' ? (
                  <Btn variant="primary" disabled={priceLoading} onClick={applyPrice}>
                    {priceLoading ? 'Applying…' : `$ Apply Price → $${price_adv.suggested_price?.toFixed(2)}`}
                  </Btn>
                ) : (
                  <Btn variant="ghost" disabled>
                    $ Price is Optimal
                  </Btn>
                )}
              </div>
              {actionMsg && (
                <div style={{
                  marginTop: 10, padding: '10px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600,
                  background: actionMsg.ok ? '#10b98115' : '#ef444415',
                  color: actionMsg.ok ? C.success : C.danger,
                  border: `1px solid ${actionMsg.ok ? C.success : C.danger}33`,
                  animation: 'fadeUp 0.2s ease',
                }}>
                  {actionMsg.ok ? '✓' : '✕'} {actionMsg.text}
                </div>
              )}
            </Card>
          )}
        </div>

        {/* ── RIGHT: Main content ── */}
        <div>

          {/* ══ TAB: ANALYSIS ══ */}
          {tab === 'analysis' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

              {error && (
                <div style={{ padding: '14px 18px', background: '#ef444415', border: `1px solid ${C.danger}44`, borderRadius: 10, color: C.danger, fontSize: 13, fontWeight: 600 }}>
                  ⚠ {error}
                </div>
              )}

              {!selected && !error && (
                <Card style={{ textAlign: 'center', padding: 60 }}>
                  <p style={{ fontSize: 32, margin: '0 0 12px' }}>🎯</p>
                  <p style={{ color: C.subtle, fontSize: 15, fontWeight: 600, margin: 0 }}>Select a product and run analysis</p>
                  <p style={{ color: C.muted, fontSize: 13, margin: '6px 0 0' }}>Requires ≥ 30 days of sales history</p>
                </Card>
              )}

              {loading && <Card><Spinner /></Card>}

              {result && !loading && (
                <>
                  {/* KPI row */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, animation: 'fadeUp 0.3s ease' }}>
                    <div style={{ padding: '18px 20px', background: C.surface, border: `1px solid ${invColor}33`, borderRadius: 12 }}>
                      <Label>Inventory Action</Label>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
                        <p style={{ margin: 0, fontSize: 22, fontWeight: 800, color: invColor }}>{inv.action || 'N/A'}</p>
                        <span style={tag(invColor, invColor + '22', inv.urgency ?? '')}>{inv.urgency ?? ''}</span>
                      </div>
                      <div style={{ marginTop: 10, fontSize: 13, color: C.subtle, display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <span>ROP: <b style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>{inv.reorder_point ?? 0}</b></span>
                        <span>Safety stock: <b style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>{inv.safety_stock ?? 0}</b></span>
                        <span>Days of supply: <b style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>{inv.days_of_supply ?? '—'}</b></span>
                      </div>
                    </div>

                    <div style={{ padding: '18px 20px', background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12 }}>
                      <Label>Order Recommendation</Label>
                      <p style={{ margin: '6px 0 0', fontSize: 26, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace', color: invColor }}>
                        {suggestedQty} <span style={{ fontSize: 14, fontWeight: 500, color: C.muted }}>units</span>
                      </p>
                      <div style={{ marginTop: 10, fontSize: 13, color: C.subtle, display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <span>Stockout risk: <b style={{ color: inv.stockout_probability > 50 ? C.danger : C.success, fontFamily: 'JetBrains Mono, monospace' }}>{inv.stockout_probability ?? 0}%</b></span>
                        <span>Demand {forecastDays}d: <b style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>{inv.expected_demand_30d ?? '—'}</b></span>
                        <span>Velocity: <b style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>{inv.current_daily_velocity ?? '—'}/day</b></span>
                      </div>
                    </div>

                    <div style={{ padding: '18px 20px', background: C.surface, border: `1px solid ${priceColor}33`, borderRadius: 12 }}>
                      <Label>Pricing</Label>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
                        <p style={{ margin: 0, fontSize: 22, fontWeight: 800, color: priceColor }}>{price_adv.action || 'N/A'}</p>
                      </div>
                      <div style={{ marginTop: 10, fontSize: 13, color: C.subtle, display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <span>Current: <b style={{ color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>${price_adv.current_price?.toFixed(2) ?? '—'}</b></span>
                        <span>Suggested: <b style={{ color: priceColor, fontFamily: 'JetBrains Mono, monospace' }}>${price_adv.suggested_price?.toFixed(2) ?? '—'}</b></span>
                        <span>Change: <b style={{ color: priceColor, fontFamily: 'JetBrains Mono, monospace' }}>{(price_adv.adjustment_pct ?? price_adv.change_percent ?? 0) > 0 ? '+' : ''}{price_adv.adjustment_pct ?? price_adv.change_percent ?? 0}%</b></span>
                      </div>
                    </div>
                  </div>

                  {/* Forecast chart */}
                  {forecastSeries.length > 0 && (
                    <Card style={{ animation: 'fadeUp 0.35s ease' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                        <div>
                          <p style={{ margin: 0, fontWeight: 700, fontSize: 15 }}>Demand Forecast</p>
                          <p style={{ margin: '2px 0 0', fontSize: 13, color: C.muted }}>Prophet + XGBoost hybrid · {forecastSeries.length} days · shaded area = confidence interval</p>
                        </div>
                        <span style={tag(C.accentLt, C.accent + '18', result.parameters?.penalty_under ? `penalty=${result.parameters.penalty_under}` : 'hybrid')}>
                          {result.parameters?.penalty_under ? `penalty=${result.parameters.penalty_under}` : 'hybrid'}
                        </span>
                      </div>
                      <ResponsiveContainer width="100%" height={230}>
                        <AreaChart data={forecastSeries} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                          <defs>
                            <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor={C.accent} stopOpacity={0.25} />
                              <stop offset="95%" stopColor={C.accent} stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                          <XAxis dataKey="date" tick={{ fontSize: 11, fill: C.muted }} tickLine={false} axisLine={false} interval={Math.floor(forecastSeries.length / 6)} />
                          <YAxis tick={{ fontSize: 11, fill: C.muted }} tickLine={false} axisLine={false} />
                          <Tooltip content={<ChartTooltip />} />
                          <Area type="monotone" dataKey="upper" stroke="transparent" fill="url(#grad)" name="Upper" />
                          <Area type="monotone" dataKey="lower" stroke="transparent" fill={C.bg} name="Lower" />
                          <Line type="monotone" dataKey="yhat" stroke={C.accent} strokeWidth={2.5} dot={false} name="Forecast" />
                        </AreaChart>
                      </ResponsiveContainer>
                    </Card>
                  )}

                  {/* Pricing reason + AI narrative */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, animation: 'fadeUp 0.4s ease' }}>
                    <Card>
                      <Label>Pricing Reason</Label>
                      <p style={{ margin: '8px 0 0', fontSize: 14, color: C.subtle, lineHeight: 1.6 }}>
                        {price_adv.reason || '—'}
                      </p>
                      <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: C.muted }}>Velocity ratio</span>
                          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>{price_adv.velocity_ratio ?? '—'}x</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: C.muted }}>Target velocity</span>
                          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>{price_adv.target_velocity ?? '—'}/day</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: C.muted }}>Actual velocity</span>
                          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>{price_adv.actual_velocity ?? '—'}/day</span>
                        </div>
                        {price_adv.guardrail_note && (
                          <p style={{ margin: '6px 0 0', color: C.warn, fontSize: 12 }}>⚡ {price_adv.guardrail_note}</p>
                        )}
                      </div>
                    </Card>

                    <Card style={{ background: '#eef2ff', border: '1px solid #c7d2fe' }}>
                      <Label>AI Narrative</Label>
                      <p style={{
                        margin: '8px 0 0',
                        padding: '10px 12px',
                        borderRadius: 8,
                        background: 'rgba(255,255,255,0.75)',
                        border: '1px solid #dbeafe',
                        fontSize: 13,
                        color: '#334155',
                        lineHeight: 1.8,
                        whiteSpace: 'pre-line',
                        fontFamily: 'JetBrains Mono, monospace',
                        fontWeight: 600,
                      }}>
                        {result.ai_reasoning || '—'}
                      </p>
                    </Card>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ══ TAB: BACKTEST ══ */}
          {tab === 'backtest' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

              {salesMeta ? (
                <div style={{ borderRadius: 12, border: `1px solid ${C.border}`, overflow: 'hidden', animation: 'fadeUp 0.25s ease' }}>
                  <div style={{ padding: '12px 20px', background: '#eef2ff', borderBottom: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: C.accent }}>📅 Dataset: {selected?.name}</span>
                      <span style={{ fontSize: 11, color: C.muted, fontFamily: 'JetBrains Mono, monospace' }}>{salesMeta.firstDate} → {salesMeta.lastDate}</span>
                    </div>
                    <span style={{ fontSize: 12, color: C.muted, fontFamily: 'JetBrains Mono, monospace' }}>{salesMeta.totalDays} days total</span>
                  </div>
                  <div style={{ padding: '16px 20px', background: C.surface }}>
                    <div style={{ display: 'flex', height: 28, borderRadius: 6, overflow: 'hidden', marginBottom: 10 }}>
                      <div style={{ width: '70%', background: `linear-gradient(90deg, ${C.accent}cc, ${C.accent})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: '#fff', letterSpacing: '0.04em' }}>
                        TRAIN — 70% ({salesMeta.trainDays} days)
                      </div>
                      <div style={{ width: '30%', background: `linear-gradient(90deg, ${C.warn}, ${C.warn}cc)`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: '#fff', letterSpacing: '0.04em' }}>
                        TEST — 30% ({salesMeta.testDays} days)
                      </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '70% 30%', fontSize: 11 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', paddingRight: 8 }}>
                        <span style={{ color: C.muted }}>Train start: <b style={{ color: C.accent, fontFamily: 'JetBrains Mono, monospace' }}>{salesMeta.trainStart}</b></span>
                        <span style={{ color: C.muted }}>Train end: <b style={{ color: C.accent, fontFamily: 'JetBrains Mono, monospace' }}>{salesMeta.trainEnd}</b></span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', paddingLeft: 8 }}>
                        <span style={{ color: C.muted }}>Test start: <b style={{ color: C.warn, fontFamily: 'JetBrains Mono, monospace' }}>{salesMeta.testStart}</b></span>
                        <span style={{ color: C.muted }}>Test end: <b style={{ color: C.warn, fontFamily: 'JetBrains Mono, monospace' }}>{salesMeta.testEnd}</b></span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' as const }}>
                      {[
                        [`📦 Product`, selected?.name ?? '—'],
                        [`📊 Total days`, `${salesMeta.totalDays}`],
                        [`🎓 Train period`, `${salesMeta.trainStart} → ${salesMeta.trainEnd}`],
                        [`🧪 Test period`, `${salesMeta.testStart} → ${salesMeta.testEnd}`],
                        [`⚙️ Split`, `70% / 30%`],
                      ].map(([k, v]) => (
                        <div key={k} style={{ padding: '4px 10px', borderRadius: 6, background: '#f1f5f9', border: `1px solid ${C.border}`, fontSize: 11 }}>
                          <span style={{ color: C.muted }}>{k}: </span>
                          <span style={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: C.text }}>{v}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : selected ? (
                <div style={{ padding: '12px 16px', borderRadius: 10, background: '#fffbeb', border: `1px solid #fde68a`, fontSize: 13, color: C.warn }}>
                  ⏳ Loading sales data to compute train/test split…
                </div>
              ) : null}

              <Card>
                <p style={{ margin: '0 0 4px', fontWeight: 700, fontSize: 14 }}>Backtest Configuration</p>
                <p style={{ margin: '0 0 16px', fontSize: 12, color: C.muted }}>
                  Model trained on 70% of data, evaluated on the remaining 30% (test period above).
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                  <div>
                    <Label>Simulation Days {salesMeta ? `(30% = ${salesMeta.testDays})` : ''}</Label>
                    <input
                      type="number" value={btDays}
                      onChange={(e: any) => setBtDays(e.target.value)}
                      style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: `1px solid ${C.border}`, background: C.surface, color: C.text, fontSize: 14, outline: 'none', boxSizing: 'border-box' as const }}
                      onFocus={e => e.target.style.borderColor = C.accent}
                      onBlur={e => e.target.style.borderColor = C.border}
                    />
                    {salesMeta && parseInt(btDays) !== salesMeta.testDays && (
                      <p style={{ fontSize: 10, color: C.warn, margin: '4px 0 0' }}>⚠ Overriding auto 30% ({salesMeta.testDays} days)</p>
                    )}
                  </div>
                  <Input label="Initial Stock" type="number" value={btStock} onChange={(e: any) => setBtStock(e.target.value)} />
                  <Input label="Penalty Under" type="number" step="0.5" value={penaltyUnder} onChange={(e: any) => setPenaltyUnder(e.target.value)} />
                </div>
                <div style={{ marginTop: 16 }}>
                  <Btn variant="primary" disabled={!selected || btLoading} onClick={runBacktest}>
                    {btLoading ? 'Simulating…' : '▶ Run Backtest Simulation'}
                  </Btn>
                </div>
              </Card>

              {btLoading && <Card><Spinner /></Card>}

              {backtest && !btLoading && (() => {
                const dd = backtest.daily_data || [];
                const firstDay  = dd[0]?.date ?? salesMeta?.testStart ?? '—';
                const lastDay   = dd[dd.length - 1]?.date ?? salesMeta?.testEnd ?? '—';
                const trainEnd  = salesMeta?.trainEnd ?? '—';
                const improvement = backtest.dss_service_level - backtest.naive_service_level;
                return (
                  <>
                    <div style={{ padding: '14px 20px', borderRadius: 12, background: improvement >= 0 ? '#ecfdf5' : '#fef2f2', border: `1px solid ${improvement >= 0 ? C.success : C.danger}44`, animation: 'fadeUp 0.25s ease', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <p style={{ margin: 0, fontWeight: 700, fontSize: 13, color: improvement >= 0 ? C.success : C.danger }}>
                          {improvement >= 0 ? '✅ DSS outperforms naive strategy' : '⚠ DSS underperformed on this split'}
                        </p>
                        <p style={{ margin: '3px 0 0', fontSize: 12, color: C.muted }}>
                          Test period: <b style={{ fontFamily: 'JetBrains Mono, monospace', color: C.text }}>{firstDay}</b>{' → '}<b style={{ fontFamily: 'JetBrains Mono, monospace', color: C.text }}>{lastDay}</b>
                          {salesMeta && <> &nbsp;·&nbsp; Trained up to <b style={{ fontFamily: 'JetBrains Mono, monospace', color: C.accent }}>{trainEnd}</b></>}
                        </p>
                      </div>
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 800, fontSize: 22, color: improvement >= 0 ? C.success : C.danger }}>
                        {improvement >= 0 ? '+' : ''}{improvement.toFixed(1)}%
                      </span>
                    </div>

                    {backtest.methodology_note && (
                      <div style={{ padding: '12px 16px', borderRadius: 10, fontSize: 12, background: '#f8fafc', border: `1px solid ${C.border}`, color: C.muted, lineHeight: 1.7, animation: 'fadeUp 0.28s ease' }}>
                        <span style={{ fontWeight: 700, color: C.text }}>📋 Methodology: </span>{backtest.methodology_note}
                      </div>
                    )}

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, animation: 'fadeUp 0.3s ease' }}>
                      <StatBox label="Oracle (upper bound)" value={`${backtest.oracle_service_level ?? 100}%`} color={'#a78bfa'} sub={`${backtest.oracle_stockout_days ?? 0} stockout days`} />
                      <StatBox label="DSS Service Level"    value={`${backtest.dss_service_level}%`}           color={C.success} sub={`${backtest.dss_stockout_days} stockout days`} />
                      <StatBox label="Naive Service Level"  value={`${backtest.naive_service_level}%`}         color={C.warn}    sub={`${backtest.naive_stockout_days} stockout days`} />
                      <StatBox label="DSS vs Naive"         value={`${backtest.stockout_reduction_pct > 0 ? '+' : ''}${backtest.stockout_reduction_pct}%`} color={backtest.stockout_reduction_pct >= 0 ? C.success : C.danger} sub="stockout reduction" />
                      <StatBox label="Test Period"          value={`${backtest.simulation_days}d`}             color={C.accentLt} sub={`${firstDay} → ${lastDay}`} />
                    </div>

                    {dd.length > 0 && (
                      <Card style={{ animation: 'fadeUp 0.35s ease' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                          <div>
                            <p style={{ margin: 0, fontWeight: 700, fontSize: 14 }}>Stock Level Simulation: DSS vs Naive</p>
                            <p style={{ margin: '3px 0 0', fontSize: 12, color: C.muted }}>
                              Test window: <b style={{ fontFamily: 'JetBrains Mono, monospace', color: C.text }}>{firstDay}</b>{' → '}<b style={{ fontFamily: 'JetBrains Mono, monospace', color: C.text }}>{lastDay}</b>{' '}({dd.length} days)
                              {salesMeta && <> &nbsp;·&nbsp; Model trained on <b style={{ color: C.accent }}>{salesMeta.trainDays}</b> days prior</>}
                            </p>
                          </div>
                          <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
                            {[
                              { color: '#a78bfa', label: 'Oracle', dash: '2 2' },
                              { color: C.success, label: 'DSS',    dash: '' },
                              { color: C.warn,    label: 'Naive',  dash: '5 3' },
                            ].map(l => (
                              <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <div style={{ width: 24, height: 2, background: l.dash ? `repeating-linear-gradient(90deg, ${l.color} 0px, ${l.color} ${l.dash.split(' ')[0]}px, transparent ${l.dash.split(' ')[0]}px, transparent ${parseInt(l.dash.split(' ')[0]) + parseInt(l.dash.split(' ')[1])}px)` : l.color }} />
                                <span style={{ color: C.muted, fontWeight: 600 }}>{l.label}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <ResponsiveContainer width="100%" height={280}>
                          <LineChart data={dd.map((d: any) => ({ ...d, label: d.date ?? `Day ${d.day}` }))} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                            <XAxis dataKey="label" tick={{ fontSize: 10, fill: C.muted }} tickLine={false} axisLine={false} interval={Math.floor(dd.length / 8)} />
                            <YAxis tick={{ fontSize: 10, fill: C.muted }} tickLine={false} axisLine={false} />
                            <Tooltip content={({ active, payload, label }: any) => {
                              if (!active || !payload?.length) return null;
                              const row = payload[0]?.payload;
                              return (
                                <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: '8px 14px', fontSize: 12 }}>
                                  <p style={{ color: C.muted, margin: '0 0 4px', fontFamily: 'JetBrains Mono, monospace' }}>{row?.date ?? label} {row?.date ? `(Day ${row.day})` : ''}</p>
                                  <p style={{ color: C.muted, margin: '0 0 6px', fontSize: 11 }}>Demand: <b style={{ color: C.text }}>{row?.demand}</b></p>
                                  {payload.map((p: any, i: number) => <p key={i} style={{ color: p.color, margin: '2px 0', fontWeight: 700 }}>{p.name}: {p.value}</p>)}
                                </div>
                              );
                            }} />
                            <ReferenceLine y={0} stroke={C.danger} strokeDasharray="4 4" strokeWidth={1.5} />
                            <Line type="monotone" dataKey="oracle_stock" stroke="#a78bfa" strokeWidth={1.5} dot={false} name="Oracle (upper bound)" strokeDasharray="2 2" />
                            <Line type="monotone" dataKey="dss_stock"    stroke={C.success} strokeWidth={2.5} dot={false} name="DSS (our model)" />
                            <Line type="monotone" dataKey="naive_stock"  stroke={C.warn}    strokeWidth={2}   dot={false} name="Naive baseline" strokeDasharray="5 3" />
                          </LineChart>
                        </ResponsiveContainer>
                      </Card>
                    )}
                  </>
                );
              })()}
            </div>
          )}

          {/* ══ TAB: HISTORY ══ */}
          {tab === 'history' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {!selected ? (
                <Card style={{ textAlign: 'center', padding: 48 }}>
                  <p style={{ color: C.muted, margin: 0 }}>Select a product to view report history</p>
                </Card>
              ) : history.length === 0 ? (
                <Card style={{ textAlign: 'center', padding: 48 }}>
                  <p style={{ color: C.muted, margin: 0 }}>No reports yet for {selected.name}</p>
                </Card>
              ) : (
                history.map((r: any, i: number) => {
                  const inv_h   = r.inventory_advice || {};
                  const price_h = r.pricing_advice   || {};
                  const [ic] = getColor(inv_h.action);
                  const [pc] = getColor(price_h.action);
                  return (
                    <Card key={r.id} style={{ animation: `fadeUp 0.3s ease ${i * 0.05}s both` }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div>
                          <p style={{ margin: 0, fontWeight: 700, fontSize: 13 }}>Report #{r.id}</p>
                          <p style={{ margin: '2px 0 0', fontSize: 11, color: C.muted }}>{r.generated_at?.slice(0, 16).replace('T', ' ')}</p>
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          <span style={tag(ic, ic+'22', inv_h.action || 'N/A')}>{inv_h.action || 'N/A'}</span>
                          <span style={tag(pc, pc+'22', price_h.action || '—')}>{price_h.action || '—'}</span>
                          {editingReportId === r.id ? (
                            <div style={{ display: 'flex', gap: 6 }}>
                              <button onClick={saveReportNote} style={{ padding: '6px 10px', borderRadius: 6, border: 'none', background: C.accent, color: '#fff', fontSize: 11, fontWeight: 700 }}>Save</button>
                              <button onClick={cancelEditReport} style={{ padding: '6px 10px', borderRadius: 6, border: `1px solid ${C.border}`, background: '#fff', color: C.muted, fontSize: 11, fontWeight: 700 }}>Cancel</button>
                            </div>
                          ) : (
                            <div style={{ display: 'flex', gap: 6 }}>
                              <button onClick={() => startEditReport(r)} style={{ padding: '6px 10px', borderRadius: 6, border: `1px solid ${C.border}`, background: '#fff', color: C.muted, fontSize: 11, fontWeight: 700 }}>Edit</button>
                              <button onClick={() => deleteReport(r.id)} style={{ padding: '6px 10px', borderRadius: 6, border: `1px solid #fecaca`, background: '#fef2f2', color: C.danger, fontSize: 11, fontWeight: 700 }}>Delete</button>
                            </div>
                          )}
                        </div>
                      </div>
                      <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, fontSize: 12 }}>
                        {[
                          ['ROP', inv_h.reorder_point],
                          ['Safety Stock', inv_h.safety_stock],
                          ['Order Qty', inv_h.suggested_order_qty],
                          ['Stockout%', `${inv_h.stockout_probability ?? 0}%`],
                          ['Suggested $', `$${price_h.suggested_price?.toFixed(2) ?? '—'}`],
                        ].map(([k, v]) => (
                          <div key={k as string} style={{ padding: '8px 10px', background: '#f8fafc', borderRadius: 7, border: `1px solid ${C.border}` }}>
                            <span style={{ color: C.muted, display: 'block', marginBottom: 3 }}>{k}</span>
                            <span style={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>{v ?? '—'}</span>
                          </div>
                        ))}
                      </div>
                      {editingReportId === r.id ? (
                        <div style={{ marginTop: 12, borderTop: `1px solid ${C.border}`, paddingTop: 10 }}>
                          <Label>Notes</Label>
                          <textarea
                            value={editReasoning}
                            onChange={(e) => setEditReasoning(e.target.value)}
                            rows={4}
                            style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: `1px solid ${C.border}`, background: '#ffffff', color: C.text, fontSize: 12, outline: 'none', resize: 'vertical', fontFamily: 'JetBrains Mono, monospace' }}
                          />
                        </div>
                      ) : (
                        r.ai_reasoning && (
                          <p style={{ margin: '12px 0 0', fontSize: 11, color: C.muted, fontFamily: 'JetBrains Mono, monospace', lineHeight: 1.7, whiteSpace: 'pre-line', borderTop: `1px solid ${C.border}`, paddingTop: 10 }}>
                            {r.ai_reasoning}
                          </p>
                        )
                      )}
                    </Card>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
