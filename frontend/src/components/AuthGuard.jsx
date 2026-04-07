'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { isAuthenticated } from '@/lib/api';

export default function AuthGuard({ children }) {
  const router   = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (pathname === '/login') {
      setChecked(true);
      return;
    }
    if (!isAuthenticated()) {
      router.replace('/login');
      return;
    }
    setChecked(true);
  }, [pathname]);

  if (!checked) {
    // Blank screen while checking — avoids flash of protected content
    return (
      <div style={{
        minHeight: '100vh',
        background: '#f8f9fb',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          border: '3px solid #e8eaef',
          borderTop: '3px solid #6366f1',
          animation: 'spin 0.7s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  return children;
}
