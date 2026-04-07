/**
 * Next.js App Router Layout
 * File: frontend/src/app/layout.tsx
 */

import './globals.css';
import AuthGuard from '@/components/AuthGuard';
import Navbar from '@/components/Navbar';
export const metadata = {
  title: 'Smart DSS — eCommerce Decision Support',
  description: 'Inventory & Pricing Optimization for eCommerce',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50">
        <AuthGuard>
          <Navbar />
          {children}
        </AuthGuard>
      </body>
    </html>
  );
}