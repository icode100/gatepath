import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { PwaProvider } from "@/components/pwa/PwaProvider";
import "katex/dist/katex.min.css";
import "./globals.css";

const description =
  "A focused GATE 2027 CSE roadmap with syllabus-locked revision notes, topic-wise practice, previous-year questions, sectional tests, and full-length mocks.";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "http";
  const configuredOrigin = process.env.NEXT_PUBLIC_SITE_URL;
  const origin = configuredOrigin ?? (host ? `${protocol}://${host}` : "http://localhost:3000");

  return {
    metadataBase: new URL(origin),
    title: {
      default: "GatePath 2027 · GATE CSE Preparation",
      template: "%s · GatePath 2027",
    },
    description,
    applicationName: "GatePath 2027",
    keywords: [
      "GATE 2027",
      "GATE CSE",
      "computer science preparation",
      "GATE mock test",
      "previous year questions",
    ],
    openGraph: {
      type: "website",
      siteName: "GatePath 2027",
      title: "GatePath 2027 · One clear path to GATE CSE",
      description,
      images: [{ url: "/og.png", width: 1730, height: 907, alt: "GatePath 2027 study roadmap" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "GatePath 2027 · One clear path to GATE CSE",
      description,
      images: ["/og.png"],
    },
    appleWebApp: {
      capable: true,
      statusBarStyle: "black-translucent",
      title: "GatePath",
    },
    formatDetection: {
      telephone: false,
    },
    icons: {
      icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
      apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
    },
  };
}

export const viewport: Viewport = {
  colorScheme: "light dark",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F7F7F7" },
    { media: "(prefers-color-scheme: dark)", color: "#080808" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <PwaProvider><AuthProvider>{children}</AuthProvider></PwaProvider>
      </body>
    </html>
  );
}
