import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import { FeedbackProvider } from "@/components/ui";
import { I18nProvider, type Lang } from "@/lib/i18n";
import "./globals.css";

export const metadata: Metadata = { title: "ClinicERP", description: "Dental & dermatology clinic management" };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const lang = ((await cookies()).get("lang")?.value === "ar" ? "ar" : "en") as Lang;
  return (
    <html lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <body>
        <I18nProvider initial={lang}>
          <FeedbackProvider>{children}</FeedbackProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
