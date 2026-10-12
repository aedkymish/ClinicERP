"use client";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, setSessionListener } from "./api";
import { useI18n } from "./i18n";

export type Clinic = "dental" | "derma";
export type View = "both" | Clinic;

export interface PublicSettings {
  currency: string;
  currency_decimals: number;
  vat_enabled: boolean;
  vat_rate: number;
  time_zone: string;
  rooms: string[];
  expense_categories: string[];
  has_logo: boolean;
  default_language: "en" | "ar";
  clinics: Record<Clinic, { id: number; name: string; prefix: string }>;
}

export interface Me {
  id: number;
  username: string;
  role: string;
  clinic_scope: View;
  staff_id: number | null;
  name: string;
  must_change_pw: boolean;
  language: "en" | "ar";
  permissions: string[];
  settings: PublicSettings;
}

interface Session {
  me: Me;
  can: (...perms: string[]) => boolean;
  view: View;
  setView: (v: View) => void;
  /** clinic query param for the API ('' = everything the user may see) */
  clinicParam: string;
  settings: PublicSettings;
  reload: () => Promise<void>;
  logout: () => Promise<void>;
  fmt: Formatters;
}

export interface Formatters {
  money: (minor: number | null | undefined) => string;
  number: (n: number | null | undefined, digits?: number) => string;
  date: (iso: string | null | undefined) => string;
  dateTime: (iso: string | null | undefined) => string;
  toMinor: (major: string | number) => number;
  toMajor: (minor: number | null | undefined) => string;
}

const IDLE_MS = 30 * 60 * 1000;
const Ctx = createContext<Session | null>(null);

export function makeFormatters(lang: string, s: PublicSettings): Formatters {
  const locale = lang === "ar" ? "ar-EG" : "en-GB";
  const d = s.currency_decimals;
  const factor = 10 ** d;
  const num = new Intl.NumberFormat(locale, { minimumFractionDigits: d, maximumFractionDigits: d });
  const tz = s.time_zone || "UTC";
  return {
    money: (m) => `${num.format((m ?? 0) / factor)} ${s.currency}`,
    number: (n, digits = 0) =>
      new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(n ?? 0),
    date: (iso) => {
      if (!iso) return "—";
      const [y, mo, da] = iso.slice(0, 10).split("-").map(Number);
      return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(Date.UTC(y, mo - 1, da));
    },
    dateTime: (iso) =>
      iso ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: tz }).format(new Date(iso)) : "—",
    toMinor: (major) => Math.round(Number(String(major).replace(/,/g, "")) * factor),
    toMajor: (minor) => ((minor ?? 0) / factor).toFixed(d),
  };
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { lang, setLang } = useI18n();
  const [me, setMe] = useState<Me | null>(null);
  const [view, setViewState] = useState<View>("both");

  const load = useCallback(async () => {
    const data = await api.get<Me>("/auth/me");
    setMe(data);
    if (data.must_change_pw) router.replace("/change-password");
  }, [router]);

  useEffect(() => {
    setSessionListener((reason) => router.replace(`/login?reason=${encodeURIComponent(reason)}`));
    load().catch(() => router.replace("/login"));
    try {
      const saved = localStorage.getItem("clinic-view") as View | null;
      if (saved) setViewState(saved);
    } catch {
      /* storage unavailable — keep default */
    }
  }, [load, router]);

  useEffect(() => {
    if (me && me.language !== lang && !document.cookie.includes("lang=")) setLang(me.language);
  }, [me, lang, setLang]);

  const logout = useCallback(async () => {
    await api.post("/auth/logout").catch(() => {});
    router.replace("/login");
  }, [router]);

  // AUTH-04: end idle sessions after 30 minutes without user activity
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!me) return;
    const reset = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        api.post("/auth/logout").catch(() => {});
        router.replace("/login?reason=idle");
      }, IDLE_MS);
    };
    const events = ["mousedown", "keydown", "touchstart", "scroll"];
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    reset();
    return () => {
      events.forEach((e) => window.removeEventListener(e, reset));
      if (timer.current) clearTimeout(timer.current);
    };
  }, [me, router]);

  const value = useMemo<Session | null>(() => {
    if (!me) return null;
    const effective: View = me.clinic_scope !== "both" ? me.clinic_scope : view;
    return {
      me,
      can: (...perms) => perms.some((p) => me.permissions.includes(p)),
      view: effective,
      setView: (v) => {
        setViewState(v);
        try {
          localStorage.setItem("clinic-view", v);
        } catch {
          /* ignore */
        }
      },
      clinicParam: effective === "both" ? "" : effective,
      settings: me.settings,
      reload: load,
      logout,
      fmt: makeFormatters(lang, me.settings),
    };
  }, [me, view, lang, load, logout]);

  if (!value) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500" role="status">
        <span className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      </div>
    );
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession outside provider");
  return v;
}
