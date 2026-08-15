import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { PwaProvider } from "@/components/pwa/PwaProvider";
import { ThemeProvider } from "@/components/theme/ThemeProvider";
import "katex/dist/katex.min.css";
import "./globals.css";

const description =
  "A focused GATE 2027 CSE roadmap with syllabus-locked revision notes, topic-wise practice, previous-year questions, sectional tests, and full-length mocks.";

const THEME_BOOTSTRAP_SCRIPT = `(() => {
  const root = document.documentElement;
  let preference = "system";
  try {
    const saved = window.localStorage.getItem("gatepath-theme");
    if (saved === "light" || saved === "dark" || saved === "system") preference = saved;
  } catch {}
  let systemDark = false;
  try {
    systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {}
  const resolved = preference === "system" ? (systemDark ? "dark" : "light") : preference;
  root.dataset.theme = resolved;
  root.dataset.themePreference = preference;
  root.style.colorScheme = resolved;
  const meta = document.querySelector('meta[name="theme-color"][data-gatepath-theme-color]');
  if (meta) meta.setAttribute("content", resolved === "dark" ? "#080808" : "#F7F7F7");
})();`;

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
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <meta
          name="theme-color"
          content="#F7F7F7"
          data-gatepath-theme-color
        />
        <script
          data-gatepath-theme-bootstrap
          dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }}
        />
      </head>
      <body>
        <ThemeProvider>
          <PwaProvider><AuthProvider>{children}</AuthProvider></PwaProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
