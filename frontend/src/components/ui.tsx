"use client";
// Shared UI kit. Dialogs and toasts replace browser alert/confirm/prompt (UI-06).
import { cloneElement, createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- buttons
type BtnVariant = "primary" | "secondary" | "danger" | "ghost";
export function Button({
  variant = "secondary", size = "md", loading, className, children, ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md"; loading?: boolean }) {
  const styles: Record<BtnVariant, string> = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 border-transparent",
    secondary: "bg-white text-slate-800 border-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-100 dark:border-slate-600 dark:hover:bg-slate-700",
    danger: "bg-red-600 text-white hover:bg-red-700 border-transparent",
    ghost: "bg-transparent text-slate-700 border-transparent hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800",
  };
  return (
    <button
      type="button"
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        styles[variant], className,
      )}
      disabled={loading || rest.disabled}
      {...rest}
    >
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- form controls
const control =
  "block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800";

export function Field({ label, required, error, hint, children, className }: {
  label: string; required?: boolean; error?: string; hint?: string; children: React.ReactElement; className?: string;
}) {
  const id = useId();
  const child = cloneElement(children as React.ReactElement<Record<string, unknown>>, {
    id, "aria-invalid": Boolean(error) || undefined, "aria-describedby": error || hint ? `${id}-d` : undefined,
  });
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
        {required && <span className="ms-0.5 text-red-600" aria-hidden>*</span>}
      </label>
      {child}
      {(error || hint) && (
        <p id={`${id}-d`} className={cx("mt-1 text-xs", error ? "text-red-700 dark:text-red-400" : "text-slate-500")}>{error || hint}</p>
      )}
    </div>
  );
}

export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(control, p.className)} />;
export const Textarea = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea rows={3} {...p} className={cx(control, p.className)} />
);
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(control, "pe-8", p.className)} />;

export function Checkbox({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
      <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" checked={checked}
        disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** Edits an amount in major units while the value stays in minor units (cents). */
export function MoneyInput({ value, onChange, decimals, ...rest }: {
  value: number | null | undefined; onChange: (minor: number) => void; decimals: number;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  const factor = 10 ** decimals;
  const [text, setText] = useState(value != null ? (value / factor).toFixed(decimals) : "");
  useEffect(() => {
    const current = Math.round(Number(text || 0) * factor);
    if (value != null && current !== value) setText((value / factor).toFixed(decimals));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input {...rest} inputMode="decimal" className={cx(control, "tabular-nums", rest.className)} value={text}
      onChange={(e) => {
        const v = e.target.value.replace(/[^\d.]/g, "");
        setText(v);
        onChange(Math.round(Number(v || 0) * factor));
      }} />
  );
}

// ---------------------------------------------------------------- layout bits
export function Card({ title, actions, children, className, padded = true }: {
  title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string; padded?: boolean;
}) {
  return (
    <section className={cx("min-w-0 rounded-lg border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          {title && <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, actions, subtitle }: { title: string; actions?: React.ReactNode; subtitle?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">{title}</h1>
        {subtitle && <div className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "gray" | "blue" | "green" | "amber" | "red" | "purple" | "sky";
export function Badge({ tone = "gray", children }: { tone?: Tone; children: React.ReactNode }) {
  // -100 backgrounds with -800 text keep ≥ 4.5:1 contrast (WCAG 2.1 AA)
  const tones: Record<Tone, string> = {
    gray: "bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-100",
    blue: "bg-dental-100 text-dental-800 dark:bg-dental-800 dark:text-dental-50",
    purple: "bg-derma-100 text-derma-800 dark:bg-derma-800 dark:text-derma-50",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
    amber: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
    red: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100",
    sky: "bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100",
  };
  return <span className={cx("inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function ClinicBadge({ clinic }: { clinic: string | null | undefined }) {
  const { t } = useI18n();
  const c = clinic ?? "shared";
  return <Badge tone={c === "dental" ? "blue" : c === "derma" ? "purple" : "gray"}>{t(`clinic.${c}`)}</Badge>;
}

const STATUS_TONES: Record<string, Tone> = {
  Scheduled: "gray", Confirmed: "sky", "Checked-in": "amber", "In progress": "purple", Completed: "green",
  Cancelled: "red", "No-show": "red", Draft: "gray", Posted: "blue", Void: "red", Paid: "green", Partial: "amber",
  Unpaid: "red", Credit: "sky", Approved: "blue", Present: "green", Late: "amber", Absent: "red",
  "Paid leave": "sky", "Unpaid leave": "purple", "Day off": "gray",
};
export function StatusBadge({ status, prefix }: { status: string; prefix: string }) {
  const { t } = useI18n();
  return <Badge tone={STATUS_TONES[status] ?? "gray"}>{t(`${prefix}${status}`)}</Badge>;
}

export function Spinner() {
  return <span role="status" aria-label="loading" className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />;
}

export function Empty({ children }: { children?: React.ReactNode }) {
  const { t } = useI18n();
  return <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{children ?? t("common.none")}</p>;
}

export function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "red" | "green" }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className={cx("mt-1 text-2xl font-semibold tabular-nums", tone === "red" ? "text-red-700 dark:text-red-400" : tone === "green" ? "text-emerald-700 dark:text-emerald-400" : "text-slate-900 dark:text-white")}>{value}</div>
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-700">
      {tabs.map((tb) => (
        <button key={tb.id} role="tab" aria-selected={active === tb.id} type="button" onClick={() => onChange(tb.id)}
          className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
            active === tb.id ? "border-brand-600 text-brand-700 dark:text-brand-100" : "border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400")}>
          {tb.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- table
export interface Column<T> {
  key: string;
  header: React.ReactNode;
  render?: (row: T) => React.ReactNode;
  className?: string;
  align?: "end";
}

export function DataTable<T extends { id?: number | string }>({ columns, rows, loading, onRowClick, empty, footer }: {
  columns: Column<T>[]; rows: T[] | null | undefined; loading?: boolean; onRowClick?: (r: T) => void; empty?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">
        <thead className="bg-slate-50 dark:bg-slate-800">
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cx("whitespace-nowrap px-3 py-2 text-start text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300", c.align === "end" && "text-end", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {loading && !rows?.length ? (
            <tr><td colSpan={columns.length} className="py-8 text-center"><Spinner /></td></tr>
          ) : !rows?.length ? (
            <tr><td colSpan={columns.length}><Empty>{empty}</Empty></td></tr>
          ) : (
            rows.map((r, i) => (
              <tr key={r.id ?? i} onClick={onRowClick ? () => onRowClick(r) : undefined}
                onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(r) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                className={cx(onRowClick && "cursor-pointer hover:bg-slate-50 focus:bg-slate-50 focus:outline-none dark:hover:bg-slate-800 dark:focus:bg-slate-800")}>
                {columns.map((c) => (
                  <td key={c.key} className={cx("px-3 py-2 align-top text-slate-800 dark:text-slate-200", c.align === "end" && "text-end tabular-nums", c.className)}>
                    {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
        {footer}
      </table>
    </div>
  );
}

export function Pagination({ page, total, pageSize, onPage }: { page: number; total: number; pageSize: number; onPage: (p: number) => void }) {
  const { t } = useI18n();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-400">
      <span>{t("common.rows", { n: total })}</span>
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>{t("common.prev")}</Button>
        <span>{t("common.page", { page, pages })}</span>
        <Button size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>{t("common.next")}</Button>
      </div>
    </div>
  );
}

export function ExportButtons({ onExport, pdf }: { onExport: (fmt: "csv" | "xlsx" | "pdf") => void; pdf?: boolean }) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-slate-300 dark:border-slate-600" role="group" aria-label="Export">
      {(["csv", "xlsx", ...(pdf ? ["pdf"] : [])] as const).map((f, i) => (
        <button key={f} type="button" onClick={() => onExport(f as "csv")}
          className={cx("bg-white px-2.5 py-2 text-xs font-medium uppercase text-slate-700 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-200", i > 0 && "border-s border-slate-300 dark:border-slate-600")}>
          {f === "xlsx" ? "Excel" : f}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- modal
export function Modal({ open, onClose, title, children, footer, size = "md" }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode; size?: "sm" | "md" | "lg" | "xl";
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    setTimeout(() => ref.current?.querySelector<HTMLElement>("input,select,textarea,button:not([data-close])")?.focus(), 0);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  const widths = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={cx("flex max-h-[92vh] w-full flex-col rounded-t-xl bg-white shadow-xl dark:bg-slate-900 sm:rounded-xl", widths[size])}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          <h2 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h2>
          <button type="button" data-close onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">✕</button>
        </div>
        <div className="overflow-y-auto px-4 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-4 py-3 dark:border-slate-700">{footer}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- toasts + confirm
interface Toast { id: number; text: string; tone: "ok" | "error" }
interface ConfirmOpts { title: string; message?: string; danger?: boolean; input?: { label: string; minLength?: number; placeholder?: string }; confirmLabel?: string }
interface Feedback {
  ok: (text: string) => void;
  error: (e: unknown) => void;
  confirm: (o: ConfirmOpts) => Promise<string | null>;
}

const FeedbackCtx = createContext<Feedback | null>(null);

export function errorText(e: unknown, t: (k: string) => string): string {
  if (e instanceof ApiError) return e.code === "stale" ? t("common.stale") : e.message;
  return e instanceof Error ? e.message : String(e);
}

export function FeedbackProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [pending, setPending] = useState<(ConfirmOpts & { resolve: (v: string | null) => void }) | null>(null);
  const [text, setText] = useState("");
  const push = useCallback((tx: string, tone: Toast["tone"]) => {
    const id = Date.now() + Math.random();
    setToasts((ts) => [...ts, { id, text: tx, tone }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), tone === "error" ? 7000 : 3500);
  }, []);
  const value: Feedback = {
    ok: (tx) => push(tx, "ok"),
    error: (e) => push(errorText(e, t), "error"),
    confirm: (o) => new Promise((resolve) => { setText(""); setPending({ ...o, resolve }); }),
  };
  const close = (v: string | null) => { pending?.resolve(v); setPending(null); };
  const inputOk = !pending?.input || text.trim().length >= (pending.input.minLength ?? 1);
  return (
    <FeedbackCtx.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4">
        {toasts.map((x) => (
          <div key={x.id} role={x.tone === "error" ? "alert" : "status"}
            className={cx("pointer-events-auto max-w-md rounded-md px-4 py-2 text-sm shadow-lg", x.tone === "ok" ? "bg-slate-900 text-white" : "bg-red-700 text-white")}>
            {x.text}
          </div>
        ))}
      </div>
      <Modal open={Boolean(pending)} onClose={() => close(null)} title={pending?.title ?? ""} size="sm"
        footer={<>
          <Button onClick={() => close(null)}>{t("common.cancel")}</Button>
          <Button variant={pending?.danger ? "danger" : "primary"} disabled={!inputOk}
            onClick={() => close(pending?.input ? text.trim() : "ok")}>{pending?.confirmLabel ?? t("common.confirm")}</Button>
        </>}>
        {pending?.message && <p className="mb-3 text-sm text-slate-700 dark:text-slate-300">{pending.message}</p>}
        {pending?.input && (
          <Field label={pending.input.label} required>
            <Textarea value={text} placeholder={pending.input.placeholder} onChange={(e) => setText(e.target.value)} />
          </Field>
        )}
      </Modal>
    </FeedbackCtx.Provider>
  );
}

export function useFeedback(): Feedback {
  const v = useContext(FeedbackCtx);
  if (!v) throw new Error("useFeedback outside provider");
  return v;
}

/** Form state helper with server field errors (UI-05). */
export function useForm<T extends Record<string, any>>(initial: T) {
  const [values, setValues] = useState<T>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof T>(k: K, v: T[K]) => setValues((s) => ({ ...s, [k]: v }));
  const bind = (k: keyof T & string) => ({
    value: (values[k] ?? "") as string,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => set(k, e.target.value as T[typeof k]),
  });
  const run = async (fn: () => Promise<void>, onError?: (e: unknown) => void) => {
    setBusy(true);
    setErrors({});
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fields).length) setErrors(e.fields);
      onError?.(e);
    } finally {
      setBusy(false);
    }
  };
  return { values, setValues, set, bind, errors, setErrors, busy, run };
}
