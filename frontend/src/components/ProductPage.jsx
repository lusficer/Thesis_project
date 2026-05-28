import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { productsAPI } from "@/lib/api";


const EMPTY_FORM = { sku: "", name: "", description: "", category_id: "", base_price: "", cost_price: "", current_price: "", initial_stock: "0", image_url: "" };

const statusCfg = {
  in_stock: { bg: "#ecfdf5", text: "#059669", dot: "#10b981", label: "In Stock" },
  low_stock: { bg: "#fffbeb", text: "#d97706", dot: "#f59e0b", label: "Low Stock" },
  out_of_stock: { bg: "#fef2f2", text: "#dc2626", dot: "#ef4444", label: "Out of Stock" },
};

const fmt = (n) => `$${Number(n).toFixed(2)}`;

const I = {
  Plus: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  Search: () => <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  Edit: () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>,
  Trash: () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>,
  X: () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  Eye: () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
  Back: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>,
};

export default function ProductsPage() {
  const router = useRouter();
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [creatingCategory, setCreatingCategory] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState("");
  const [selectedIds, setSelectedIds] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [editingProduct, setEditingProduct] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [viewProduct, setViewProduct] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [notification, setNotification] = useState(null);
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(null); // { scope: "selected" | "all", count: number }
  const [showQuickCategoryModal, setShowQuickCategoryModal] = useState(false);
  const [quickCategoryName, setQuickCategoryName] = useState("");
  const [creatingQuickCategory, setCreatingQuickCategory] = useState(false);
  const [showArchivedModal, setShowArchivedModal] = useState(false);
  const [archivedProducts, setArchivedProducts] = useState([]);
  const [loadingArchived, setLoadingArchived] = useState(false);

  const showNotif = (msg, type = "success") => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 3000);
  };

  const loadProducts = useCallback(async () => {
    try {
      setLoadingProducts(true);
      const response = await productsAPI.list({
        page,
        page_size: pageSize,
        search: search || undefined,
        category_id: catFilter ? Number(catFilter) : undefined,
      });
      if (response?.data?.items) {
        setProducts(response.data.items);
        setSelectedIds([]);
        setTotalPages(response.data.total_pages || 1);
        setTotalItems(response.data.total || 0);
      }
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Failed to load products", "error");
    } finally {
      setLoadingProducts(false);
    }
  }, [page, pageSize, search, catFilter]);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const loadCategories = useCallback(async () => {
    try {
      const res = await productsAPI.categories();
      setCategories(res.data || []);
    } catch {
      setCategories([]);
    }
  }, []);

  useEffect(() => {
    loadCategories();
  }, [loadCategories]);

  const filtered = products;

  const toggleSelected = (id) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const allSelected = filtered.length > 0 && filtered.every(p => selectedIds.includes(p.id));
  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(prev => prev.filter(id => !filtered.some(p => p.id === id)));
    } else {
      const newIds = filtered.map(p => p.id);
      setSelectedIds(prev => Array.from(new Set([...prev, ...newIds])));
    }
  };

  const openAdd = () => {
    setForm(EMPTY_FORM);
    setEditingProduct(null);
    setNewCategoryName("");
    setShowModal(true);
  };

  const toViewProduct = (source, detail) => {
    const merged = detail ? { ...source, ...detail } : source;
    const categoryId = merged?.category_id ?? merged?.category?.id ?? null;
    const categoryFromList = categoryId != null
      ? categories.find(c => String(c.id) === String(categoryId))?.name
      : null;
    const categoryName = merged?.category_name ?? merged?.category?.name ?? categoryFromList ?? null;
    return { ...merged, category_id: categoryId, category_name: categoryName };
  };

  const openEdit = async (p) => {
    let full = p;
    try {
      const res = await productsAPI.get(p.id);
      full = toViewProduct(p, res?.data);
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Failed to load product details", "error");
      return;
    }

    setForm({
      sku: full.sku, name: full.name, description: full.description || "",
      category_id: full.category_id != null ? String(full.category_id) : "", base_price: String(full.base_price),
      cost_price: String(full.cost_price || ""), current_price: String(full.current_price),
      initial_stock: String(full.current_stock), image_url: full.image_url || "",
    });
    setNewCategoryName("");
    setEditingProduct(full);
    setShowModal(true);
  };

  const openView = async (p) => {
    try {
      const res = await productsAPI.get(p.id);
      setViewProduct(toViewProduct(p, res?.data));
    } catch {
      setViewProduct(toViewProduct(p));
    }
  };

  const handleCreateCategory = async () => {
    const name = newCategoryName.trim();
    if (!name) {
      showNotif("Please enter a category name", "error");
      return;
    }

    try {
      setCreatingCategory(true);
      const res = await productsAPI.createCategory({ name });
      const created = res?.data;
      await loadCategories();
      if (created?.id) {
        updateField("category_id", String(created.id));
      }
      setNewCategoryName("");
      showNotif(`Category "${name}" created`);
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Failed to create category", "error");
    } finally {
      setCreatingCategory(false);
    }
  };

  const handleQuickCreateCategory = async () => {
    const name = quickCategoryName.trim();
    if (!name) {
      showNotif("Please enter a category name", "error");
      return;
    }

    try {
      setCreatingQuickCategory(true);
      const res = await productsAPI.createCategory({ name });
      const created = res?.data;
      await loadCategories();
      if (created?.id) {
        setCatFilter(String(created.id));
        setPage(1);
      }
      setQuickCategoryName("");
      setShowQuickCategoryModal(false);
      showNotif(`Category "${name}" created`);
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Failed to create category", "error");
    } finally {
      setCreatingQuickCategory(false);
    }
  };

  const handleDeleteCategory = async (categoryId) => {
    if (!categoryId) return;
    const cat = categories.find(c => String(c.id) === String(categoryId));
    const label = cat?.name || `#${categoryId}`;
    if (!window.confirm(`Delete category "${label}"? Products in this category will become uncategorized.`)) {
      return;
    }

    try {
      await productsAPI.deleteCategory(Number(categoryId));
      if (String(catFilter) === String(categoryId)) setCatFilter("");
      if (String(form.category_id) === String(categoryId)) updateField("category_id", "");
      await loadCategories();
      await loadProducts();
      showNotif(`Category "${label}" deleted`);
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Failed to delete category", "error");
    }
  };

  const handleSave = async () => {
    if (!form.sku || !form.name || !form.base_price) {
      showNotif("Please fill in SKU, Name, and Base Price", "error");
      return;
    }
    try {
      if (editingProduct) {
        await productsAPI.update(editingProduct.id, {
          name: form.name,
          description: form.description || null,
          category_id: Number(form.category_id) || null,
          base_price: Number(form.base_price),
          current_price: Number(form.current_price) || Number(form.base_price),
          cost_price: Number(form.cost_price) || null,
          image_url: form.image_url || null,
        });
        showNotif(`"${form.name}" updated successfully`);
      } else {
        await productsAPI.create({
          sku: form.sku,
          name: form.name,
          description: form.description || null,
          category_id: Number(form.category_id) || null,
          base_price: Number(form.base_price),
          current_price: Number(form.current_price) || Number(form.base_price),
          cost_price: Number(form.cost_price) || null,
          image_url: form.image_url || null,
          initial_stock: Number(form.initial_stock) || 0,
        });
        showNotif(`"${form.name}" created successfully`);
      }
      setShowModal(false);
      await loadProducts();
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Save failed", "error");
    }
  };

  const handleDelete = async (p) => {
    try {
      await productsAPI.delete(p.id);
      showNotif(`"${p.name}" archived`);
      await loadProducts();
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Delete failed", "error");
    } finally {
      setDeleteConfirm(null);
    }
  };

  const loadArchivedProducts = useCallback(async () => {
    try {
      setLoadingArchived(true);
      const response = await productsAPI.list({ is_active: false, page_size: 200 });
      setArchivedProducts(response?.data?.items || []);
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Failed to load archived products", "error");
      setArchivedProducts([]);
    } finally {
      setLoadingArchived(false);
    }
  }, []);

  const openArchivedModal = async () => {
    setShowArchivedModal(true);
    await loadArchivedProducts();
  };

  const handleUnarchive = async (product) => {
    try {
      await productsAPI.update(product.id, { is_active: true });
      showNotif(`"${product.name}" restored`);
      await loadProducts();
      await loadArchivedProducts();
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Restore failed", "error");
    }
  };

  const handleBulkDelete = async (hardDelete = false) => {
    if (selectedIds.length === 0) return;
    try {
      const ids = [...selectedIds];
      const response = await productsAPI.bulkDelete({ ids, hard_delete: hardDelete });
      const deleted = response?.data?.deleted ?? ids.length;
      showNotif(`${hardDelete ? "Deleted" : "Archived"} ${deleted} product${deleted > 1 ? "s" : ""}`);
      await loadProducts();
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Bulk delete failed", "error");
    }
  };

  const handleDeleteAll = async (hardDelete = false) => {
    try {
      const response = await productsAPI.bulkDelete({
        search: search || undefined,
        category_id: catFilter ? Number(catFilter) : undefined,
        hard_delete: hardDelete,
      });
      const deleted = response?.data?.deleted ?? 0;
      showNotif(`${hardDelete ? "Deleted" : "Archived"} ${deleted} product${deleted > 1 ? "s" : ""}`);
      setPage(1);
      await loadProducts();
    } catch (error) {
      showNotif(error?.response?.data?.detail || "Delete all failed", "error");
    }
  };

  const handleCleanupJunk = async () => {
    try {
      const res = await productsAPI.cleanupJunk();
      const n = res?.data?.cleaned ?? 0;
      showNotif(n > 0
        ? `🧹 Removed ${n} junk products (code-like names / StockCodes)`
        : "✅ No junk products found — everything looks clean!");
      if (n > 0) await loadProducts();
    } catch (err) {
      showNotif(err?.response?.data?.detail || "Cleanup failed", "error");
    }
  };

  const updateField = (key, val) => setForm(prev => ({ ...prev, [key]: val }));



  if (viewProduct) {
    const p = viewProduct;
    const s = statusCfg[p.stock_status];
    const margin = p.cost_price ? ((p.current_price - p.cost_price) / p.current_price * 100).toFixed(1) : null;
    const categoryName = p.category_name
      || (p.category_id != null ? categories.find(c => String(c.id) === String(p.category_id))?.name : null)
      || "Uncategorized";
    return (
      <div style={styles.page}>
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
        <main style={styles.main}>
          <button onClick={() => setViewProduct(null)} style={styles.backBtn}><I.Back /> <span>Back to Products</span></button>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: 24, marginTop: 20 }}>
            {/* Left: Product Info */}
            <div style={styles.card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
                <div>
                  <span style={{ ...styles.badge, background: s.bg, color: s.text }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: s.dot, display: "inline-block" }} /> {s.label}</span>
                  <h2 style={{ fontSize: 24, fontWeight: 700, margin: "12px 0 4px" }}>{p.name}</h2>
                  <p style={{ color: "#94a3b8", fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}>{p.sku}</p>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => { openEdit(p); setViewProduct(null); }} style={styles.iconBtn}><I.Edit /></button>
                  <button onClick={() => setDeleteConfirm(p)} style={{ ...styles.iconBtn, borderColor: "#fecaca", color: "#dc2626" }}><I.Trash /></button>
                </div>
              </div>
              {p.description && <p style={{ color: "#64748b", fontSize: 14, lineHeight: 1.6, margin: "0 0 24px", padding: "16px", background: "#f8fafc", borderRadius: 10 }}>{p.description}</p>}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
                {[
                  { label: "Base Price", value: fmt(p.base_price), sub: "Original" },
                  { label: "Current Price", value: fmt(p.current_price), sub: p.current_price !== p.base_price ? `${((p.current_price - p.base_price) / p.base_price * 100).toFixed(0)}% ${p.current_price > p.base_price ? "above" : "below"}` : "No change", color: p.current_price > p.base_price ? "#059669" : p.current_price < p.base_price ? "#dc2626" : "#94a3b8" },
                  { label: "Cost Price", value: p.cost_price ? fmt(p.cost_price) : "N/A", sub: margin ? `${margin}% margin` : "" },
                ].map((m, i) => (
                  <div key={i} style={{ padding: 16, background: "#f8fafc", borderRadius: 12 }}>
                    <p style={{ fontSize: 12, color: "#94a3b8", margin: 0, fontWeight: 500 }}>{m.label}</p>
                    <p style={{ fontSize: 22, fontWeight: 700, margin: "6px 0 2px", fontFamily: "'JetBrains Mono', monospace" }}>{m.value}</p>
                    {m.sub && <p style={{ fontSize: 11, color: m.color || "#94a3b8", margin: 0 }}>{m.sub}</p>}
                  </div>
                ))}
              </div>
            </div>

            {/* Right: Inventory Summary */}
            <div style={styles.card}>
              <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 20px" }}>Inventory Status</h3>
              <div style={{ textAlign: "center", padding: "20px 0 28px" }}>
                <p style={{ fontSize: 52, fontWeight: 700, margin: 0, fontFamily: "'JetBrains Mono', monospace", color: s.text }}>{p.current_stock}</p>
                <p style={{ fontSize: 14, color: "#64748b", margin: "4px 0 0" }}>units in stock</p>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 16px", background: "#f8fafc", borderRadius: 10 }}>
                  <span style={{ fontSize: 13, color: "#64748b" }}>Reorder Point</span>
                  <span style={{ fontSize: 14, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>{p.reorder_point}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 16px", background: "#f8fafc", borderRadius: 10 }}>
                  <span style={{ fontSize: 13, color: "#64748b" }}>Category</span>
                  <span style={{ fontSize: 14, fontWeight: 500 }}>{categoryName}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 16px", background: "#f8fafc", borderRadius: 10 }}>
                  <span style={{ fontSize: 13, color: "#64748b" }}>Stock Value</span>
                  <span style={{ fontSize: 14, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>{fmt(p.current_stock * p.current_price)}</span>
                </div>
              </div>
              <button
                style={{ ...styles.primaryBtn, width: "100%", marginTop: 20 }}
                onClick={() => router.push(`/dss?product_id=${p.id}`)}
              >
                Run DSS Analysis
              </button>
            </div>
          </div>
        </main>
        {deleteConfirm && <DeleteModal product={deleteConfirm} onConfirm={() => { handleDelete(deleteConfirm); setViewProduct(null); }} onCancel={() => setDeleteConfirm(null)} />}
        <GlobalStyles />
      </div>
    );
  }

  return (
    <div style={styles.page}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />

      <main style={styles.main}>
        {/* Notification */}
        {notification && (
          <div style={{
            position: "fixed", top: 24, right: 24, zIndex: 1000, padding: "14px 24px",
            borderRadius: 12, color: "white", fontWeight: 600, fontSize: 14,
            background: notification.type === "error" ? "#ef4444" : "#059669",
            boxShadow: "0 8px 30px rgba(0,0,0,0.15)", animation: "fadeSlideDown 0.3s ease",
          }}>{notification.msg}</div>
        )}

        {/* Page Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
          <div>
            <h2 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>Products</h2>
            <p style={{ fontSize: 14, color: "#94a3b8", margin: "4px 0 0" }}>{totalItems} products found</p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {selectedIds.length > 0 && (
              <button
                onClick={() => setBulkDeleteConfirm({ scope: "selected", count: selectedIds.length })}
                style={{ ...styles.secondaryBtn, borderColor: "#fecaca", color: "#dc2626", background: "#fef2f2" }}
              >
                <I.Trash /> Delete Selected ({selectedIds.length})
              </button>
            )}
            {totalItems > 0 && (
              <button
                onClick={() => setBulkDeleteConfirm({ scope: "all", count: totalItems })}
                style={{ ...styles.secondaryBtn, borderColor: "#fecaca", color: "#dc2626", background: "#fff5f5" }}
              >
                <I.Trash /> Delete All
              </button>
            )}
            <button
              onClick={handleCleanupJunk}
              title="Remove products with code-like names imported from UK Retail (StockCodes used as names)"
              style={{ ...styles.secondaryBtn, borderColor: "#fde68a", color: "#92400e", background: "#fffbeb" }}
            >
              🧹 Clean Junk
            </button>
            <button onClick={openArchivedModal} style={styles.secondaryBtn}>
              Archived Products
            </button>
            <button onClick={openAdd} style={styles.primaryBtn}><I.Plus /> Add Product</button>
          </div>
        </div>

        {/* Filters Row */}
        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          <div style={{ position: "relative", flex: 1, maxWidth: 360 }}>
            <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: "#94a3b8" }}><I.Search /></span>
            <input value={search} onChange={e => { setPage(1); setSearch(e.target.value); }} placeholder="Search by name or SKU..." style={styles.searchInput} />
          </div>
          <select value={catFilter} onChange={e => { setPage(1); setCatFilter(e.target.value); }} style={styles.select}>
            <option value="">All Categories</option>
            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={() => setShowQuickCategoryModal(true)} style={styles.secondaryBtn}>
            <I.Plus /> Create Category
          </button>
          {catFilter && (
            <button
              onClick={() => handleDeleteCategory(catFilter)}
              style={{ ...styles.secondaryBtn, borderColor: "#fecaca", color: "#dc2626", background: "#fff5f5" }}
            >
              <I.Trash /> Delete Category
            </button>
          )}
        </div>

        {/* Product Grid */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
          <span style={{ fontSize: 13, color: "#64748b" }}>Select all</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
          {filtered.map((p, i) => {
            const s = statusCfg[p.stock_status];
            const priceChanged = p.current_price !== p.base_price;
            return (
              <div key={p.id} style={{ ...styles.card, cursor: "pointer", transition: "all 0.2s", animation: `fadeSlideUp 0.4s ease ${i * 0.04}s both` }}
                onClick={() => openView(p)}
                onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 25px rgba(0,0,0,0.08)"; }}
                onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)"; }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(p.id)}
                        onChange={() => toggleSelected(p.id)}
                        onClick={e => e.stopPropagation()}
                      />
                      <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.5px" }}>{p.sku}</p>
                    </div>
                    <h3 style={{ fontSize: 16, fontWeight: 600, margin: "6px 0 4px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</h3>
                    {p.category_name && <span style={{ fontSize: 12, color: "#64748b", background: "#f1f5f9", padding: "2px 8px", borderRadius: 4 }}>{p.category_name}</span>}
                  </div>
                  <span style={{ ...styles.badge, background: s.bg, color: s.text, flexShrink: 0 }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot, display: "inline-block" }} /> {s.label}
                  </span>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginTop: 20, paddingTop: 16, borderTop: "1px solid #f1f5f9" }}>
                  <div>
                    <p style={{ fontSize: 11, color: "#94a3b8", margin: 0 }}>Price</p>
                    <p style={{ fontSize: 16, fontWeight: 700, margin: "4px 0 0", fontFamily: "'JetBrains Mono', monospace" }}>{fmt(p.current_price)}</p>
                    {priceChanged && <p style={{ fontSize: 10, margin: "2px 0 0", color: p.current_price > p.base_price ? "#059669" : "#dc2626" }}>
                      {p.current_price > p.base_price ? "▲" : "▼"} {Math.abs(((p.current_price - p.base_price) / p.base_price) * 100).toFixed(0)}%
                    </p>}
                  </div>
                  <div>
                    <p style={{ fontSize: 11, color: "#94a3b8", margin: 0 }}>Stock</p>
                    <p style={{ fontSize: 16, fontWeight: 700, margin: "4px 0 0", fontFamily: "'JetBrains Mono', monospace", color: s.text }}>{p.current_stock}</p>
                  </div>
                  <div>
                    <p style={{ fontSize: 11, color: "#94a3b8", margin: 0 }}>ROP</p>
                    <p style={{ fontSize: 16, fontWeight: 700, margin: "4px 0 0", fontFamily: "'JetBrains Mono', monospace" }}>{p.reorder_point}</p>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                  <button onClick={e => { e.stopPropagation(); openEdit(p); }} style={{ ...styles.smallBtn, flex: 1 }}><I.Edit /> Edit</button>
                  <button onClick={e => { e.stopPropagation(); openView(p); }} style={{ ...styles.smallBtn, flex: 1, background: "#f0f9ff", color: "#0284c7", borderColor: "#bae6fd" }}><I.Eye /> View</button>
                  <button onClick={e => { e.stopPropagation(); setDeleteConfirm(p); }} style={{ ...styles.smallBtn, background: "#fef2f2", color: "#dc2626", borderColor: "#fecaca" }}><I.Trash /></button>
                </div>
              </div>
            );
          })}
        </div>

        {totalPages > 1 && (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page <= 1}
                style={{ ...styles.secondaryBtn, opacity: page <= 1 ? 0.6 : 1 }}
              >
                Prev
              </button>
              <span style={{ fontSize: 13, color: "#64748b" }}>Page {page} of {totalPages}</span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                style={{ ...styles.secondaryBtn, opacity: page >= totalPages ? 0.6 : 1 }}
              >
                Next
              </button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13, color: "#64748b" }}>Rows</span>
              <select
                value={pageSize}
                onChange={e => { setPage(1); setPageSize(Number(e.target.value)); }}
                style={{ ...styles.select, minWidth: 80, padding: "8px 12px" }}
              >
                {[12, 24, 48].map(size => (
                  <option key={size} value={size}>{size}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: 60, color: "#94a3b8" }}>
            <p style={{ fontSize: 18, fontWeight: 600 }}>No products found</p>
            <p style={{ fontSize: 14 }}>Try adjusting your search or filters</p>
          </div>
        )}
      </main>

      {/* Add/Edit Modal */}
      {showModal && (
        <div style={styles.overlay} onClick={() => setShowModal(false)}>
          <div style={styles.modal} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
              <h3 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>{editingProduct ? "Edit Product" : "Add New Product"}</h3>
              <button onClick={() => setShowModal(false)} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: 4 }}><I.X /></button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <FormField label="SKU *" value={form.sku} onChange={v => updateField("sku", v)} placeholder="e.g. ELEC-004" disabled={!!editingProduct} />
              <FormField label="Category" type="select" value={form.category_id} onChange={v => updateField("category_id", v)} options={categories} />
              <div style={{ gridColumn: "1 / -1", display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "end" }}>
                <FormField
                  label="Create Category"
                  value={newCategoryName}
                  onChange={setNewCategoryName}
                  placeholder="e.g. Electronics"
                />
                <button
                  onClick={handleCreateCategory}
                  disabled={creatingCategory || !newCategoryName.trim()}
                  style={{
                    ...styles.secondaryBtn,
                    height: 40,
                    opacity: creatingCategory || !newCategoryName.trim() ? 0.6 : 1,
                    cursor: creatingCategory || !newCategoryName.trim() ? "not-allowed" : "pointer",
                  }}
                >
                  {creatingCategory ? "Adding..." : "Add Category"}
                </button>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <FormField label="Product Name *" value={form.name} onChange={v => updateField("name", v)} placeholder="e.g. Wireless Mouse" />
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <FormField label="Description" value={form.description} onChange={v => updateField("description", v)} placeholder="Product description..." multiline />
              </div>
              <FormField label="Base Price ($) *" value={form.base_price} onChange={v => updateField("base_price", v)} type="number" placeholder="0.00" />
              <FormField label="Cost Price ($)" value={form.cost_price} onChange={v => updateField("cost_price", v)} type="number" placeholder="0.00" />
              <FormField label="Current Price ($)" value={form.current_price} onChange={v => updateField("current_price", v)} type="number" placeholder="Same as base" />
              {!editingProduct && <FormField label="Initial Stock" value={form.initial_stock} onChange={v => updateField("initial_stock", v)} type="number" placeholder="0" />}
            </div>

            <div style={{ display: "flex", gap: 12, marginTop: 28, justifyContent: "flex-end" }}>
              <button onClick={() => setShowModal(false)} style={styles.secondaryBtn}>Cancel</button>
              <button onClick={handleSave} style={styles.primaryBtn}>{editingProduct ? "Save Changes" : "Create Product"}</button>
            </div>
          </div>
        </div>
      )}

      {/* Quick Create Category Modal */}
      {showQuickCategoryModal && (
        <div style={styles.overlay} onClick={() => setShowQuickCategoryModal(false)}>
          <div style={{ ...styles.modal, maxWidth: 420 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
              <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Create Category</h3>
              <button
                onClick={() => setShowQuickCategoryModal(false)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: 4 }}
              >
                <I.X />
              </button>
            </div>

            <FormField
              label="Category Name"
              value={quickCategoryName}
              onChange={setQuickCategoryName}
              placeholder="e.g. Electronics"
            />

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 18 }}>
              <button onClick={() => setShowQuickCategoryModal(false)} style={styles.secondaryBtn}>Cancel</button>
              <button
                onClick={handleQuickCreateCategory}
                disabled={creatingQuickCategory || !quickCategoryName.trim()}
                style={{
                  ...styles.primaryBtn,
                  opacity: creatingQuickCategory || !quickCategoryName.trim() ? 0.6 : 1,
                  cursor: creatingQuickCategory || !quickCategoryName.trim() ? "not-allowed" : "pointer",
                }}
              >
                {creatingQuickCategory ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Archived Products Modal */}
      {showArchivedModal && (
        <div style={styles.overlay} onClick={() => setShowArchivedModal(false)}>
          <div style={{ ...styles.modal, maxWidth: 760 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
              <div>
                <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Archived Products</h3>
                <p style={{ fontSize: 13, color: "#64748b", margin: "4px 0 0" }}>Restore products that were archived earlier.</p>
              </div>
              <button
                onClick={() => setShowArchivedModal(false)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: 4 }}
              >
                <I.X />
              </button>
            </div>

            {loadingArchived ? (
              <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Loading archived products...</div>
            ) : archivedProducts.length === 0 ? (
              <div style={{ padding: 24, textAlign: "center", color: "#94a3b8", background: "#f8fafc", borderRadius: 12 }}>
                No archived products found.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, maxHeight: 460, overflowY: "auto" }}>
                {archivedProducts.map((p) => (
                  <div key={p.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: 14, border: "1px solid #e2e8f0", borderRadius: 12, background: "#f8fafc" }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</div>
                      <div style={{ fontSize: 12, color: "#64748b", fontFamily: "'JetBrains Mono', monospace" }}>{p.sku}</div>
                    </div>
                    <button
                      onClick={() => handleUnarchive(p)}
                      style={{ ...styles.primaryBtn, background: "#059669", flexShrink: 0 }}
                    >
                      Restore
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
              <button onClick={() => setShowArchivedModal(false)} style={styles.secondaryBtn}>Close</button>
            </div>
          </div>
        </div>
      )}


      {/* Delete Confirmation */}
      {deleteConfirm && <DeleteModal product={deleteConfirm} onConfirm={() => handleDelete(deleteConfirm)} onCancel={() => setDeleteConfirm(null)} />}
      {bulkDeleteConfirm && (
        <BulkDeleteModal
          scope={bulkDeleteConfirm.scope}
          count={bulkDeleteConfirm.count}
          onCancel={() => setBulkDeleteConfirm(null)}
          onArchive={() => {
            if (bulkDeleteConfirm.scope === "selected") {
              handleBulkDelete(false);
            } else {
              handleDeleteAll(false);
            }
            setBulkDeleteConfirm(null);
          }}
          onHardDelete={() => {
            if (bulkDeleteConfirm.scope === "selected") {
              handleBulkDelete(true);
            } else {
              handleDeleteAll(true);
            }
            setBulkDeleteConfirm(null);
          }}
        />
      )}

      <GlobalStyles />
    </div>
  );
}


function FormField({ label, value, onChange, placeholder, type = "text", multiline, options, disabled }) {
  const base = {
    width: "100%", padding: multiline ? "10px 14px" : "10px 14px", borderRadius: 10,
    border: "1px solid #e2e8f0", fontSize: 14, outline: "none", transition: "border-color 0.2s",
    fontFamily: "inherit", background: disabled ? "#f8fafc" : "white",
  };
  return (
    <div>
      <label style={{ fontSize: 13, fontWeight: 600, color: "#374151", display: "block", marginBottom: 6 }}>{label}</label>
      {type === "select" ? (
        <select value={value} onChange={e => onChange(e.target.value)} style={base}>
          <option value="">Select...</option>
          {options?.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      ) : multiline ? (
        <textarea value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} rows={3} style={{ ...base, resize: "vertical" }} />
      ) : (
        <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} disabled={disabled} style={base}
          onFocus={e => e.target.style.borderColor = "#6366f1"} onBlur={e => e.target.style.borderColor = "#e2e8f0"} />
      )}
    </div>
  );
}

function DeleteModal({ product, onConfirm, onCancel }) {
  return (
    <div style={styles.overlay} onClick={onCancel}>
      <div style={{ ...styles.modal, maxWidth: 420, textAlign: "center" }} onClick={e => e.stopPropagation()}>
        <div style={{ width: 56, height: 56, borderRadius: "50%", background: "#fef2f2", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", color: "#dc2626" }}>
          <I.Trash />
        </div>
        <h3 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 8px" }}>Archive Product?</h3>
        <p style={{ fontSize: 14, color: "#64748b", margin: "0 0 24px" }}>
          <strong>"{product.name}"</strong> will be archived. You can restore it later.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
          <button onClick={onCancel} style={styles.secondaryBtn}>Cancel</button>
          <button onClick={onConfirm} style={{ ...styles.primaryBtn, background: "#dc2626" }}>Archive</button>
        </div>
      </div>
    </div>
  );
}

function BulkDeleteModal({ scope, count, onArchive, onHardDelete, onCancel }) {
  const scopeLabel = scope === "selected" ? "selected" : "all";
  return (
    <div style={styles.overlay} onClick={onCancel}>
      <div style={{ ...styles.modal, maxWidth: 460, textAlign: "center" }} onClick={e => e.stopPropagation()}>
        <div style={{ width: 56, height: 56, borderRadius: "50%", background: "#fef2f2", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", color: "#dc2626" }}>
          <I.Trash />
        </div>
        <h3 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 8px" }}>Delete Products?</h3>
        <p style={{ fontSize: 14, color: "#64748b", margin: "0 0 20px" }}>
          You are about to remove {count} {scopeLabel} product{count > 1 ? "s" : ""}.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          <button onClick={onCancel} style={styles.secondaryBtn}>Cancel</button>
          <button onClick={onArchive} style={{ ...styles.secondaryBtn, borderColor: "#e2e8f0" }}>Archive</button>
          <button onClick={onHardDelete} style={{ ...styles.primaryBtn, background: "#dc2626" }}>Delete Permanently</button>
        </div>
        <p style={{ fontSize: 12, color: "#94a3b8", margin: "14px 0 0", lineHeight: 1.6 }}>
          Archive keeps data in the database. Delete permanently removes related records.
        </p>
      </div>
    </div>
  );
}

function GlobalStyles() {
  return <style>{`
    @keyframes fadeSlideUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes fadeSlideDown { from { opacity: 0; transform: translateY(-12px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    * { box-sizing: border-box; }
    select { appearance: none; background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e"); background-position: right 10px center; background-repeat: no-repeat; background-size: 16px; padding-right: 36px !important; }
  `}</style>;
}

const styles = {
  page: { fontFamily: "'DM Sans', 'Segoe UI', system-ui, sans-serif", background: "#f8f9fb", minHeight: "100vh", color: "#1a1a2e" },
  main: { maxWidth: 1400, margin: "0 auto", padding: "32px 40px" },
  card: { background: "white", borderRadius: 16, padding: 24, border: "1px solid #e8eaef", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" },
  primaryBtn: { display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 20px", borderRadius: 10, border: "none", background: "#6366f1", color: "white", fontWeight: 600, fontSize: 14, cursor: "pointer", transition: "all 0.15s" },
  secondaryBtn: { display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 20px", borderRadius: 10, border: "1px solid #e2e8f0", background: "white", color: "#374151", fontWeight: 500, fontSize: 14, cursor: "pointer" },
  smallBtn: { display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#374151", fontWeight: 500, fontSize: 12, cursor: "pointer", transition: "all 0.15s" },
  iconBtn: { display: "flex", alignItems: "center", justifyContent: "center", width: 36, height: 36, borderRadius: 8, border: "1px solid #e2e8f0", background: "white", color: "#64748b", cursor: "pointer" },
  badge: { display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 600 },
  searchInput: { width: "100%", padding: "10px 14px 10px 40px", borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 14, outline: "none" },
  select: { padding: "10px 14px", borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 14, outline: "none", minWidth: 180, fontFamily: "inherit", cursor: "pointer" },
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 },
  modal: { background: "white", borderRadius: 20, padding: 32, maxWidth: 600, width: "90%", maxHeight: "90vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.2)", animation: "fadeSlideUp 0.3s ease" },
  backBtn: { display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 16px", borderRadius: 8, border: "1px solid #e2e8f0", background: "white", color: "#374151", fontWeight: 500, fontSize: 14, cursor: "pointer" },
  spinner: { width: 40, height: 40, border: "4px solid #ddd6fe", borderTop: "4px solid #6366f1", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto" },
};
