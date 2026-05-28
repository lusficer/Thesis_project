'use client';

import { useState, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import api from '@/lib/api';
import { setToken, setCachedUser } from '@/lib/api';

const C = {
  bg:      '#f8f9fb',
  surface: '#ffffff',
  border:  '#e8eaef',
  accent:  '#6366f1',
  danger:  '#dc2626',
  text:    '#1a1a2e',
  muted:   '#64748b',
  subtle:  '#94a3b8',
};

type LoginErrors = {
  email?: string;
  password?: string;
};

type RegisterErrors = {
  email?: string;
  password?: string;
  confirm?: string;
};

type FieldProps = {
  label: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  placeholder?: string;
  autoComplete?: string;
};

function Field({ label, type = 'text', value, onChange, error, placeholder, autoComplete }: FieldProps) {
  const [focused, setFocused] = useState(false);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: C.muted, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          padding: '11px 14px',
          borderRadius: 10,
          border: `1.5px solid ${error ? C.danger : focused ? C.accent : C.border}`,
          fontSize: 14,
          color: C.text,
          background: C.surface,
          outline: 'none',
          transition: 'border-color 0.15s',
          fontFamily: 'inherit',
          width: '100%',
          boxSizing: 'border-box',
        }}
      />
      {error && (
        <p style={{ fontSize: 12, color: C.danger, margin: 0 }}>{error}</p>
      )}
    </div>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState('login'); // 'login' | 'register'

  // Login state
  const [loginEmail,    setLoginEmail]    = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginErrors,   setLoginErrors]   = useState<LoginErrors>({});
  const [loginApiError, setLoginApiError] = useState('');
  const [loginLoading,  setLoginLoading]  = useState(false);

  // Register state
  const [regName,     setRegName]     = useState('');
  const [regEmail,    setRegEmail]    = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirm,  setRegConfirm]  = useState('');
  const [regErrors,   setRegErrors]   = useState<RegisterErrors>({});
  const [regApiError, setRegApiError] = useState('');
  const [regLoading,  setRegLoading]  = useState(false);

  const validateEmail = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);

  const validateLogin = () => {
    const errs: LoginErrors = {};
    if (!loginEmail)              errs.email    = 'Email is required';
    else if (!validateEmail(loginEmail)) errs.email = 'Invalid email format';
    if (!loginPassword)           errs.password = 'Password is required';
    else if (loginPassword.length < 6)  errs.password = 'At least 6 characters';
    setLoginErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const validateRegister = () => {
    const errs: RegisterErrors = {};
    if (!regEmail)               errs.email    = 'Email is required';
    else if (!validateEmail(regEmail)) errs.email = 'Invalid email format';
    if (!regPassword)            errs.password = 'Password is required';
    else if (regPassword.length < 6)   errs.password = 'At least 6 characters';
    if (!regConfirm)             errs.confirm  = 'Please confirm your password';
    else if (regConfirm !== regPassword) errs.confirm = 'Passwords do not match';
    setRegErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleLogin = async () => {
    if (!validateLogin()) return;
    setLoginLoading(true);
    setLoginApiError('');
    try {
      const res = await api.post('/auth/login', {
        email:    loginEmail,
        password: loginPassword,
      });
      setToken(res.data.access_token);
      // Fetch and cache user info
      const me = await api.get('/auth/me');
      setCachedUser(me.data);
      router.push('/');
    } catch (e: any) {
      setLoginApiError(e?.response?.data?.detail || 'Login failed. Check your credentials.');
    } finally {
      setLoginLoading(false);
    }
  };

  const handleRegister = async () => {
    if (!validateRegister()) return;
    setRegLoading(true);
    setRegApiError('');
    try {
      await api.post('/auth/register', {
        email:     regEmail,
        password:  regPassword,
        full_name: regName.trim() || undefined,
      });
      const res = await api.post('/auth/login', {
        email:    regEmail,
        password: regPassword,
      });
      setToken(res.data.access_token);
      const me = await api.get('/auth/me');
      setCachedUser(me.data);
      router.push('/');
    } catch (e: any) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;

      if (status === 409) {
        setTab('login');
        setLoginEmail(regEmail);
        setLoginPassword('');
        setLoginApiError('Email already exists. Please sign in instead.');
        setRegApiError('');
      } else {
        setRegApiError(detail || 'Registration failed. Please try again.');
      }
    } finally {
      setRegLoading(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>, action: () => void) => {
    if (e.key === 'Enter') action();
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: C.bg,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: "'DM Sans', system-ui, sans-serif",
      padding: '24px 16px',
    }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet" />
      <style>{`
        @keyframes fadeUp { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
        * { box-sizing: border-box; }
      `}</style>

      <div style={{ width: '100%', maxWidth: 420, animation: 'fadeUp 0.4s ease' }}>

        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 10,
            padding: '8px 16px', borderRadius: 999,
            background: '#eef2ff', border: `1px solid ${C.border}`,
            marginBottom: 16,
          }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.accent, display: 'inline-block' }} />
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.accent }}>
              Decision Studio
            </span>
          </div>
          <h1 style={{ margin: 0, fontSize: 28, fontWeight: 800, color: C.text, letterSpacing: '-0.5px' }}>
            Smart DSS
          </h1>
          <p style={{ margin: '6px 0 0', fontSize: 13, color: C.muted }}>
            Inventory · Pricing · Forecasting
          </p>
        </div>

        {/* Card */}
        <div style={{
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: 20,
          boxShadow: '0 4px 24px rgba(0,0,0,0.06)',
          overflow: 'hidden',
        }}>

          {/* Tab bar */}
          <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}` }}>
            {[
              { key: 'login',    label: 'Sign In' },
              // { key: 'register', label: 'Create Account' },
            ].map(t => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                style={{
                  flex: 1, padding: '16px 0', border: 'none', cursor: 'pointer',
                  background: 'transparent', fontSize: 13, fontWeight: 700,
                  fontFamily: 'inherit', letterSpacing: '0.02em',
                  color: tab === t.key ? C.accent : C.subtle,
                  borderBottom: tab === t.key ? `2px solid ${C.accent}` : '2px solid transparent',
                  transition: 'all 0.15s',
                  marginBottom: -1,
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div style={{ padding: 28 }}>

            {tab === 'login' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                <Field
                  label="Email"
                  type="email"
                  value={loginEmail}
                  onChange={setLoginEmail}
                  error={loginErrors.email}
                  placeholder="you@example.com"
                  autoComplete="email"
                />
                <Field
                  label="Password"
                  type="password"
                  value={loginPassword}
                  onChange={setLoginPassword}
                  error={loginErrors.password}
                  placeholder="••••••••"
                  autoComplete="current-password"
                />

                {loginApiError && (
                  <div style={{
                    padding: '10px 14px', borderRadius: 8, fontSize: 13,
                    background: '#fef2f2', border: `1px solid ${C.danger}33`,
                    color: C.danger, fontWeight: 500,
                  }}>
                    {loginApiError}
                  </div>
                )}

                <button
                  onClick={handleLogin}
                  disabled={loginLoading}
                  onKeyDown={e => handleKeyDown(e, handleLogin)}
                  style={{
                    padding: '13px 0', borderRadius: 10, border: 'none',
                    background: loginLoading ? C.border : C.accent,
                    color: loginLoading ? C.muted : '#fff',
                    fontSize: 14, fontWeight: 800, fontFamily: 'inherit',
                    cursor: loginLoading ? 'not-allowed' : 'pointer',
                    letterSpacing: '0.02em', transition: 'all 0.15s',
                    marginTop: 4,
                  }}
                >
                  {loginLoading ? 'Signing in…' : 'Sign In →'}
                </button>
              </div>
            )}

            {tab === 'register' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                <Field
                  label="Full Name (optional)"
                  value={regName}
                  onChange={setRegName}
                  placeholder="Nguyen Van A"
                  autoComplete="name"
                />
                <Field
                  label="Email"
                  type="email"
                  value={regEmail}
                  onChange={setRegEmail}
                  error={regErrors.email}
                  placeholder="you@example.com"
                  autoComplete="email"
                />
                <Field
                  label="Password"
                  type="password"
                  value={regPassword}
                  onChange={setRegPassword}
                  error={regErrors.password}
                  placeholder="Min 6 characters"
                  autoComplete="new-password"
                />
                <Field
                  label="Confirm Password"
                  type="password"
                  value={regConfirm}
                  onChange={setRegConfirm}
                  error={regErrors.confirm}
                  placeholder="Repeat password"
                  autoComplete="new-password"
                />

                {regApiError && (
                  <div style={{
                    padding: '10px 14px', borderRadius: 8, fontSize: 13,
                    background: '#fef2f2', border: `1px solid ${C.danger}33`,
                    color: C.danger, fontWeight: 500,
                  }}>
                    {regApiError}
                  </div>
                )}

                <button
                  onClick={handleRegister}
                  disabled={regLoading}
                  style={{
                    padding: '13px 0', borderRadius: 10, border: 'none',
                    background: regLoading ? C.border : C.accent,
                    color: regLoading ? C.muted : '#fff',
                    fontSize: 14, fontWeight: 800, fontFamily: 'inherit',
                    cursor: regLoading ? 'not-allowed' : 'pointer',
                    letterSpacing: '0.02em', transition: 'all 0.15s',
                    marginTop: 4,
                  }}
                >
                  {regLoading ? 'Creating account…' : 'Create Account →'}
                </button>
              </div>
            )}
          </div>
        </div>

        <p style={{ textAlign: 'center', fontSize: 12, color: C.subtle, marginTop: 20 }}>
          Smart DSS · Thesis Project · 2024
        </p>
      </div>
    </div>
  );
}