import type { Metadata } from "next";
import { headers } from "next/headers";
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
      default: "Gatepath 2027 · GATE CSE Preparation",
      template: "%s · Gatepath 2027",
    },
    description,
    applicationName: "Gatepath 2027",
    keywords: [
      "GATE 2027",
      "GATE CSE",
      "computer science preparation",
      "GATE mock test",
      "previous year questions",
    ],
    openGraph: {
      type: "website",
      siteName: "Gatepath 2027",
      title: "Gatepath 2027 · One clear path to GATE CSE",
      description,
      images: [{ url: "/og.png", width: 1730, height: 907, alt: "Gatepath 2027 study roadmap" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "Gatepath 2027 · One clear path to GATE CSE",
      description,
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
