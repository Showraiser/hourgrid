import type { Metadata } from "next";
// one type family for the whole product, self-hosted (works offline)
import "@fontsource/ibm-plex-mono/300.css";
import "@fontsource/ibm-plex-mono/300-italic.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/400-italic.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/700.css";
import "./globals.css";
import { Header } from "@/components/Header";

export const metadata: Metadata = {
  title: "HourGrid",
  description: "Peer-to-peer rooftop solar trading with hourly clean-energy certificates",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Header />
          {children}
        </div>
      </body>
    </html>
  );
}
