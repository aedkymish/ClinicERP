"use client";
import { useEffect, useRef, useState } from "react";
import { useLookups } from "@/components/forms";
import { Button, Card, Checkbox, DataTable, Field, Input, PageHeader, Select, Textarea, useFeedback } from "@/components/ui";
import { api, API, downloadPost } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function SettingsPage() {
  const { t } = useI18n();
  const fb = useFeedback();
  const session = useSession();
  const lookups = useLookups();
  const { data, reload } = useApi<any>("/settings");
  const [v, setV] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const logo = useRef<HTMLInputElement>(null);
  const restoreFile = useRef<HTMLInputElement>(null);
  const importFile = useRef<HTMLInputElement>(null);
  const [importReport, setImportReport] = useState<any | null>(null);

  useEffect(() => {
    if (data) setV({
      dental: data.clinics.dental.name, derma: data.clinics.derma.name, dental_prefix: data.clinics.dental.prefix, derma_prefix: data.clinics.derma.prefix,
      currency: data.currency, currency_decimals: data.currency_decimals, vat_enabled: data.vat_enabled, vat_rate: data.vat_rate, time_zone: data.time_zone,
      shift_start: data.shift_start, grace_min: data.grace_min, work_days: data.work_days, rooms: data.rooms.join("\n"),
      expense_categories: data.expense_categories.join("\n"), default_language: data.default_language,
    });
  }, [data]);
  if (!v) return null;
  const set = (k: string, x: unknown) => setV((s: any) => ({ ...s, [k]: x }));
  const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/settings", {
        currency: v.currency, currency_decimals: Number(v.currency_decimals), vat_enabled: v.vat_enabled, vat_rate: Number(v.vat_rate), time_zone: v.time_zone,
        shift_start: v.shift_start, grace_min: Number(v.grace_min), work_days: Number(v.work_days), rooms: lines(v.rooms),
        expense_categories: lines(v.expense_categories), default_language: v.default_language,
        clinics: { dental: v.dental, derma: v.derma, dental_prefix: v.dental_prefix, derma_prefix: v.derma_prefix },
      });
      fb.ok(t("common.saved"));
      reload();
      session.reload();
    } catch (e) {
      fb.error(e);
    } finally {
      setBusy(false);
    }
  };

  const upload = async (path: string, file: File, extra?: Record<string, string>) => {
    const form = new FormData();
    form.append("file", file);
    for (const [k, x] of Object.entries(extra ?? {})) form.append(k, x);
    return api.post(path, form);
  };

  const restore = async () => {
    const file = restoreFile.current?.files?.[0];
    if (!file) return;
    const typed = await fb.confirm({ title: t("set.restore"), danger: true, message: t("set.restoreConfirm"), input: { label: "RESTORE", placeholder: "RESTORE" } });
    if (typed !== "RESTORE") return;
    try {
      await upload("/admin/restore", file, { confirm: "RESTORE" });
      fb.ok(t("common.saved"));
      window.location.href = "/login";
    } catch (e) {
      fb.error(e);
    }
  };

  const runImport = async (dry: boolean) => {
    const file = importFile.current?.files?.[0];
    if (!file) return;
    try {
      setImportReport(await upload("/admin/import-v1", file, { dry_run: String(dry) }));
      if (!dry) fb.ok(t("common.saved"));
    } catch (e) {
      fb.error(e);
    }
  };

  return (
    <>
      <PageHeader title={t("set.title")} actions={<Button variant="primary" loading={busy} onClick={save}>{t("common.save")}</Button>} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("set.clinics")}>
          <div className="grid grid-cols-3 gap-3">
            <Field label={`${t("clinic.dental")} · ${t("common.name")}`} className="col-span-2"><Input value={v.dental} onChange={(e) => set("dental", e.target.value)} /></Field>
            <Field label={t("set.prefix")}><Input value={v.dental_prefix} maxLength={5} onChange={(e) => set("dental_prefix", e.target.value.toUpperCase())} /></Field>
            <Field label={`${t("clinic.derma")} · ${t("common.name")}`} className="col-span-2"><Input value={v.derma} onChange={(e) => set("derma", e.target.value)} /></Field>
            <Field label={t("set.prefix")}><Input value={v.derma_prefix} maxLength={5} onChange={(e) => set("derma_prefix", e.target.value.toUpperCase())} /></Field>
          </div>
          <div className="mt-4 flex items-center gap-3">
            {data.has_logo && <img src={`${API}/settings/logo`} alt="" className="h-12 rounded border border-slate-200" />}
            <input ref={logo} type="file" accept="image/png,image/jpeg" className="hidden" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try { await upload("/settings/logo", f); reload(); fb.ok(t("common.saved")); } catch (err) { fb.error(err); }
            }} />
            <Button size="sm" onClick={() => logo.current?.click()}>{t("set.logo")}…</Button>
          </div>
        </Card>
        <Card title={`${t("set.currency")} · ${t("inv.vat")}`}>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("set.currency")}><Input value={v.currency} onChange={(e) => set("currency", e.target.value)} /></Field>
            <Field label={t("set.decimals")}><Select value={v.currency_decimals} onChange={(e) => set("currency_decimals", e.target.value)}>{[0, 2, 3].map((d) => <option key={d}>{d}</option>)}</Select></Field>
            <div className="flex items-end pb-2"><Checkbox label={t("set.vatEnabled")} checked={v.vat_enabled} onChange={(x) => set("vat_enabled", x)} /></div>
            <Field label={t("set.vatRate")}><Input type="number" min={0} max={100} step="any" value={v.vat_rate} disabled={!v.vat_enabled} onChange={(e) => set("vat_rate", e.target.value)} /></Field>
            <Field label={t("set.tz")} className="col-span-2">
              <Select value={v.time_zone} onChange={(e) => set("time_zone", e.target.value)}>{(lookups.time_zones.length ? lookups.time_zones : [v.time_zone]).map((z) => <option key={z}>{z}</option>)}</Select>
            </Field>
            <Field label={t("set.language")}><Select value={v.default_language} onChange={(e) => set("default_language", e.target.value)}><option value="en">English</option><option value="ar">العربية</option></Select></Field>
          </div>
        </Card>
        <Card title={t("nav.attendance")}>
          <div className="grid grid-cols-3 gap-3">
            <Field label={t("set.shift")}><Input type="time" value={v.shift_start} onChange={(e) => set("shift_start", e.target.value)} /></Field>
            <Field label={t("set.grace")}><Input type="number" min={0} value={v.grace_min} onChange={(e) => set("grace_min", e.target.value)} /></Field>
            <Field label={t("set.workDays")}><Input type="number" min={1} max={31} value={v.work_days} onChange={(e) => set("work_days", e.target.value)} /></Field>
          </div>
        </Card>
        <Card title={`${t("common.room")} · ${t("nav.expenses")}`}>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("set.rooms")}><Textarea rows={5} value={v.rooms} onChange={(e) => set("rooms", e.target.value)} /></Field>
            <Field label={t("set.expenseCats")}><Textarea rows={5} value={v.expense_categories} onChange={(e) => set("expense_categories", e.target.value)} /></Field>
          </div>
        </Card>
        <Card title={t("set.backup")} className="lg:col-span-2">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" onClick={() => downloadPost("/admin/backup", "clinic-backup.db").catch((e) => fb.error(e))}>{t("set.backupNow")}</Button>
            <span className="text-xs text-slate-500">{t("set.encryption")}: {data.encryption ? "✓" : "—"} · {t("set.offsite")}: {data.offsite || "—"}</span>
          </div>
          <h3 className="mb-1 mt-4 text-sm font-semibold">{t("set.nightly")}</h3>
          <DataTable rows={data.backups.slice(0, 10).map((b: any) => ({ ...b, id: b.name }))} columns={[
            { key: "name", header: t("common.name"), render: (b: any) => <a className="underline" href={`${API}/admin/backups/${encodeURIComponent(b.name)}`}>{b.name}</a> },
            { key: "created", header: t("common.date") },
            { key: "size", header: "KB", align: "end", render: (b: any) => Math.round(b.size / 1024) },
          ]} />
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3 dark:border-slate-700">
            <span className="text-sm font-semibold">{t("set.restore")}:</span>
            <input ref={restoreFile} type="file" accept=".db,.enc" className="text-sm" />
            <Button variant="danger" size="sm" onClick={restore}>{t("set.restore")}</Button>
          </div>
        </Card>
        <Card title={t("set.import")} className="lg:col-span-2">
          <p className="mb-2 text-sm text-slate-600 dark:text-slate-400">{t("set.importHint")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <input ref={importFile} type="file" accept=".json,application/json" className="text-sm" onChange={() => setImportReport(null)} />
            <Button size="sm" onClick={() => runImport(true)}>{t("set.dryRun")}</Button>
            <Button size="sm" variant="primary" disabled={!importReport?.dry_run} onClick={() => runImport(false)}>{t("set.importNow")}</Button>
          </div>
          {importReport && (
            <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-800">
              <ul className="flex flex-wrap gap-x-4">{Object.entries<number>(importReport.counts).map(([k, n]) => <li key={k}><strong>{n}</strong> {k}</li>)}</ul>
              {importReport.warnings.length > 0 && <ul className="mt-2 list-disc ps-5 text-amber-800 dark:text-amber-200">{importReport.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
