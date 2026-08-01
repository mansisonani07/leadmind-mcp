import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as SonnerToaster } from "@/components/ui/sonner";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "LeadMind MCP — AI Lead Management CRM",
  description:
    "Conversational AI lead management powered by MCP. Free-tier only: Groq LLM + SQLite. Built with caching, fallback, and demo-safe reliability engineering.",
  keywords: [
    "MCP",
    "Model Context Protocol",
    "Lead Management",
    "CRM",
    "AI",
    "Groq",
    "Claude Desktop",
  ],
  authors: [{ name: "LeadMind MCP" }],
  icons: {
    icon: "https://z-cdn.chatglm.cn/z-ai/static/logo.svg",
  },
  openGraph: {
    title: "LeadMind MCP — AI Lead Management CRM",
    description:
      "Conversational AI lead management powered by MCP. Free-tier only: Groq LLM + SQLite.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
        <SonnerToaster richColors closeButton position="top-right" />
      </body>
    </html>
  );
}
