/**
 * Shared Header component — navigation + notifications + user menu.
 * File: frontend/src/components/Header.jsx
 */

"use client";
import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import api, { logout, getCachedUser, setCachedUser, getInitials, isAuthenticated } from "@/lib/api";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/" },
  { label: "Products",  href: "/products" },
  { label: "Inventory", href: "/inventory" },
  { label: "DSS Analysis", href: "/dss" },
];

const NOTIF_ICON = {
  low_stock:       { color: "#f59e0b", icon: "⚠" },
  out_of_stock:    { color: "#ef4444", icon: "🚨" },
  dss_completed:   { color: "#6366f1", icon: "✓" },
  price_updated:   { color: "#0891b2", icon: "$" },
  order_confirmed: { color: "#059669", icon: "📦" },
  stockout_warning:{ color: "#dc2626", icon: "🔴" },
};

export default function Header({ active = "Dashboard" }) {
  const [showNotifs,     setShowNotifs]     = useState(false);
  const [showUserMenu,   setShowUserMenu]   = useState(false);
  const [notifications,  setNotifications]  = useState([]);
  const [unreadCount,    setUnreadCount]    = useState(0);
  const [user,           setUser]           = useState(null);
  const [isAuthed,       setIsAuthed]       = useState(false);

  const notifRef   = useRef(null);
  const userRef    = useRef(null);

  useEffect(() => {
    const authed = isAuthenticated();
    setIsAuthed(authed);
    if (!authed) {
      setUser(null);
      setNotifications([]);
      setUnreadCount(0);
      return;
    }

    const cached = getCachedUser();
    if (cached) setUser(cached);
    api.get("/auth/me")
      .then(res => { setUser(res.data); setCachedUser(res.data); })
      .catch(() => { setUser(null); });
  }, []);

  useEffect(() => {
    if (!isAuthed) return;

    api.get("/notifications", { params: { limit: 20 } })
      .then(res => {
        const items = res.data?.items || [];
        setNotifications(items);
        setUnreadCount(res.data?.unread_count ?? items.filter(n => !n.is_read).length);
      })
      .catch(() => {
        // Fallback placeholder while API isn't wired
        setNotifications([]);
        setUnreadCount(0);
      });
  }, [isAuthed]);

  useEffect(() => {
    const handler = (e) => {
      if (notifRef.current && !notifRef.current.contains(e.target))  setShowNotifs(false);
      if (userRef.current  && !userRef.current.contains(e.target))   setShowUserMenu(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const markAllRead = () => {
    api.put("/notifications/read-all").catch(() => {});
    setUnreadCount(0);
    setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
  };

  const handleLogout = () => {
    setIsAuthed(false);
    setUser(null);
    setNotifications([]);
    setUnreadCount(0);
    setShowUserMenu(false);
    setShowNotifs(false);
    logout();
  };

  const initials = getInitials(user);

  return (
    <header style={{
      background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
      padding: "0 40px",
      color: "white",
      position: "sticky",
      top: 0,
      zIndex: 50,
    }}>
      <div style={{
        maxWidth: 1400, margin: "0 auto",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        height: 72,
      }}>

        {/* Logo */}
        <Link href="/" style={{ textDecoration: "none", color: "white" }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0, letterSpacing: "-0.5px" }}>
            <span style={{ color: "#38bdf8" }}>Smart</span> DSS
          </h1>
        </Link>

        {/* Nav + right controls */}
        <nav style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {NAV_ITEMS.map(item => (
            <Link key={item.label} href={item.href} style={{
              padding: "8px 18px", borderRadius: 8, textDecoration: "none",
              background: item.label === active ? "rgba(56,189,248,0.15)" : "transparent",
              color: item.label === active ? "#38bdf8" : "rgba(255,255,255,0.6)",
              fontWeight: item.label === active ? 600 : 400,
              fontSize: 14, transition: "all 0.15s",
            }}>
              {item.label}
            </Link>
          ))}

          {isAuthed && (
          <>
          <div ref={notifRef} style={{ position: "relative", marginLeft: 8 }}>
            <button
              onClick={() => { setShowNotifs(v => !v); setShowUserMenu(false); }}
              style={{
                position: "relative", background: "rgba(255,255,255,0.1)",
                border: "none", borderRadius: 10, width: 40, height: 40,
                cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                color: "white", transition: "background 0.15s",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.2)"}
              onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.1)"}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
              {unreadCount > 0 && (
                <span style={{
                  position: "absolute", top: -2, right: -2,
                  width: 18, height: 18, borderRadius: "50%",
                  background: "#ef4444", color: "white",
                  fontSize: 10, fontWeight: 700,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  border: "2px solid #0f172a",
                }}>
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </button>

            {/* Notifications dropdown */}
            {showNotifs && (
              <div style={{
                position: "absolute", top: "calc(100% + 8px)", right: 0,
                width: 380, background: "white", borderRadius: 16,
                boxShadow: "0 20px 60px rgba(0,0,0,0.25)", border: "1px solid #e2e8f0",
                overflow: "hidden", animation: "fadeSlideDown 0.2s ease",
                color: "#1e293b",
              }}>
                <div style={{
                  padding: "16px 20px", borderBottom: "1px solid #f1f5f9",
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                }}>
                  <h4 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>Notifications</h4>
                  {unreadCount > 0 && (
                    <button onClick={markAllRead} style={{ fontSize: 12, color: "#6366f1", fontWeight: 600, background: "none", border: "none", cursor: "pointer" }}>
                      Mark all read
                    </button>
                  )}
                </div>
                <div style={{ maxHeight: 380, overflowY: "auto" }}>
                  {notifications.length === 0 ? (
                    <p style={{ padding: 32, textAlign: "center", color: "#94a3b8", fontSize: 14, margin: 0 }}>No notifications</p>
                  ) : (
                    notifications.map(n => {
                      const cfg = NOTIF_ICON[n.type] || { color: "#94a3b8", icon: "•" };
                      return (
                        <div key={n.id} style={{
                          padding: "14px 20px", borderBottom: "1px solid #f8fafc",
                          background: n.is_read ? "white" : "#f0f9ff",
                          cursor: "pointer", transition: "background 0.15s",
                          display: "flex", gap: 12, alignItems: "flex-start",
                        }}
                          onMouseEnter={e => e.currentTarget.style.background = "#f8fafc"}
                          onMouseLeave={e => e.currentTarget.style.background = n.is_read ? "white" : "#f0f9ff"}
                        >
                          <span style={{
                            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                            background: cfg.color + "15", color: cfg.color,
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14,
                          }}>
                            {cfg.icon}
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <p style={{ fontSize: 13, fontWeight: n.is_read ? 400 : 600, margin: 0, lineHeight: 1.4 }}>{n.title}</p>
                            {n.message && <p style={{ fontSize: 12, color: "#94a3b8", margin: "3px 0 0" }}>{n.message}</p>}
                          </div>
                          {!n.is_read && (
                            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#6366f1", flexShrink: 0, marginTop: 4 }} />
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}
          </div>

          <div ref={userRef} style={{ position: "relative", marginLeft: 8 }}>
            <button
              onClick={() => { setShowUserMenu(v => !v); setShowNotifs(false); }}
              title={user?.full_name || user?.email || "Account"}
              style={{
                width: 38, height: 38, borderRadius: "50%",
                background: showUserMenu ? "#38bdf8" : "rgba(56,189,248,0.25)",
                border: "2px solid rgba(56,189,248,0.5)",
                cursor: "pointer", color: "white",
                fontSize: 12, fontWeight: 800, fontFamily: "inherit",
                display: "flex", alignItems: "center", justifyContent: "center",
                letterSpacing: "0.02em", transition: "all 0.15s",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "#38bdf8"}
              onMouseLeave={e => e.currentTarget.style.background = showUserMenu ? "#38bdf8" : "rgba(56,189,248,0.25)"}
            >
              {initials}
            </button>

            {/* User dropdown */}
            {showUserMenu && (
              <div style={{
                position: "absolute", top: "calc(100% + 8px)", right: 0,
                width: 210, background: "white", borderRadius: 14,
                boxShadow: "0 20px 60px rgba(0,0,0,0.2)", border: "1px solid #e2e8f0",
                overflow: "hidden", animation: "fadeSlideDown 0.2s ease",
                color: "#1e293b",
              }}>
                {/* User info */}
                <div style={{ padding: "14px 16px", borderBottom: "1px solid #f1f5f9" }}>
                  <p style={{ margin: 0, fontWeight: 700, fontSize: 13 }}>
                    {user?.full_name || "User"}
                  </p>
                  <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b", wordBreak: "break-all" }}>
                    {user?.email}
                  </p>
                  {user?.role && (
                    <span style={{
                      display: "inline-block", marginTop: 6,
                      fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
                      textTransform: "uppercase", color: "#6366f1",
                      background: "#eef2ff", padding: "2px 8px", borderRadius: 4,
                    }}>
                      {user.role}
                    </span>
                  )}
                </div>

                {/* Logout */}
                <button
                  onClick={handleLogout}
                  style={{
                    width: "100%", padding: "12px 16px",
                    border: "none", background: "transparent",
                    cursor: "pointer", textAlign: "left",
                    fontSize: 13, fontWeight: 600, color: "#dc2626",
                    fontFamily: "inherit",
                    display: "flex", alignItems: "center", gap: 8,
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = "#fef2f2"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  🚪 Sign Out
                </button>
              </div>
            )}
          </div>
          </>
          )}
        </nav>
      </div>

      <style>{`
        @keyframes fadeSlideDown {
          from { opacity: 0; transform: translateY(-8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </header>
  );
}
