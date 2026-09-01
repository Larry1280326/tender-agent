import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tender Pipeline",
  description: "香港公開招標項目處理",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-Hant">
      <body className="min-h-screen bg-slate-100 text-slate-900 antialiased">
        {children}
      </body>
    </html>
  );
}
