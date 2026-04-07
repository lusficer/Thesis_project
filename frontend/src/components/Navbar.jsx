'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import api, { logout, getCachedUser, setCachedUser, getInitials, isAuthenticated } from '@/lib/api';

const NAV_LINKS = [
  { href: '/',          label: 'Dashboard',   icon: '📊' },
  { href: '/products',  label: 'Products',    icon: '📦' },
  { href: '/inventory', label: 'Inventory',   icon: '📋' },
  { href: '/dss',       label: 'DSS Analysis',icon: '🎯' },
];

const NOTIF_ICON = {
  low_stock:        { color: '#f59e0b', icon: '⚠' },
  out_of_stock:     { color: '#ef4444', icon: '🚨' },
  dss_completed:    { color: '#6366f1', icon: '✓' },
  price_updated:    { color: '#0891b2', icon: '$' },
  order_confirmed:  { color: '#059669', icon: '📦' },
  stockout_warning: { color: '#dc2626', icon: '🔴' },
};

export default function Navbar() {
  const pathname = usePathname();

  const [user,          setUser]          = useState(null);
  const [showUserMenu,  setShowUserMenu]  = useState(false);
  const [showNotifs,    setShowNotifs]    = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount,   setUnreadCount]   = useState(0);
  const [isAuthed,      setIsAuthed]      = useState(false);

  const userRef  = useRef(null);
  const notifRef = useRef(null);

  // ── Fetch user ────────────────────────────────────────────────────
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
    api.get('/auth/me')
      .then(res => { setUser(res.data); setCachedUser(res.data); })
      .catch(() => { setUser(null); });
  }, [pathname]);

  // ── Fetch notifications ───────────────────────────────────────────
  useEffect(() => {
    if (!isAuthed) return;

    api.get('/notifications', { params: { limit: 20 } })
      .then(res => {
        const items = res.data?.items || [];
        setNotifications(items);
        setUnreadCount(res.data?.unread_count ?? items.filter(n => !n.is_read).length);
      })
      .catch(() => {});
  }, [isAuthed]);

  // ── Close dropdowns on outside click ─────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (userRef.current  && !userRef.current.contains(e.target))  setShowUserMenu(false);
      if (notifRef.current && !notifRef.current.contains(e.target)) setShowNotifs(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const markAllRead = () => {
    api.put('/notifications/read-all').catch(() => {});
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
    <nav className="bg-white shadow-sm border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">

          {/* Logo */}
          <div className="flex items-center">
            <Link href="/" className="flex items-center space-x-3">
              <div className="text-2xl">🛒</div>
              <span className="text-xl font-bold text-gray-900">Smart DSS</span>
            </Link>
          </div>

          {/* Nav links */}
          <div className="flex items-center space-x-1">
            {NAV_LINKS.map((link) => {
              const isActive = link.href === '/'
                ? pathname === '/'
                : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`flex items-center space-x-2 px-4 py-2 rounded-lg transition-colors duration-200 ${
                    isActive
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }`}
                >
                  <span className="text-lg">{link.icon}</span>
                  <span>{link.label}</span>
                </Link>
              );
            })}
          </div>

          {/* Right: bell + avatar */}
          {isAuthed && (
          <div className="flex items-center space-x-2">

            {/* ── Notification Bell ── */}
            <div ref={notifRef} className="relative">
              <button
                onClick={() => { setShowNotifs(v => !v); setShowUserMenu(false); }}
                className="relative p-2 rounded-lg text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
                {unreadCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 text-white text-xs font-bold rounded-full flex items-center justify-center border-2 border-white">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                )}
              </button>

              {/* Notif dropdown */}
              {showNotifs && (
                <div className="absolute right-0 mt-2 w-96 bg-white rounded-2xl shadow-2xl border border-gray-100 overflow-hidden z-50"
                  style={{ animation: 'fadeSlideDown 0.18s ease' }}>
                  <div className="flex justify-between items-center px-5 py-4 border-b border-gray-100">
                    <h4 className="text-sm font-bold text-gray-900">Notifications</h4>
                    {unreadCount > 0 && (
                      <button onClick={markAllRead} className="text-xs text-indigo-600 font-semibold hover:text-indigo-800">
                        Mark all read
                      </button>
                    )}
                  </div>
                  <div className="max-h-96 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <p className="text-center text-gray-400 text-sm py-10">No notifications</p>
                    ) : notifications.map(n => {
                      const cfg = NOTIF_ICON[n.type] || { color: '#94a3b8', icon: '•' };
                      return (
                        <div key={n.id}
                          className={`flex items-start gap-3 px-5 py-4 border-b border-gray-50 cursor-pointer transition-colors hover:bg-gray-50 ${!n.is_read ? 'bg-blue-50' : ''}`}
                        >
                          <span className="w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-sm"
                            style={{ background: cfg.color + '18', color: cfg.color }}>
                            {cfg.icon}
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className={`text-sm leading-snug ${n.is_read ? 'text-gray-700 font-normal' : 'text-gray-900 font-semibold'}`}>
                              {n.title}
                            </p>
                            {n.message && <p className="text-xs text-gray-400 mt-0.5">{n.message}</p>}
                          </div>
                          {!n.is_read && <span className="w-2 h-2 rounded-full bg-indigo-500 flex-shrink-0 mt-1.5" />}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* ── User Avatar ── */}
            <div ref={userRef} className="relative">
              <button
                onClick={() => { setShowUserMenu(v => !v); setShowNotifs(false); }}
                title={user?.full_name || user?.email || 'Account'}
                className="flex items-center space-x-2 px-2 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <div className="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center">
                  <span className="text-indigo-700 font-bold text-xs">{initials}</span>
                </div>
                <span className="text-sm text-gray-700 font-medium max-w-24 truncate">
                  {user?.full_name?.split(' ')[0] || user?.email?.split('@')[0] || 'User'}
                </span>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-gray-400">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>

              {/* User dropdown */}
              {showUserMenu && (
                <div className="absolute right-0 mt-2 w-52 bg-white rounded-2xl shadow-2xl border border-gray-100 overflow-hidden z-50"
                  style={{ animation: 'fadeSlideDown 0.18s ease' }}>
                  <div className="px-4 py-3 border-b border-gray-100">
                    <p className="text-sm font-bold text-gray-900 truncate">{user?.full_name || 'User'}</p>
                    <p className="text-xs text-gray-500 truncate mt-0.5">{user?.email}</p>
                    {user?.role && (
                      <span className="inline-block mt-2 text-xs font-bold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
                        {user.role}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={handleLogout}
                    className="w-full flex items-center gap-2 px-4 py-3 text-sm font-semibold text-red-600 hover:bg-red-50 transition-colors text-left"
                  >
                    🚪 Sign Out
                  </button>
                </div>
              )}
            </div>
          </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes fadeSlideDown {
          from { opacity: 0; transform: translateY(-6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </nav>
  );
}