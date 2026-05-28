'use client';

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from "recharts";
import { dashboardAPI, productsAPI, inventoryAPI, notificationsAPI } from "@/lib/api";

const fmt    = (n) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n ?? 0);
const fmtNum = (n) => new Intl.NumberFormat("en-US").format(n ?? 0);
const fmtK   = (n) => n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n}`;

const STATUS = {
  in_stock:     { bg: "#ecfdf5", text: "#059669", dot: "#10b981", label: "In Stock" },
  low_stock:    { bg: "#fffbeb", text: "#d97706", dot: "#f59e0b", label: "Low Stock" },
  out_of_stock: { bg: "#fef2f2", text: "#dc2626", dot: "#ef4444", label: "Out of Stock" },
};

const I = {
  Box:       () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m16.5 9.4-9-5.19M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>,
  Dollar:    () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>,
  Alert:     () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  Trend:     () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>,
  Activity:  () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
  ArrowUp:   () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>,
  ArrowDown: () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>,
  Calendar:  () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>,
  Search:    () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  StockIn:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>,
  StockOut:  () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>,
  Tag:       () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>,
  DSS:       () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>,
};

const ACTIVITY_CFG = {
  stock_in:        { icon: <I.StockIn />,  color: "#059669", bg: "#ecfdf5", label: "Restocked" },
  stock_out:       { icon: <I.StockOut />, color: "#dc2626", bg: "#fef2f2", label: "Stock Out" },
  price_change:    { icon: <I.Tag />,      color: "#7c3aed", bg: "#f5f3ff", label: "Price" },
  dss_order:       { icon: <I.DSS />,      color: "#0891b2", bg: "#ecfeff", label: "DSS Order" },
  dss_alert:       { icon: <I.Alert />,    color: "#d97706", bg: "#fffbeb", label: "Alert" },
};

const RevenueTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 10, padding: "10px 14px", fontSize: 13, boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}>
      <p style={{ margin: "0 0 4px", color: "#64748b", fontSize: 12 }}>{d.full_date || label}</p>
      <p style={{ margin: 0, fontWeight: 700, color: "#1a1a2e" }}>{fmt(payload[0].value)}</p>
      {d.quantity && <p style={{ margin: "2px 0 0", color: "#94a3b8", fontSize: 12 }}>{fmtNum(d.quantity)} units sold</p>}
    </div>
  );
};

export default function DashboardPage() {
  const router = useRouter();

  const [summary, setSummary]           = useState(null);
  const [products, setProducts]         = useState([]);
  const [revenueChart, setRevenueChart] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading]           = useState(true);
  const [chartLoading, setChartLoading] = useState(true);
  const [filter, setFilter]             = useState("all");
  const [search, setSearch]             = useState("");
  const [sortCol, setSortCol]           = useState("sales_7d");
  const [sortDir, setSortDir]           = useState("desc");
  const [chartMode, setChartMode]       = useState("revenue"); // revenue | units
  const [anchorDate, setAnchorDate]     = useState(null);
  const [chartDays, setChartDays]       = useState(30);
  const [customFrom, setCustomFrom]     = useState("");
  const [customTo, setCustomTo]         = useState("");
  const [showCustom, setShowCustom]     = useState(false);
  const [chartRevTotal, setChartRevTotal] = useState(0);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [sumRes, prodRes, txnRes] = await Promise.allSettled([
          dashboardAPI.summary(),
          productsAPI.list({ limit: 200, sort_by: "sales_7d", sort_order: "desc" }),
          inventoryAPI.allTransactions({ limit: 30 }),
        ]);
        if (sumRes.status === "fulfilled")  setSummary(sumRes.value.data);
        if (prodRes.status === "fulfilled") setProducts(prodRes.value.data?.items || []);
        if (txnRes.status === "fulfilled")  setTransactions(txnRes.value.data?.items || txnRes.value.data || []);
      } finally {
        setLoading(false);
      }
    };
    load();

    loadChart(30);
  }, []);

  const loadChart = (days, from = "", to = "") => {
    setChartLoading(true);
    const params = from && to
      ? `?from=${from}&to=${to}`
      : `?days=${days}`;
    dashboardAPI.revenueTrendParams(params)
      .then(res => {
        const data = res.data?.data || [];
        setRevenueChart(data);
        if (res.data?.anchor_date) setAnchorDate(res.data.anchor_date);
        setChartRevTotal(data.reduce((s, d) => s + (d.revenue || 0), 0));
      })
      .catch(() => { setRevenueChart([]); setChartRevTotal(0); })
      .finally(() => setChartLoading(false));
  };

  const handlePreset = (days) => {
    setChartDays(days);
    setShowCustom(false);
    setCustomFrom(""); setCustomTo("");
    loadChart(days);
  };

  const handleCustomApply = () => {
    if (customFrom && customTo && customFrom <= customTo) {
      loadChart(0, customFrom, customTo);
      setShowCustom(false);
    }
  };

  const toggleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("desc"); }
  };

  const filtered = products
    .filter(p => {
      if (filter === "low_stock")     return p.stock_status === "low_stock";
      if (filter === "out_of_stock")  return p.stock_status === "out_of_stock";
      if (filter === "high_velocity") return p.sales_7d > 0;
      return true;
    })
    .filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase()) || p.sku.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      const dir = sortDir === "asc" ? 1 : -1;
      if (sortCol === "name")          return dir * a.name.localeCompare(b.name);
      if (sortCol === "current_stock") return dir * (a.current_stock - b.current_stock);
      if (sortCol === "current_price") return dir * (a.current_price - b.current_price);
      if (sortCol === "sales_7d")      return dir * (a.sales_7d - b.sales_7d);
      return 0;
    });

  const lowStockCount = products.filter(p => p.stock_status === "low_stock" || p.stock_status === "out_of_stock").length;
  const outOfStockCount = products.filter(p => p.stock_status === "out_of_stock").length;
  const latestDate = anchorDate || (revenueChart.length > 0 ? revenueChart[revenueChart.length - 1].full_date : null);

  // Derived revenue metrics from chart data
  const totalRevenue30d = revenueChart.reduce((sum, d) => sum + (d.revenue || 0), 0);
  const splitIdx = Math.floor(revenueChart.length / 2);
  const prevWindow = revenueChart.slice(0, splitIdx);
  const currWindow = revenueChart.slice(splitIdx);
  const prevHalf = prevWindow.reduce((s, d) => s + (d.revenue || 0), 0);
  const currHalf = currWindow.reduce((s, d) => s + (d.revenue || 0), 0);
  const prevActiveDays = prevWindow.filter((d) => (d.revenue || 0) > 0).length;
  const currActiveDays = currWindow.filter((d) => (d.revenue || 0) > 0).length;
  const hasComparableTrend =
    prevWindow.length >= 7 &&
    currWindow.length >= 7 &&
    prevActiveDays >= 5 &&
    currActiveDays >= 5 &&
    prevHalf > 0;
  const revenueTrend = hasComparableTrend ? ((currHalf - prevHalf) / prevHalf * 100) : 0;
  const revenueToday = revenueChart.length > 0 ? (revenueChart[revenueChart.length - 1].revenue || 0) : 0;

  // Top 5 selling products for bar chart
  const topProducts = [...products]
    .filter(p => p.sales_7d > 0)
    .sort((a, b) => b.sales_7d - a.sales_7d)
    .slice(0, 6);

  // Build activity feed from inventory transactions
  const activityFeed = transactions.slice(0, 12).map(txn => {
    const isIn = txn.type === "IN" || txn.type === "stock_in";
    return {
      id: txn.id,
      type: isIn ? "stock_in" : "stock_out",
      label: isIn ? `+${fmtNum(txn.quantity)} units restocked` : `-${fmtNum(txn.quantity)} units`,
      product: txn.product_name || txn.reference || "—",
      time: txn.created_at ? new Date(txn.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—",
      note: txn.notes || txn.reference || "",
    };
  });

  return (
    <div style={{ fontFamily: "'DM Sans', 'Segoe UI', system-ui, sans-serif", background: "#f8f9fb", minHeight: "100vh", color: "#1a1a2e" }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />

      <main style={{ maxWidth: 1400, margin: "0 auto", padding: "32px 40px" }}>

        {/* Data anchor notice */}
        {latestDate && (
          <div style={{ marginBottom: 20, padding: "10px 16px", borderRadius: 10, background: "#eff6ff", border: "1px solid #bfdbfe", display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#1d4ed8" }}>
            <I.Calendar />
            <span>Data anchored to latest DB date: <strong>{latestDate}</strong> — all windows are relative to this date, not today.</span>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20, marginBottom: 28 }}>
          {[
            {
              icon: <I.Box />,    color: "#6366f1", bg: "#eef2ff",
              label: "Total Products",
              value: fmtNum(summary?.total_products || 0),
              sub: `${fmtNum(products.filter(p => p.stock_status === "in_stock").length)} in stock`,
            },
            {
              icon: <I.Dollar />, color: "#059669", bg: "#ecfdf5",
              label: "Inventory Value",
              value: fmt(summary?.total_inventory_value || 0),
              sub: `${fmtNum(products.reduce((s, p) => s + p.current_stock, 0))} units on hand`,
            },
            {
              icon: <I.Alert />,  color: "#d97706", bg: "#fffbeb",
              label: "Stock Alerts",
              value: String(lowStockCount),
              sub: `${outOfStockCount} out of stock`,
              urgent: outOfStockCount > 0,
            },
            {
              icon: <I.Trend />,  color: "#0891b2", bg: "#ecfeff",
              label: (() => {
                if (customFrom && customTo) return `Revenue ${customFrom} → ${customTo}`;
                const end = latestDate || "—";
                const startDate = revenueChart.length > 0 ? revenueChart[0].full_date : "—";
                return `Revenue ${startDate} → ${end}`;
              })(),
              value: fmt(chartRevTotal || totalRevenue30d || summary?.revenue_month || 0),
              sub: hasComparableTrend
                ? `${revenueTrend > 0 ? "▲" : "▼"} ${Math.abs(revenueTrend).toFixed(1)}% vs prev half`
                : `${fmt(revenueToday || summary?.revenue_today || 0)} on ${latestDate || "latest day"}`,
              trendUp: hasComparableTrend && revenueTrend > 0,
              trendDown: hasComparableTrend && revenueTrend < 0,
            },
          ].map((card, i) => (
            <div key={i} style={{
              background: "white", borderRadius: 16, padding: "22px 24px",
              border: card.urgent ? "1px solid #fde68a" : "1px solid #e8eaef",
              boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
              animation: `fadeSlideUp 0.5s ease ${i * 0.07}s both`,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 12, color: "#64748b", margin: 0, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.4px" }}>{card.label}</p>
                  <p style={{ fontSize: 26, fontWeight: 700, margin: "6px 0 0", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "-0.5px" }}>{card.value}</p>
                  {card.sub && (
                    <p style={{ fontSize: 12, margin: "4px 0 0", color: card.trendUp ? "#059669" : card.trendDown ? "#dc2626" : "#94a3b8", fontWeight: card.trendUp || card.trendDown ? 600 : 400 }}>
                      {card.sub}
                    </p>
                  )}
                </div>
                <div style={{ background: card.bg, color: card.color, borderRadius: 12, padding: 10, flexShrink: 0 }}>{card.icon}</div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20, marginBottom: 20 }}>

          {/* Revenue / Units chart */}
          <div style={{ background: "white", borderRadius: 16, padding: "24px", border: "1px solid #e8eaef" }}>
            {/* Chart header: title + date range picker + metric toggle */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Sales History</h3>
                <p style={{ fontSize: 12, color: "#94a3b8", margin: "2px 0 0" }}>
                  {revenueChart.length > 0
                    ? <><strong>{revenueChart[0].full_date}</strong> → <strong>{revenueChart[revenueChart.length-1].full_date}</strong> · {revenueChart.length} days</>
                    : "No data"
                  }
                </p>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                {/* Preset buttons */}
                <div style={{ display: "flex", gap: 4 }}>
                  {[7, 30, 90].map(d => (
                    <button key={d} onClick={() => handlePreset(d)} style={{
                      padding: "4px 10px", borderRadius: 7, border: "1px solid",
                      borderColor: chartDays === d && !customFrom ? "#6366f1" : "#e2e8f0",
                      background:  chartDays === d && !customFrom ? "#eef2ff" : "white",
                      color:       chartDays === d && !customFrom ? "#6366f1" : "#64748b",
                      fontSize: 12, fontWeight: 600, cursor: "pointer",
                    }}>{d}d</button>
                  ))}
                  {/* Custom range button */}
                  <button onClick={() => setShowCustom(v => !v)} style={{
                    padding: "4px 10px", borderRadius: 7, border: "1px solid",
                    borderColor: (customFrom && customTo) ? "#6366f1" : "#e2e8f0",
                    background:  (customFrom && customTo) ? "#eef2ff" : "white",
                    color:       (customFrom && customTo) ? "#6366f1" : "#64748b",
                    fontSize: 12, fontWeight: 600, cursor: "pointer",
                  }}>
                    {customFrom && customTo ? `${customFrom.slice(5)} → ${customTo.slice(5)}` : "Custom"}
                  </button>
                </div>
                {/* Metric toggle */}
                <div style={{ display: "flex", gap: 4, borderLeft: "1px solid #e2e8f0", paddingLeft: 8 }}>
                  {[["revenue", "$"], ["units", "qty"]].map(([mode, lbl]) => (
                    <button key={mode} onClick={() => setChartMode(mode)} style={{
                      padding: "4px 10px", borderRadius: 7, border: "1px solid",
                      borderColor: chartMode === mode ? "#6366f1" : "#e2e8f0",
                      background:  chartMode === mode ? "#eef2ff" : "white",
                      color:       chartMode === mode ? "#6366f1" : "#64748b",
                      fontSize: 12, fontWeight: 600, cursor: "pointer",
                    }}>{lbl}</button>
                  ))}
                </div>
              </div>
            </div>

            {/* Custom date range picker — shown inline */}
            {showCustom && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, padding: "10px 14px", background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0" }}>
                <span style={{ fontSize: 12, color: "#64748b", fontWeight: 500 }}>From</span>
                <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)}
                  style={{ padding: "5px 10px", borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 13, outline: "none", cursor: "pointer" }} />
                <span style={{ fontSize: 12, color: "#64748b", fontWeight: 500 }}>To</span>
                <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)}
                  style={{ padding: "5px 10px", borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 13, outline: "none", cursor: "pointer" }} />
                <button onClick={handleCustomApply} disabled={!customFrom || !customTo || customFrom > customTo}
                  style={{ padding: "5px 14px", borderRadius: 8, border: "none", background: "#6366f1", color: "white", fontSize: 12, fontWeight: 700, cursor: "pointer", opacity: (!customFrom || !customTo || customFrom > customTo) ? 0.5 : 1 }}>
                  Apply
                </button>
                <button onClick={() => { setCustomFrom(""); setCustomTo(""); setShowCustom(false); handlePreset(chartDays); }}
                  style={{ padding: "5px 10px", borderRadius: 8, border: "1px solid #e2e8f0", background: "white", color: "#64748b", fontSize: 12, cursor: "pointer" }}>
                  Reset
                </button>
              </div>
            )}

            {chartLoading ? (
              <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "#94a3b8" }}>Loading…</div>
            ) : revenueChart.length === 0 ? (
              <div style={{ height: 200, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#94a3b8", gap: 8 }}>
                <p style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>No sales history data</p>
                <p style={{ margin: 0, fontSize: 13 }}>Import sales CSV to populate this chart</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={210}>
                <AreaChart data={revenueChart} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.15}/>
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval={Math.floor(revenueChart.length / 6)} />
                  <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} tickFormatter={chartMode === "revenue" ? fmtK : v => fmtNum(v)} />
                  <Tooltip content={<RevenueTooltip />} />
                  <Area
                    type="monotone"
                    dataKey={chartMode === "revenue" ? "revenue" : "quantity"}
                    stroke="#6366f1" strokeWidth={2.5}
                    fill="url(#revGrad)" dot={false} activeDot={{ r: 5, strokeWidth: 0, fill: "#6366f1" }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Top selling products mini bar chart */}
          <div style={{ background: "white", borderRadius: 16, padding: "24px", border: "1px solid #e8eaef" }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 4px" }}>Top Products</h3>
            <p style={{ fontSize: 12, color: "#94a3b8", margin: "0 0 16px" }}>By units sold last 7 days</p>
            {topProducts.length === 0 ? (
              <div style={{ color: "#94a3b8", fontSize: 13, textAlign: "center", paddingTop: 40 }}>No sales data yet</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {topProducts.map((p, i) => {
                  const pct = Math.max(4, (p.sales_7d / topProducts[0].sales_7d) * 100);
                  const colors = ["#6366f1", "#8b5cf6", "#0891b2", "#059669", "#d97706", "#ec4899"];
                  return (
                    <div key={p.id} style={{ cursor: "pointer" }} onClick={() => router.push(`/dss?product_id=${p.id}`)}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <span style={{ fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 180 }}>{p.name}</span>
                        <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: colors[i], flexShrink: 0 }}>{fmtNum(p.sales_7d)}</span>
                      </div>
                      <div style={{ height: 6, background: "#f1f5f9", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{ width: `${pct}%`, height: "100%", background: colors[i], borderRadius: 3, transition: "width 0.8s ease" }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>

          {/* Low Stock Alerts */}
          <div style={{ background: "white", borderRadius: 16, padding: "24px", border: "1px solid #e8eaef" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "#f59e0b" }}><I.Alert /></span> Stock Alerts
              </h3>
              {lowStockCount > 0 && (
                <span style={{ fontSize: 12, background: "#fef2f2", color: "#dc2626", padding: "3px 10px", borderRadius: 20, fontWeight: 700 }}>
                  {lowStockCount} need attention
                </span>
              )}
            </div>
            {products.filter(p => p.stock_status !== "in_stock").length === 0 ? (
              <div style={{ textAlign: "center", padding: "24px 0", color: "#059669" }}>
                <p style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>✅ All products healthy</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 280, overflowY: "auto" }}>
                {(() => {
                  // Merge products list with velocity data from summary.low_stock_alerts
                  const alertMap = {};
                  (summary?.low_stock_alerts || []).forEach(a => {
                    alertMap[a.product_id] = a;
                  });
                  return products.filter(p => p.stock_status !== "in_stock")
                    .sort((a, b) => (a.stock_status === "out_of_stock" ? -1 : 1))
                    .map(p => {
                      const s = STATUS[p.stock_status];
                      const alertData = alertMap[p.id];
                      // Prefer days_until_stockout from backend (uses correct anchor_date)
                      // Fallback: derive from sales_7d when available
                      const daysLeft = alertData?.days_until_stockout
                        ?? (p.sales_7d > 0 ? Math.floor(p.current_stock / (p.sales_7d / 7)) : null);
                      const velocity = alertData?.daily_velocity;
                      return (
                        <div key={p.id} onClick={() => router.push(`/dss?product_id=${p.id}`)}
                          style={{ padding: "11px 14px", borderRadius: 10, border: `1px solid ${p.stock_status === "out_of_stock" ? "#fecaca" : "#fde68a"}`, background: s.bg, cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <div>
                            <p style={{ fontSize: 13, fontWeight: 600, margin: 0 }}>{p.name}</p>
                            <p style={{ fontSize: 11, color: "#64748b", margin: "2px 0 0" }}>
                              {daysLeft !== null
                                ? <span>~<strong>{daysLeft}d</strong> remaining{velocity ? ` · ${velocity.toFixed(1)} units/day` : ""}</span>
                                : <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{p.sku}</span>
                              }
                            </p>
                          </div>
                          <div style={{ textAlign: "right", flexShrink: 0 }}>
                            <p style={{ fontSize: 18, fontWeight: 700, margin: 0, fontFamily: "'JetBrains Mono', monospace", color: s.text }}>{fmtNum(p.current_stock)}</p>
                            <p style={{ fontSize: 11, color: s.text, margin: "1px 0 0" }}>{s.label}</p>
                          </div>
                        </div>
                      );
                    });
                })()}
              </div>
            )}
          </div>

          {/* Activity Feed — inventory transactions */}
          <div style={{ background: "white", borderRadius: 16, padding: "24px", border: "1px solid #e8eaef" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "#6366f1" }}><I.Activity /></span> Recent Activity
              </h3>
              <span style={{ fontSize: 12, color: "#94a3b8" }}>Inventory transactions</span>
            </div>
            {activityFeed.length === 0 ? (
              <div style={{ textAlign: "center", padding: "24px 0", color: "#94a3b8" }}>
                <p style={{ margin: 0, fontSize: 14 }}>No recent transactions</p>
                <p style={{ margin: "4px 0 0", fontSize: 12 }}>Confirm DSS orders or adjust stock to see activity</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 280, overflowY: "auto" }}>
                {activityFeed.map((act, i) => {
                  const cfg = ACTIVITY_CFG[act.type] || ACTIVITY_CFG.stock_in;
                  return (
                    <div key={act.id || i} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "9px 12px", borderRadius: 10, background: "#f8fafc", border: "1px solid #f1f5f9" }}>
                      <div style={{ width: 28, height: 28, borderRadius: 8, background: cfg.bg, color: cfg.color, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        {cfg.icon}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                          <p style={{ fontSize: 13, fontWeight: 600, margin: 0, color: cfg.color }}>{act.label}</p>
                          <span style={{ fontSize: 11, color: "#94a3b8", flexShrink: 0, marginLeft: 8 }}>{act.time}</span>
                        </div>
                        <p style={{ fontSize: 12, color: "#64748b", margin: "1px 0 0", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{act.product}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div style={{ background: "white", borderRadius: 16, border: "1px solid #e8eaef", overflow: "hidden" }}>
          <div style={{ padding: "18px 24px", borderBottom: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ display: "flex", gap: 6 }}>
              {[
                { key: "all",          label: "All" },
                { key: "low_stock",    label: "Low Stock" },
                { key: "out_of_stock", label: "Out of Stock" },
                { key: "high_velocity", label: "Active" },
              ].map(f => (
                <button key={f.key} onClick={() => setFilter(f.key)} style={{
                  padding: "5px 12px", borderRadius: 8, border: "1px solid",
                  borderColor: filter === f.key ? "#6366f1" : "#e2e8f0",
                  background:  filter === f.key ? "#eef2ff" : "white",
                  color:       filter === f.key ? "#6366f1" : "#64748b",
                  fontWeight:  filter === f.key ? 600 : 400,
                  fontSize: 12, cursor: "pointer",
                }}>{f.label}</button>
              ))}
            </div>
            <div style={{ position: "relative" }}>
              <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#94a3b8" }}><I.Search /></span>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search…"
                style={{ padding: "7px 12px 7px 32px", borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 13, width: 200, outline: "none" }}
                onFocus={e => e.target.style.borderColor = "#6366f1"}
                onBlur={e => e.target.style.borderColor = "#e2e8f0"}
              />
            </div>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ background: "#f8fafc" }}>
                  {[
                    { key: "name",          label: "Product" },
                    { key: null,            label: "Status" },
                    { key: "current_stock", label: "Stock" },
                    { key: "current_price", label: "Price" },
                    { key: "sales_7d",      label: "7d Sales" },
                    { key: null,            label: "Stock Value" },
                    { key: null,            label: "" },
                  ].map((col, i) => (
                    <th key={i} onClick={() => col.key && toggleSort(col.key)} style={{
                      padding: "11px 16px", textAlign: "left", fontWeight: 600, color: "#64748b",
                      fontSize: 11, textTransform: "uppercase", letterSpacing: "0.5px",
                      cursor: col.key ? "pointer" : "default", whiteSpace: "nowrap",
                    }}>
                      {col.label}
                      {col.key && sortCol === col.key && <span style={{ marginLeft: 4 }}>{sortDir === "asc" ? "↑" : "↓"}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((p, i) => {
                  const s = STATUS[p.stock_status];
                  const stockValue = p.current_stock * p.current_price;
                  const priceChanged = p.current_price !== p.base_price;
                  const priceUp = p.current_price > p.base_price;
                  return (
                    <tr key={p.id} style={{ borderBottom: "1px solid #f1f5f9", cursor: "pointer", animation: `fadeSlideUp 0.35s ease ${Math.min(i, 10) * 0.025}s both` }}
                      onMouseEnter={e => e.currentTarget.style.background = "#f8fafc"}
                      onMouseLeave={e => e.currentTarget.style.background = "white"}
                    >
                      <td style={{ padding: "12px 16px" }}>
                        <p style={{ fontWeight: 600, margin: 0, whiteSpace: "nowrap" }}>{p.name}</p>
                        <p style={{ fontSize: 11, color: "#94a3b8", margin: "1px 0 0", fontFamily: "'JetBrains Mono', monospace" }}>{p.sku}</p>
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: s.bg, color: s.text }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot }} /> {s.label}
                        </span>
                      </td>
                      <td style={{ padding: "12px 16px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{fmtNum(p.current_stock)}</td>
                      <td style={{ padding: "12px 16px" }}>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>${Number(p.current_price).toFixed(2)}</span>
                        {priceChanged && (
                          <span style={{ fontSize: 10, marginLeft: 5, color: priceUp ? "#059669" : "#dc2626", fontWeight: 700 }}>
                            {priceUp ? "▲" : "▼"}{Math.abs(((p.current_price - p.base_price) / p.base_price) * 100).toFixed(0)}%
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ width: 52, height: 5, borderRadius: 3, background: "#f1f5f9", overflow: "hidden" }}>
                            <div style={{ width: `${Math.min(100, (p.sales_7d / Math.max(1, filtered[0]?.sales_7d || 1)) * 100)}%`, height: "100%", background: p.sales_7d > 0 ? "#6366f1" : "#e2e8f0", borderRadius: 3 }} />
                          </div>
                          <span style={{ fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}>{fmtNum(p.sales_7d)}</span>
                        </div>
                      </td>
                      <td style={{ padding: "12px 16px", fontFamily: "'JetBrains Mono', monospace", color: "#64748b", fontSize: 13 }}>
                        {fmt(stockValue)}
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <button onClick={() => router.push(`/dss?product_id=${p.id}`)}
                          style={{ padding: "5px 12px", borderRadius: 8, border: "1px solid #e2e8f0", background: "white", color: "#6366f1", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
                          onMouseEnter={e => { e.target.style.background = "#6366f1"; e.target.style.color = "white"; }}
                          onMouseLeave={e => { e.target.style.background = "white"; e.target.style.color = "#6366f1"; }}
                        >Analyze</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {filtered.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "#94a3b8" }}>
              <p style={{ fontSize: 15 }}>No products match your filters</p>
            </div>
          )}
        </div>
      </main>

      <style>{`
        @keyframes fadeSlideUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        * { box-sizing: border-box; }
      `}</style>
    </div>
  );
}
