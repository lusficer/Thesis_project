import { useState, useEffect, useCallback, useRef } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, PieChart, Pie
} from "recharts";
import { inventoryAPI, productsAPI, salesAPI } from "@/lib/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

const statusCfg = {
  in_stock:     { bg: "#ecfdf5", text: "#059669", dot: "#10b981", label: "In Stock" },
  low_stock:    { bg: "#fffbeb", text: "#d97706", dot: "#f59e0b", label: "Low Stock" },
  out_of_stock: { bg: "#fef2f2", text: "#dc2626", dot: "#ef4444", label: "Out of Stock" },
};

const txnCfg = {
  IN:         { bg: "#f3e8ff", text: "#7c3aed", icon: "↓",  label: "Stock In" },
  OUT:        { bg: "#fef2f2", text: "#dc2626", icon: "↑",  label: "Stock Out" },
  ADJUSTMENT: { bg: "#f0f9ff", text: "#0369a1", icon: "↔",  label: "Adjustment" },
  SALE:       { bg: "#ecfdf5", text: "#059669", icon: "💰", label: "Sale" },
  WHOLESALE:  { bg: "#eff6ff", text: "#2563eb", icon: "📦", label: "Wholesale" },
  DAMAGE:     { bg: "#fef2f2", text: "#dc2626", icon: "⚠️", label: "Damaged" },
  LOSS:       { bg: "#fff7ed", text: "#ea580c", icon: "❌", label: "Loss" },
};

// Reasons shown in the Stock Out modal
const OUT_REASONS = [
  { value: "SALE",      label: "Retail Sale" },
  { value: "WHOLESALE", label: "Wholesale" },
  { value: "DAMAGE",    label: "Damaged" },
  { value: "LOSS",      label: "Lost" },
];

const fmtDt  = (s) => new Date(s).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtMoney = (n) => n != null ? `$${Number(n).toFixed(2)}` : null;
const productOptionLabel = (p) => `${p.name} (${p.sku}) — Stock: ${p.current_stock}`;

// ─── Icons ──────────────────────────────────────────────────────────
const I = {
  Plus:   () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  Minus:  () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  X:      () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  Alert:  () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  Search: () => <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  Clock:  () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
  Upload: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
};

const EMPTY_STOCK_FORM = {
  product_id: "", quantity: "",
  // stock-out fields
  reason: "SALE", unit_price: "", customer_name: "",
  // stock-in fields
  supplier: "", unit_cost: "",
  // shared
  reference: "", notes: "",
};

export default function InventoryPage() {
  const [tab, setTab] = useState("overview"); // overview | transactions | alerts | import

  // Stock modal state
  const [stockModal, setStockModal] = useState(null); // "in" | "out" | null
  const [stockForm, setStockForm] = useState(EMPTY_STOCK_FORM);

  // Data
  const [inventory, setInventory]     = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading]         = useState(true);

  // Filters
  const [search, setSearch]       = useState("");
  const [txnFilter, setTxnFilter] = useState("all");
  const [inventorySearch, setInventorySearch] = useState("");
  const [inventoryStatusFilter, setInventoryStatusFilter] = useState("all");

  const [notification, setNotification] = useState(null);

  const [stockModalSearch, setStockModalSearch] = useState("");

  // ── Import tab state ─────────────────────────────────────────────
  const [stagedFiles, setStagedFiles]       = useState([]);
  const [importing, setImporting]           = useState(false);
  const [importProgress, setImportProgress] = useState(null); // {step, pct, created, updated, total}
  const [importResult, setImportResult]     = useState(null); // {products_imported, records_imported, elapsed}
  const [importingFileLabel, setImportingFileLabel] = useState("");
  const [importDisclaimerOpen, setImportDisclaimerOpen] = useState(false);
  const importInputRef = useRef(null);
  const esRef          = useRef(null); // SSE EventSource (used for product catalog import)

  const showNotif = (msg) => {
    const text = typeof msg === 'string' ? msg : Array.isArray(msg) ? msg.map(e => e?.msg || JSON.stringify(e)).join(', ') : JSON.stringify(msg);
    setNotification(text);
    setTimeout(() => setNotification(null), 3000);
  };

  const alerts = inventory
    .filter(p => p.status === "low_stock" || p.status === "out_of_stock")
    .map(p => ({ ...p, days_left: p.daily_avg > 0 ? Math.floor(p.current_stock / p.daily_avg) : 0 }))
    .sort((a, b) => a.days_left - b.days_left);

  const filteredInventory = inventory.filter((p) => {
    const keyword = inventorySearch.trim().toLowerCase();
    const matchSearch = !keyword
      || p.name?.toLowerCase().includes(keyword)
      || p.sku?.toLowerCase().includes(keyword);
    const matchStatus = inventoryStatusFilter === "all" || p.status === inventoryStatusFilter;
    return matchSearch && matchStatus;
  });

  const stockChart = filteredInventory.map(p => ({
    name: p.sku,
    stock: p.current_stock,
    rop: p.reorder_point,
    color: p.status === "out_of_stock" ? "#ef4444" : p.status === "low_stock" ? "#f59e0b" : "#6366f1",
  }));

  const pieCounts = [
    { name: "In Stock",     value: filteredInventory.filter(p => p.status === "in_stock").length,     fill: "#10b981" },
    { name: "Low Stock",    value: filteredInventory.filter(p => p.status === "low_stock").length,    fill: "#f59e0b" },
    { name: "Out of Stock", value: filteredInventory.filter(p => p.status === "out_of_stock").length, fill: "#ef4444" },
  ];

  const filteredStockModalProducts = inventory.filter((p) => {
    const keyword = stockModalSearch.trim().toLowerCase();
    if (!keyword) return true;
    return p.name?.toLowerCase().includes(keyword) || p.sku?.toLowerCase().includes(keyword);
  });

  const filteredTxns = transactions.filter(t => {
    if (txnFilter !== "all" && t.type !== txnFilter) return false;
    if (search && !t.product_name?.toLowerCase().includes(search.toLowerCase()) && !t.sku?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const loadInventory = useCallback(async () => {
    try {
      setLoading(true);
      const [productsRes, txnRes] = await Promise.all([
        productsAPI.list({ limit: 200 }),
        inventoryAPI.allTransactions({ limit: 200 }),
      ]);

      const items = productsRes?.data?.items || [];
      setInventory(items.map(p => ({
        product_id:    p.id,
        name:          p.name,
        sku:           p.sku,
        current_stock: p.current_stock ?? 0,
        reorder_point: p.reorder_point ?? 0,
        safety_stock:  p.safety_stock ?? 0,
        status:        p.stock_status || "in_stock",
        current_price: p.current_price ?? 0,
        daily_avg:     0,
      })));
      setTransactions(txnRes?.data || []);
    } catch (err) {
      showNotif(err?.response?.data?.detail || "Failed to load inventory");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadInventory(); }, [loadInventory]);

  // Auto-fill unit_price when product or reason changes in stock-out modal
  const handleProductSelect = (productId) => {
    const product = inventory.find(p => String(p.product_id) === String(productId));
    setStockForm(prev => ({
      ...prev,
      product_id: productId,
      // Prefill sale price only for sale-type reasons
      unit_price: (prev.reason === "SALE" || prev.reason === "WHOLESALE")
        ? String(product?.current_price ?? "")
        : prev.unit_price,
    }));

    if (stockModal === "out") {
      setStockModalSearch(product ? productOptionLabel(product) : "");
    }
  };

  const handleStockOutProductInput = (value) => {
    setStockModalSearch(value);

    const q = value.trim().toLowerCase();
    if (!q) {
      setStockForm(prev => ({ ...prev, product_id: "" }));
      return;
    }

    const exact = inventory.find((p) => productOptionLabel(p).toLowerCase() === q);
    if (exact) {
      handleProductSelect(String(exact.product_id));
      return;
    }

    const exactSku = inventory.find((p) => p.sku?.toLowerCase() === q);
    if (exactSku) {
      handleProductSelect(String(exactSku.product_id));
      return;
    }

    const exactName = inventory.find((p) => p.name?.toLowerCase() === q);
    if (exactName) {
      handleProductSelect(String(exactName.product_id));
    }
  };

  const handleReasonChange = (reason) => {
    const product = inventory.find(p => String(p.product_id) === String(stockForm.product_id));
    setStockForm(prev => ({
      ...prev,
      reason,
      // Auto-fill price for sale reasons, clear it for non-sale
      unit_price: (reason === "SALE" || reason === "WHOLESALE")
        ? String(product?.current_price ?? "")
        : "",
    }));
  };

  const openStockModal = (mode) => {
    setStockForm(EMPTY_STOCK_FORM);
    setStockModalSearch("");
    setStockModal(mode);
  };

  const closeStockModal = () => {
    setStockModal(null);
    setStockModalSearch("");
  };

  const handleStockAction = async () => {
    if (!stockForm.product_id || !stockForm.quantity) return;
    try {
      if (stockModal === "in") {
        await inventoryAPI.stockIn({
          product_id: Number(stockForm.product_id),
          quantity:   Number(stockForm.quantity),
          supplier:   stockForm.supplier   || undefined,
          unit_cost:  stockForm.unit_cost  ? Number(stockForm.unit_cost) : undefined,
          reference:  stockForm.reference  || undefined,
          notes:      stockForm.notes      || undefined,
        });
        showNotif(`Stock received: ${stockForm.quantity} units`);
      } else {
        await inventoryAPI.stockOut({
          product_id:    Number(stockForm.product_id),
          quantity:      Number(stockForm.quantity),
          reason:        stockForm.reason || "SALE",
          unit_price:    stockForm.unit_price ? Number(stockForm.unit_price) : undefined,
          customer_name: stockForm.customer_name || undefined,
          reference:     stockForm.reference || undefined,
          notes:         stockForm.notes     || undefined,
        });
        showNotif(`Stock out: ${stockForm.quantity} units (${stockForm.reason})`);
      }
      await loadInventory();
      closeStockModal();
      setStockForm(EMPTY_STOCK_FORM);
    } catch (err) {
      showNotif(err?.response?.data?.detail || "Stock update failed");
    }
  };

  // ── Import: stage files without uploading yet ────────────────────
  const handleFileStage = (event) => {
    const newFiles = Array.from(event.target.files || []);
    if (!newFiles.length) return;
    setStagedFiles(prev => {
      const existing = new Set(prev.map(f => f.name));
      return [...prev, ...newFiles.filter(f => !existing.has(f.name))];
    });
    event.target.value = ""; // allow re-selecting same file
  };

  const removeStagedFile = (name) => setStagedFiles(prev => prev.filter(f => f.name !== name));

  // ── Run sales CSV import via BackgroundTask + SSE progress ────────
  const handleImportFile = async () => {
    if (!stagedFiles.length) return;

    const isIndiaOrders  = (f) => /list.of.orders/i.test(f.name);
    const isIndiaDetails = (f) => /order.details/i.test(f.name);
    const indiaOrders  = stagedFiles.filter(isIndiaOrders);
    const indiaDetails = stagedFiles.filter(isIndiaDetails);

    if (indiaOrders.length > 0 && indiaDetails.length === 0) {
      showNotif("India Orders detected — also add Order_Details.csv before importing.");
      return;
    }
    if (indiaDetails.length > 0 && indiaOrders.length === 0) {
      showNotif("Order_Details.csv detected — also add List_of_Orders.csv before importing.");
      return;
    }

    esRef.current?.close();
    setImporting(true);
    setImportResult(null);
    setImportingFileLabel(
      stagedFiles.length === 1
        ? stagedFiles[0].name
        : `${stagedFiles.length} files: ${stagedFiles.map((f) => f.name).join(", ")}`
    );
    setImportProgress({ step: "Uploading file(s)…", pct: 5 });
    const t0 = Date.now();

    // ── Step 1: POST files → get job_id immediately ───────────────
    let jobId;
    try {
      const res = await salesAPI.import(stagedFiles);
      jobId = res.data?.job_id;
    } catch (err) {
      const det = err?.response?.data?.detail;
      showNotif(typeof det === 'string' ? det : det?.[0]?.msg || "Upload failed");
      setImporting(false);
      setImportProgress(null);
      return;
    }

    if (!jobId) {
      showNotif("Server did not return a job ID");
      setImporting(false);
      setImportProgress(null);
      return;
    }

    // ── Step 2: SSE stream for real-time progress ─────────────────
    const es = new EventSource(`${API_BASE_URL}/sales/import/${jobId}/progress`);
    esRef.current = es;

    es.onmessage = async (evt) => {
      const d = JSON.parse(evt.data);
      const pct = d.progress ?? 0;

      let step = "Processing…";
      if (pct < 15)       step = "Parsing CSV…";
      else if (pct < 30)  step = "Normalizing data…";
      else if (pct < 90)  step = `Inserting records… (${pct}%)`;
      else if (pct < 100) step = "Finalizing…";
      else                step = "Completed!";

      setImportProgress({ step, pct });

      if (d.status === "done") {
        es.close();
        const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
        await loadInventory();
        setImporting(false);
        setImportProgress(null);
        setImportingFileLabel("");
        setStagedFiles([]);
        setImportResult({
          products_imported: d.products_imported || 0,
          records_imported:  d.records_imported  || 0,
          elapsed,
        });
        showNotif(`✅ ${d.records_imported} records, ${d.products_imported} products in ${elapsed}s`);
      } else if (d.status === "error") {
        es.close();
        showNotif(typeof d.error === 'string' ? d.error : JSON.stringify(d.error) || "Import failed");
        setImporting(false);
        setImportProgress(null);
        setImportingFileLabel("");
      }
    };

    es.onerror = () => {
      es.close();
      showNotif("Connection lost during import");
      setImporting(false);
      setImportProgress(null);
      setImportingFileLabel("");
    };
  };

  // ─── Render ──────────────────────────────────────────────────────
  return (
    <div style={S.page}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />

      {notification && <div style={S.notif}>{notification}</div>}

      <main style={S.main}>
        {/* Page Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
          <div>
            <h2 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>Inventory Management</h2>
            <p style={{ fontSize: 14, color: "#94a3b8", margin: "4px 0 0" }}>Track stock levels, transactions, and alerts</p>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={() => openStockModal("out")} style={S.secondaryBtn}><I.Minus /> Stock Out</button>
            <button onClick={() => openStockModal("in")}  style={S.primaryBtn}><I.Plus /> Stock In</button>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 4, marginBottom: 24, background: "#f1f5f9", borderRadius: 12, padding: 4, width: "fit-content" }}>
          {[
            { key: "overview",     label: "Overview" },
            { key: "transactions", label: "Transactions" },
            { key: "alerts",       label: `Alerts (${alerts.length})` },
            { key: "import",       label: "Import Sales Data" },
          ].map(t => (
            <button key={t.key} onClick={() => setTab(t.key)} style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              background: tab === t.key ? "white" : "transparent",
              color: tab === t.key ? "#1e293b" : "#64748b",
              fontWeight: tab === t.key ? 600 : 400, fontSize: 14,
              boxShadow: tab === t.key ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              transition: "all 0.15s",
            }}>{t.label}</button>
          ))}
        </div>

        {/* ─── Overview Tab ──────────────────────────────────────── */}
        {tab === "overview" && (
          <>
            <div style={{ ...S.card, marginBottom: 20, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {[
                  { key: "all", label: "All" },
                  { key: "in_stock", label: "In Stock" },
                  { key: "low_stock", label: "Low Stock" },
                  { key: "out_of_stock", label: "Out of Stock" },
                ].map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setInventoryStatusFilter(f.key)}
                    style={{
                      padding: "6px 14px",
                      borderRadius: 8,
                      border: "1px solid",
                      borderColor: inventoryStatusFilter === f.key ? "#6366f1" : "#e2e8f0",
                      background: inventoryStatusFilter === f.key ? "#eef2ff" : "white",
                      color: inventoryStatusFilter === f.key ? "#6366f1" : "#64748b",
                      fontWeight: inventoryStatusFilter === f.key ? 600 : 400,
                      fontSize: 13,
                      cursor: "pointer",
                    }}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <div style={{ position: "relative" }}>
                <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#94a3b8" }}><I.Search /></span>
                <input
                  value={inventorySearch}
                  onChange={e => setInventorySearch(e.target.value)}
                  placeholder="Search product or SKU..."
                  style={{ padding: "8px 14px 8px 38px", borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 14, width: 260, outline: "none" }}
                />
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 20, marginBottom: 24 }}>
              <div style={S.card}>
                <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 20px" }}>Stock Levels vs Reorder Points</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={stockChart} barCategoryGap="20%">
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 13 }} />
                    <Bar dataKey="stock" name="Current Stock" radius={[6, 6, 0, 0]}>
                      {stockChart.map((e, i) => <Cell key={i} fill={e.color} />)}
                    </Bar>
                    <Bar dataKey="rop" name="Reorder Point" fill="#cbd5e1" radius={[6, 6, 0, 0]} opacity={0.5} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div style={S.card}>
                <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 16px" }}>Stock Distribution</h3>
                <ResponsiveContainer width="100%" height={180}>
                  <PieChart>
                    <Pie data={pieCounts} cx="50%" cy="50%" innerRadius={50} outerRadius={75} dataKey="value" strokeWidth={2} stroke="#fff">
                      {pieCounts.map((e, i) => <Cell key={i} fill={e.fill} />)}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 10, fontSize: 13 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ display: "flex", justifyContent: "center", gap: 16, marginTop: 8 }}>
                  {pieCounts.map(p => (
                    <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                      <span style={{ width: 10, height: 10, borderRadius: 3, background: p.fill }} />
                      <span style={{ color: "#64748b" }}>{p.name}</span>
                      <span style={{ fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{p.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ ...S.card, padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ background: "#f8fafc" }}>
                    {["Product", "SKU", "Current Stock", "ROP", "Safety Stock", "Status", "Daily Avg", "Days Left"].map(h => (
                      <th key={h} style={{ padding: "12px 16px", textAlign: "left", fontWeight: 600, color: "#64748b", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.5px" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredInventory.map((p, i) => {
                    const s = statusCfg[p.status];
                    const daysLeft = p.daily_avg > 0 ? Math.floor(p.current_stock / p.daily_avg) : "—";
                    const stockPct = p.reorder_point > 0 ? Math.min(100, (p.current_stock / (p.reorder_point * 3)) * 100) : 100;
                    return (
                      <tr key={p.product_id} style={{ borderBottom: "1px solid #f1f5f9", animation: `fadeSlideUp 0.4s ease ${i * 0.03}s both` }}
                        onMouseEnter={e => e.currentTarget.style.background = "#f8fafc"}
                        onMouseLeave={e => e.currentTarget.style.background = "white"}>
                        <td style={{ padding: "14px 16px", fontWeight: 600 }}>{p.name}</td>
                        <td style={{ padding: "14px 16px", fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: "#94a3b8" }}>{p.sku}</td>
                        <td style={{ padding: "14px 16px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span style={{ fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", minWidth: 40 }}>{p.current_stock}</span>
                            <div style={{ width: 60, height: 6, borderRadius: 3, background: "#f1f5f9", overflow: "hidden" }}>
                              <div style={{ height: "100%", borderRadius: 3, width: `${stockPct}%`, background: p.status === "out_of_stock" ? "#ef4444" : p.status === "low_stock" ? "#f59e0b" : "#6366f1", transition: "width 0.3s" }} />
                            </div>
                          </div>
                        </td>
                        <td style={{ padding: "14px 16px", fontFamily: "'JetBrains Mono', monospace" }}>{p.reorder_point}</td>
                        <td style={{ padding: "14px 16px", fontFamily: "'JetBrains Mono', monospace" }}>{p.safety_stock}</td>
                        <td style={{ padding: "14px 16px" }}>
                          <span style={{ ...S.badge, background: s.bg, color: s.text }}>
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot, display: "inline-block" }} /> {s.label}
                          </span>
                        </td>
                        <td style={{ padding: "14px 16px", fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}>{p.daily_avg}/day</td>
                        <td style={{ padding: "14px 16px" }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: typeof daysLeft === "number" && daysLeft < 7 ? "#dc2626" : daysLeft < 14 ? "#d97706" : "#059669" }}>
                            {daysLeft}{typeof daysLeft === "number" ? "d" : ""}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                  {filteredInventory.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ padding: "24px 16px", textAlign: "center", color: "#94a3b8" }}>
                        No products match current filters
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* ─── Transactions Tab ──────────────────────────────────── */}
        {tab === "transactions" && (
          <div style={S.card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {[
                  { key: "all",       label: "All" },
                  { key: "IN",        label: "Stock In" },
                  { key: "SALE",      label: "Sales" },
                  { key: "WHOLESALE", label: "Wholesale" },
                  { key: "OUT",       label: "Stock Out" },
                  { key: "DAMAGE",    label: "Damaged" },
                  { key: "LOSS",      label: "Loss" },
                  { key: "ADJUSTMENT",label: "Adjustments" },
                ].map(f => (
                  <button key={f.key} onClick={() => setTxnFilter(f.key)} style={{
                    padding: "6px 14px", borderRadius: 8, border: "1px solid",
                    borderColor: txnFilter === f.key ? "#6366f1" : "#e2e8f0",
                    background:  txnFilter === f.key ? "#eef2ff" : "white",
                    color:       txnFilter === f.key ? "#6366f1" : "#64748b",
                    fontWeight:  txnFilter === f.key ? 600 : 400, fontSize: 13, cursor: "pointer",
                  }}>{f.label}</button>
                ))}
              </div>
              <div style={{ position: "relative" }}>
                <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#94a3b8" }}><I.Search /></span>
                <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search transactions..." style={{ padding: "8px 14px 8px 38px", borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 14, width: 240, outline: "none" }} />
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {filteredTxns.map((t, i) => {
                const cfg = txnCfg[t.type] || txnCfg.OUT;
                return (
                  <div key={t.id} style={{
                    display: "flex", alignItems: "center", gap: 16, padding: "14px 18px",
                    borderRadius: 12, border: "1px solid #f1f5f9", transition: "background 0.15s",
                    animation: `fadeSlideUp 0.3s ease ${i * 0.04}s both`,
                  }}
                    onMouseEnter={e => e.currentTarget.style.background = "#f8fafc"}
                    onMouseLeave={e => e.currentTarget.style.background = "white"}>
                    <div style={{ width: 40, height: 40, borderRadius: 10, background: cfg.bg, color: cfg.text, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 700, flexShrink: 0 }}>
                      {cfg.icon}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span style={{ fontWeight: 600, fontSize: 14 }}>{t.product_name}</span>
                        <span style={{ fontSize: 11, color: "#94a3b8", fontFamily: "'JetBrains Mono', monospace" }}>{t.sku}</span>
                        {/* Extra context tags */}
                        {t.customer_name && <span style={S.metaTag}>👤 {t.customer_name}</span>}
                        {t.supplier      && <span style={S.metaTag}>🏭 {t.supplier}</span>}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 4, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, color: "#64748b", display: "flex", alignItems: "center", gap: 4 }}><I.Clock /> {fmtDt(t.timestamp)}</span>
                        {t.reference  && <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#94a3b8", background: "#f1f5f9", padding: "1px 8px", borderRadius: 4 }}>{t.reference}</span>}
                        {t.notes      && <span style={{ fontSize: 12, color: "#94a3b8" }}>{t.notes}</span>}
                        {t.unit_price != null && <span style={{ fontSize: 12, color: "#6366f1", fontFamily: "'JetBrains Mono', monospace" }}>{fmtMoney(t.unit_price)}/unit</span>}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      <span style={{ ...S.badge, background: cfg.bg, color: cfg.text, fontSize: 11 }}>{cfg.label}</span>
                      <p style={{ fontSize: 20, fontWeight: 700, margin: "6px 0 0", fontFamily: "'JetBrains Mono', monospace", color: t.quantity > 0 ? "#059669" : "#dc2626" }}>
                        {t.quantity > 0 ? "+" : ""}{t.quantity}
                      </p>
                    </div>
                  </div>
                );
              })}
              {filteredTxns.length === 0 && <p style={{ textAlign: "center", color: "#94a3b8", padding: 32 }}>No transactions found</p>}
            </div>
          </div>
        )}

        {/* ─── Alerts Tab ────────────────────────────────────────── */}
        {tab === "alerts" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {alerts.length === 0 && (
              <div style={{ ...S.card, textAlign: "center", padding: 60 }}>
                <p style={{ fontSize: 40, margin: "0 0 8px" }}>✅</p>
                <p style={{ fontSize: 18, fontWeight: 600, color: "#059669" }}>All stock levels healthy</p>
                <p style={{ fontSize: 14, color: "#94a3b8" }}>No products below reorder point</p>
              </div>
            )}
            {alerts.map((p, i) => {
              const s = statusCfg[p.status];
              const urgency = p.status === "out_of_stock" ? "CRITICAL" : p.days_left < 5 ? "HIGH" : "MEDIUM";
              const urgencyColor = urgency === "CRITICAL" ? "#dc2626" : urgency === "HIGH" ? "#d97706" : "#6366f1";
              return (
                <div key={p.product_id} style={{ ...S.card, display: "flex", alignItems: "center", gap: 20, borderLeft: `4px solid ${urgencyColor}`, animation: `fadeSlideUp 0.4s ease ${i * 0.06}s both` }}>
                  <div style={{ width: 48, height: 48, borderRadius: 12, background: s.bg, color: s.text, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <I.Alert />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontWeight: 700, fontSize: 16 }}>{p.name}</span>
                      <span style={{ ...S.badge, background: urgencyColor + "15", color: urgencyColor, fontSize: 10, fontWeight: 700, letterSpacing: "0.5px" }}>{urgency}</span>
                    </div>
                    <p style={{ fontSize: 13, color: "#64748b", margin: "4px 0 0" }}>
                      Stock: <strong>{p.current_stock}</strong> • ROP: <strong>{p.reorder_point}</strong> • Avg: <strong>{p.daily_avg}/day</strong>
                      {p.days_left > 0 && <span> • ~<strong style={{ color: urgencyColor }}>{p.days_left} days</strong> until stockout</span>}
                    </p>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                    <button style={S.primaryBtn}>Order Now</button>
                    <button style={S.secondaryBtn}>Run DSS</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ─── Import Tab ────────────────────────────────────────── */}
        {tab === "import" && (
          <div style={{ ...S.card, maxWidth: 560 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 4 }}>
              <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Import Sales Data</h3>
              <button
                onClick={() => setImportDisclaimerOpen(true)}
                style={{ ...S.secondaryBtn, padding: "6px 10px", fontSize: 12 }}
              >
                <I.Alert /> Disclaimer
              </button>
            </div>
            <p style={{ fontSize: 13, color: "#64748b", margin: "0 0 24px" }}>
              Upload CSV sales exports. Supports multiple retail dataset formats, including paired-file sources.
            </p>

            {importing ? (
              /* Progress UI */
              <div style={{ border: "2px solid #e0e7ff", borderRadius: 12, padding: "32px 24px", textAlign: "center", background: "#f5f3ff" }}>
                <div style={S.spinner} />
                <p style={{ color: "#6366f1", fontWeight: 700, marginTop: 14, fontSize: 15 }}>
                  {importProgress?.step || "Processing…"}
                </p>
                {importingFileLabel && (
                  <p style={{ color: "#4f46e5", fontSize: 12, marginTop: 6, wordBreak: "break-word" }}>
                    Importing: {importingFileLabel}
                  </p>
                )}
                <div style={{ margin: "10px auto 0", maxWidth: 320, height: 8, background: "#ddd6fe", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{ height: "100%", borderRadius: 4, background: "linear-gradient(90deg, #6366f1, #818cf8)", width: `${importProgress?.pct ?? 10}%`, transition: "width 0.4s ease" }} />
                </div>
                <span style={{ fontSize: 13, color: "#6366f1", fontWeight: 700, marginTop: 8, display: "block" }}>
                  {importProgress?.pct ?? 0}%
                </span>
                <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 12, lineHeight: 1.6 }}>
                  Large files (Favorita, UK Retail ~100MB) are processed in the background.
                </p>
              </div>
            ) : importResult ? (
              /* Result card */
              <div style={{ border: "2px solid #d1fae5", borderRadius: 12, padding: "28px 24px", textAlign: "center", background: "#f0fdf4" }}>
                <div style={{ fontSize: 40, marginBottom: 10 }}>✅</div>
                <p style={{ color: "#059669", fontWeight: 700, fontSize: 16, margin: "0 0 16px" }}>Import completed in {importResult.elapsed}s</p>
                <div style={{ display: "flex", justifyContent: "center", gap: 24 }}>
                  <div>
                    <p style={{ fontSize: 26, fontWeight: 700, margin: 0, fontFamily: "'JetBrains Mono', monospace" }}>{importResult.records_imported}</p>
                    <p style={{ fontSize: 12, color: "#64748b", margin: "4px 0 0" }}>Records imported</p>
                  </div>
                  <div style={{ width: 1, background: "#d1fae5" }} />
                  <div>
                    <p style={{ fontSize: 26, fontWeight: 700, margin: 0, fontFamily: "'JetBrains Mono', monospace" }}>{importResult.products_imported}</p>
                    <p style={{ fontSize: 12, color: "#64748b", margin: "4px 0 0" }}>Products touched</p>
                  </div>
                </div>
                <button onClick={() => { setImportResult(null); setStagedFiles([]); }} style={{ ...S.secondaryBtn, marginTop: 20 }}>
                  Import more files
                </button>
              </div>
            ) : (
              /* File staging UI */
              <div>
                {/* Drop zone */}
                <div
                  style={{ border: "2px dashed #d1d5db", borderRadius: 12, padding: stagedFiles.length > 0 ? "20px 24px" : 40, textAlign: "center", background: "#f9fafb", cursor: "pointer", transition: "all 0.2s" }}
                  onClick={() => importInputRef.current?.click()}
                  onDragOver={e => { e.preventDefault(); e.currentTarget.style.borderColor = "#6366f1"; e.currentTarget.style.background = "#eef2ff"; }}
                  onDragLeave={e => { e.currentTarget.style.borderColor = "#d1d5db"; e.currentTarget.style.background = "#f9fafb"; }}
                  onDrop={e => {
                    e.preventDefault();
                    e.currentTarget.style.borderColor = "#d1d5db"; e.currentTarget.style.background = "#f9fafb";
                    const dt = e.dataTransfer.files;
                    if (dt.length > 0) handleFileStage({ target: { files: dt, value: "" } });
                  }}
                >
                  <I.Upload />
                  <p style={{ fontWeight: 600, margin: "8px 0 4px", fontSize: stagedFiles.length > 0 ? 13 : 15 }}>
                    {stagedFiles.length > 0 ? "Add another file (drag & drop or click)" : "Drop CSV file(s) here or click to browse"}
                  </p>
                  {stagedFiles.length === 0 && (
                    <p style={{ fontSize: 13, color: "#94a3b8", margin: "0 0 12px" }}>
                      Some dataset types require a companion file pair. Add both files together.
                    </p>
                  )}
                  <input ref={importInputRef} type="file" accept=".csv" multiple onChange={handleFileStage} style={{ display: "none" }} />
                  {stagedFiles.length === 0 && (
                    <button onClick={e => { e.stopPropagation(); importInputRef.current?.click(); }} style={S.secondaryBtn}>
                      Browse Files
                    </button>
                  )}
                </div>

                {/* Staged file list */}
                {stagedFiles.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <p style={{ fontSize: 12, fontWeight: 600, color: "#374151", margin: "0 0 8px" }}>
                      {stagedFiles.length} file{stagedFiles.length > 1 ? "s" : ""} selected:
                    </p>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {stagedFiles.map(f => {
                        const isOrders  = /list.of.orders/i.test(f.name);
                        const isDetails = /order.details/i.test(f.name);
                        const tag = isOrders ? "India Orders" : isDetails ? "India Details" : null;
                        return (
                          <div key={f.name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 12px", background: "#f1f5f9", borderRadius: 8, border: "1px solid #e2e8f0" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                              <span style={{ fontSize: 16 }}>📄</span>
                              <span style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                              {tag && <span style={{ fontSize: 11, background: "#dbeafe", color: "#1d4ed8", padding: "2px 6px", borderRadius: 4, flexShrink: 0 }}>{tag}</span>}
                              <span style={{ fontSize: 11, color: "#94a3b8", flexShrink: 0 }}>{(f.size / 1024 / 1024).toFixed(1)}MB</span>
                            </div>
                            <button onClick={() => removeStagedFile(f.name)} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 16, padding: "0 4px" }}>✕</button>
                          </div>
                        );
                      })}
                    </div>

                    {/* India pair validation hint */}
                    {(() => {
                      const hasOrders  = stagedFiles.some(f => /list.of.orders/i.test(f.name));
                      const hasDetails = stagedFiles.some(f => /order.details/i.test(f.name));
                      if (hasOrders && !hasDetails) return <p style={S.warnBanner}>⚠️ A companion file is required for this paired dataset format.</p>;
                      if (hasDetails && !hasOrders) return <p style={S.warnBanner}>⚠️ A companion file is required for this paired dataset format.</p>;
                      if (hasOrders && hasDetails)  return <p style={S.okBanner}>✅ Paired dataset files detected — they will be auto-joined.</p>;
                      return null;
                    })()}

                    <button onClick={handleImportFile} style={{ ...S.primaryBtn, width: "100%", marginTop: 14, justifyContent: "center" }}>
                      <I.Upload /> Import {stagedFiles.length} file{stagedFiles.length > 1 ? "s" : ""}
                    </button>
                  </div>
                )}

                {!stagedFiles.length && (
                  <p style={{ fontSize: 12, color: "#94a3b8", margin: "12px 0 0", lineHeight: 1.6 }}>
                    ⚡ For paired datasets, upload both required files together before importing. Other formats can be imported individually.
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </main>

      {/* ─── Import Disclaimer Modal ───────────────────────────────── */}
      {importDisclaimerOpen && (
        <div style={S.overlay} onClick={() => setImportDisclaimerOpen(false)}>
          <div
            style={{ ...S.modal, maxWidth: 640, padding: 32, borderRadius: 18 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Import Disclaimer</h3>
              <button
                onClick={() => setImportDisclaimerOpen(false)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8" }}
              >
                <I.X />
              </button>
            </div>
            <p style={{ margin: "0 0 12px", fontSize: 16, color: "#475569", lineHeight: 1.7 }}>
              Importing the same dataset multiple times does <strong>not</strong> create duplicate products,
              but it <strong>adds</strong> sales quantities to existing product/date records.
            </p>
            <p style={{ margin: 0, fontSize: 16, color: "#475569", lineHeight: 1.7 }}>
              In short: re-importing identical files can inflate sales totals and affect forecasts.
            </p>
            <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end" }}>
              <button onClick={() => setImportDisclaimerOpen(false)} style={{ ...S.primaryBtn, padding: "10px 16px", fontSize: 14 }}>
                Got it
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Stock In / Out Modal ─────────────────────────────────── */}
      {stockModal && (
        <div style={S.overlay} onClick={closeStockModal}>
          <div style={S.modal} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
              <h3 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>
                {stockModal === "in" ? "Receive Stock" : "Stock Out"}
              </h3>
              <button onClick={closeStockModal} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8" }}><I.X /></button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {stockModal === "out" && (
                <div>
                  <label style={S.label}>Product *</label>
                  <div style={{ position: "relative" }}>
                    <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#94a3b8" }}><I.Search /></span>
                    <input
                      value={stockModalSearch}
                      onChange={e => handleStockOutProductInput(e.target.value)}
                      placeholder="Search or select product..."
                      style={{ ...S.input, paddingLeft: 38 }}
                      list="stock-out-products"
                    />
                    <datalist id="stock-out-products">
                      {filteredStockModalProducts.map(p => (
                        <option key={p.product_id} value={productOptionLabel(p)} />
                      ))}
                    </datalist>
                  </div>
                </div>
              )}

              {/* Product selector */}
              {stockModal === "in" && (
              <div>
                <label style={S.label}>Product *</label>
                <select
                  value={stockForm.product_id}
                  onChange={e => handleProductSelect(e.target.value)}
                  style={S.input}
                >
                  <option value="">Select product...</option>
                  {filteredStockModalProducts.map(p => (
                    <option key={p.product_id} value={p.product_id}>
                      {p.name} ({p.sku}) — Stock: {p.current_stock}
                    </option>
                  ))}
                </select>
              </div>
              )}

              {/* Quantity */}
              <div>
                <label style={S.label}>Quantity *</label>
                <input type="number" value={stockForm.quantity} onChange={e => setStockForm(p => ({ ...p, quantity: e.target.value }))} placeholder="Enter quantity" style={S.input} min="1" />
              </div>

              {/* ── Stock Out specific fields ── */}
              {stockModal === "out" && (
                <>
                  {/* Reason selector */}
                  <div>
                    <label style={S.label}>Reason</label>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {OUT_REASONS.map(r => (
                        <button
                          key={r.value}
                          onClick={() => handleReasonChange(r.value)}
                          style={{
                            padding: "8px 16px", borderRadius: 8, border: "1px solid",
                            borderColor: stockForm.reason === r.value ? "#6366f1" : "#e2e8f0",
                            background:  stockForm.reason === r.value ? "#eef2ff" : "white",
                            color:       stockForm.reason === r.value ? "#6366f1" : "#64748b",
                            fontWeight:  stockForm.reason === r.value ? 600 : 400,
                            fontSize: 13, cursor: "pointer",
                          }}
                        >
                          {r.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Price + customer — only shown for sale-type reasons */}
                  {(stockForm.reason === "SALE" || stockForm.reason === "WHOLESALE") && (
                    <>
                      <div>
                        <label style={S.label}>Unit Price</label>
                        <input type="number" value={stockForm.unit_price} onChange={e => setStockForm(p => ({ ...p, unit_price: e.target.value }))} placeholder="e.g. 29.99" style={S.input} min="0" step="0.01" />
                      </div>
                      <div>
                        <label style={S.label}>Customer Name (optional)</label>
                        <input value={stockForm.customer_name} onChange={e => setStockForm(p => ({ ...p, customer_name: e.target.value }))} placeholder="e.g. Acme Corp" style={S.input} />
                      </div>
                    </>
                  )}
                </>
              )}

              {/* ── Stock In specific fields ── */}
              {stockModal === "in" && (
                <>
                  <div>
                    <label style={S.label}>Supplier (optional)</label>
                    <input value={stockForm.supplier} onChange={e => setStockForm(p => ({ ...p, supplier: e.target.value }))} placeholder="e.g. Acme Wholesale" style={S.input} />
                  </div>
                  <div>
                    <label style={S.label}>Purchase Cost per Unit (optional)</label>
                    <input type="number" value={stockForm.unit_cost} onChange={e => setStockForm(p => ({ ...p, unit_cost: e.target.value }))} placeholder="e.g. 12.50" style={S.input} min="0" step="0.01" />
                  </div>
                </>
              )}

              {/* Shared fields */}
              <div>
                <label style={S.label}>Invoice / Reference</label>
                <input value={stockForm.reference} onChange={e => setStockForm(p => ({ ...p, reference: e.target.value }))} placeholder="e.g. INV-2024-0090" style={S.input} />
              </div>
              <div>
                <label style={S.label}>Notes</label>
                <textarea value={stockForm.notes} onChange={e => setStockForm(p => ({ ...p, notes: e.target.value }))} placeholder="Optional notes..." rows={3} style={{ ...S.input, resize: "vertical" }} />
              </div>
            </div>

            <div style={{ display: "flex", gap: 12, marginTop: 24, justifyContent: "flex-end" }}>
              <button onClick={closeStockModal} style={S.secondaryBtn}>Cancel</button>
              <button onClick={handleStockAction} style={{ ...S.primaryBtn, background: stockModal === "in" ? "#059669" : "#dc2626" }}>
                {stockModal === "in" ? "Receive Stock" : "Confirm Stock Out"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes fadeSlideUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        * { box-sizing: border-box; }
        select { appearance: none; background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e"); background-position: right 10px center; background-repeat: no-repeat; background-size: 16px; padding-right: 36px !important; }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

const S = {
  page:        { fontFamily: "'DM Sans', 'Segoe UI', system-ui, sans-serif", background: "#f8f9fb", minHeight: "100vh", color: "#1a1a2e" },
  main:        { maxWidth: 1400, margin: "0 auto", padding: "32px 40px" },
  card:        { background: "white", borderRadius: 16, padding: 24, border: "1px solid #e8eaef", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" },
  primaryBtn:  { display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 20px", borderRadius: 10, border: "none", background: "#6366f1", color: "white", fontWeight: 600, fontSize: 14, cursor: "pointer" },
  secondaryBtn:{ display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 20px", borderRadius: 10, border: "1px solid #e2e8f0", background: "white", color: "#374151", fontWeight: 500, fontSize: 14, cursor: "pointer" },
  badge:       { display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 600 },
  metaTag:     { fontSize: 11, background: "#f1f5f9", color: "#64748b", padding: "2px 8px", borderRadius: 4 },
  overlay:     { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 },
  modal:       { background: "white", borderRadius: 20, padding: 32, maxWidth: 520, width: "90%", maxHeight: "90vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.2)", animation: "fadeSlideUp 0.3s ease" },
  label:       { fontSize: 13, fontWeight: 600, color: "#374151", display: "block", marginBottom: 6 },
  input:       { width: "100%", padding: "10px 14px", borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 14, outline: "none", fontFamily: "inherit" },
  notif:       { position: "fixed", top: 24, right: 24, zIndex: 1000, padding: "14px 24px", borderRadius: 12, color: "white", fontWeight: 600, fontSize: 14, background: "#059669", boxShadow: "0 8px 30px rgba(0,0,0,0.15)", animation: "fadeSlideUp 0.3s ease" },
  spinner:     { width: 36, height: 36, border: "3px solid #ddd6fe", borderTopColor: "#6366f1", borderRadius: "50%", margin: "0 auto", animation: "spin 0.8s linear infinite" },
  warnBanner:  { fontSize: 12, color: "#d97706", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: "8px 12px", marginTop: 8 },
  okBanner:    { fontSize: 12, color: "#059669", background: "#f0fdf4", border: "1px solid #d1fae5", borderRadius: 6, padding: "8px 12px", marginTop: 8 },
};
