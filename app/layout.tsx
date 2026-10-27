import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "車両収支管理 | 迫トラック",
  description: "拠点・車種・車番で毎月の収支を見える化",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body className="antialiased">{children}</body>
    </html>
  );
}
