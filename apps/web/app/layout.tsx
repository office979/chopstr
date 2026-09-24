import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import "./caption-fonts.css";

export const metadata: Metadata = {
  title: {
    default: "chopstr",
    template: "%s · chopstr",
  },
  description:
    "Clipping für den DACH-Raum. Sinntreu geschnitten, jede Auswahl erklärt, EU-verarbeitet.",
  applicationName: "chopstr",
};

export const viewport: Viewport = {
  themeColor: "#000000",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">{children}</body>
    </html>
  );
}
