"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useSession, type View } from "@/lib/session";
import { cx } from "./ui";

const ICONS: Record<string, string> = {
  dashboard: "M3 12l9-9 9 9M5 10v10h5v-6h4v6h5V10",
  patients: "M16 11a4 4 0 10-8 0 4 4 0 008 0zM4 21a8 8 0 0116 0",
  appointments: "M8 3v4M16 3v4M3 9h18M5 5h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z",
  visits: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2M9 13h6M9 17h4",
  billing: "M9 14l6-6M9.5 8.5h.01M14.5 13.5h.01M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z",
  services: "M7 7h10M7 12h10M7 17h6M4 3h16v18H4z",
  inventory: "M20 7l-8-4-8 4m16 0v10l-8 4m8-14l-8 4m0 10l-8-4V7m8 4L4 7",
  expenses: "M12 8c-2 0-3 .9-3 2s1 2 3 2 3 .9 3 2-1 2-3 2m0-8V6m0 10v2M4 4h16v16H4z",
  staff: "M17 20h5v-2a4 4 0 00-5-3.9M9 20H2v-2a4 4 0 015-3.9m10-5.1a3 3 0 11-6 0 3 3 0 016 0zM9 8a3 3 0 11-6 0 3 3 0 016 0z",
  users: "M15 7a3 3 0 11-6 0 3 3 0 016 0zM12 14c-4 0-7 2-7 4v2h14v-2c0-2-3-4-7-4zM19 8l2 2 3-3",
  attendance: "M12 8v4l3 3M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  payroll: "M3 6h18v12H3zM3 10h18M7 15h3",
  reports: "M9 17V9m4 8V5m4 12v-6M4 21h16",
  audit: "M9 12l2 2 4-4m5.6-4A12 12 0 0112 2.9 12 12 0 013.4 6 12 12 0 0012 21a12 12 0 008.6-15z",
  settings: "M10.3 4.3a1.7 1.7 0 013.4 0 1.7 1.7 0 002.6 1.1 1.7 1.7 0 012.4 2.4 1.7 1.7 0 001 2.5 1.7 1.7 0 010 3.4 1.7 1.7 0 00-1 2.6 1.7 1.7 0 01-2.4 2.4 1.7 1.7 0 00-2.6 1 1.7 1.7 0 01-3.4 0 1.7 1.7 0 00-2.5-1 1.7 1.7 0 01-2.4-2.4 1.7 1.7 0 00-1.1-2.6 1.7 1.7 0 010-3.4 1.7 1.7 0 001.1-2.5 1.7 1.7 0 012.4-2.4 1.7 1.7 0 002.5-1.1zM15 12a3 3 0 11-6 0 3 3 0 016 0z",
  profile: "M5.1 17.8A13.9 13.9 0 0112 16c2.5 0 4.8.7 6.9 1.8M15 10a3 3 0 11-6 0 3 3 0 016 0zm6 2a9 9 0 11-18 0 9 9 0 0118 0z",
};

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name]} />
    </svg>
  );
}

const NAV: { id: string; href: string; perms: string[] }[] = [
  { id: "dashboard", href: "/", perms: [] },
  { id: "patients", href: "/patients", perms: ["patients.read"] },
  { id: "appointments", href: "/appointments", perms: ["appointments.read"] },
  { id: "visits", href: "/visits", perms: ["visits.read"] },
  { id: "billing", href: "/billing", perms: ["billing.read"] },
  { id: "services", href: "/services", perms: ["services.read"] },
  { id: "inventory", href: "/inventory", perms: ["inventory.read"] },
  { id: "expenses", href: "/expenses", perms: ["expenses"] },
  { id: "staff", href: "/staff", perms: ["staff.read_all"] },
  { id: "attendance", href: "/attendance", perms: ["attendance.manage"] },
  { id: "payroll", href: "/payroll", perms: ["payroll.manage"] },
  { id: "reports", href: "/reports", perms: ["reports.full", "reports.commission_own", "reports.cash"] },
  { id: "users", href: "/users", perms: ["users"] },
  { id: "audit", href: "/audit", perms: ["audit"] },
  { id: "settings", href: "/settings", perms: ["settings"] },
  { id: "profile", href: "/profile", perms: [] },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const { me, can, view, setView, settings, logout } = useSession();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);

  const items = NAV.filter((n) => n.perms.length === 0 || can(...n.perms));
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const switchLang = () => {
    const next = lang === "ar" ? "en" : "ar";
    setLang(next);
    api.post("/auth/language", { language: next }).catch(() => {});
  };

  const sidebar = (
    <nav aria-label={t("nav.menu")} className="flex h-full flex-col gap-0.5 overflow-y-auto p-3">
      <div className="mb-4 flex items-center gap-2 px-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">C</div>
        <span className="font-semibold">{t("app.name")}</span>
      </div>
      {items.map((n) => (
        <Link key={n.id} href={n.href} aria-current={active(n.href) ? "page" : undefined}
          className={cx("flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
            active(n.href) ? "bg-brand-50 text-brand-700 dark:bg-slate-800 dark:text-white" : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800")}>
          <Icon name={n.id} />
          {t(`nav.${n.id}`)}
        </Link>
      ))}
    </nav>
  );

  const viewBorder = view === "dental" ? "border-t-dental-600" : view === "derma" ? "border-t-derma-600" : "border-t-brand-600";

  return (
    <div className={cx("min-h-screen border-t-4 lg:flex", viewBorder)}>
      <aside className="no-print hidden w-60 shrink-0 border-e border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:block">
        <div className="sticky top-0 h-screen">{sidebar}</div>
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 start-0 w-64 bg-white shadow-xl dark:bg-slate-900">{sidebar}</div>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="no-print sticky top-0 z-30 flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
          <button type="button" className="rounded-md p-2 hover:bg-slate-100 dark:hover:bg-slate-800 lg:hidden" onClick={() => setOpen(true)} aria-label={t("nav.menu")}>
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}><path d="M4 6h16M4 12h16M4 18h16" /></svg>
          </button>
          {me.clinic_scope === "both" ? (
            <div role="group" aria-label={t("common.clinic")} className="inline-flex overflow-hidden rounded-md border border-slate-300 text-sm dark:border-slate-600">
              {(["both", "dental", "derma"] as View[]).map((v) => (
                <button key={v} type="button" onClick={() => setView(v)} aria-pressed={view === v}
                  className={cx("px-3 py-1.5 font-medium",
                    view === v ? (v === "dental" ? "bg-dental-600 text-white" : v === "derma" ? "bg-derma-600 text-white" : "bg-brand-600 text-white")
                      : "bg-white text-slate-700 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-200")}>
                  {v === "both" ? t("clinic.both") : settings.clinics[v]?.name ?? t(`clinic.${v}`)}
                </button>
              ))}
            </div>
          ) : (
            <span className={cx("rounded-md px-3 py-1.5 text-sm font-medium text-white", me.clinic_scope === "dental" ? "bg-dental-600" : "bg-derma-600")}>
              {settings.clinics[me.clinic_scope as "dental"]?.name}
            </span>
          )}
          <div className="ms-auto flex items-center gap-2">
            <button type="button" onClick={switchLang} className="rounded-md px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800">
              {t("lang.switch")}
            </button>
            <Link href="/profile" className="hidden text-end sm:block">
              <div className="text-sm font-medium leading-tight">{me.name}</div>
              <div className="text-xs text-slate-500">{t(`role.${me.role}`)}</div>
            </Link>
            <button type="button" onClick={logout} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800">
              {t("auth.signout")}
            </button>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-5">{children}</main>
      </div>
    </div>
  );
}
