"use client";
import { useEffect, useRef, useState } from "react";
import { Button, Card, ClinicBadge, DataTable, ExportButtons, Field, Input, Modal, MoneyInput, PageHeader, Pagination, Select, useFeedback } from "@/components/ui";
import { api, API, openFile } from "@/lib/api";
import { todayISO, useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function ExpensesPage() {
  const { t } = useI18n();
  const { clinicParam, settings, fmt } = useSession();
  const [from, setFrom] = useState(todayISO().slice(0, 8) + "01");
  const [to, setTo] = useState(todayISO());
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [edit, setEdit] = useState<any | null>(null);
  const params = { clinic: clinicParam, from, to, category, page };
  const { data, loading, reload } = useApi<any>("/expenses", params);

  return (
    <>
      <PageHeader title={t("exp.title")} actions={<Button variant="primary" onClick={() => setEdit({})}>+ {t("exp.new")}</Button>} />
      <Card padded={false}>
        <div className="grid grid-cols-2 items-end gap-3 border-b border-slate-200 p-3 dark:border-slate-700 md:grid-cols-5">
          <Field label={t("common.from")}><Input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} /></Field>
          <Field label={t("common.to")}><Input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} /></Field>
          <Field label={t("common.category")}>
            <Select value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }}>
              <option value="">{t("common.all")}</option>{settings.expense_categories.map((c) => <option key={c}>{c}</option>)}
            </Select>
          </Field>
          <div className="col-span-2 flex items-end justify-between gap-2 md:justify-end">
            <div className="text-end">
              <div className="text-xs text-slate-500">{t("exp.totalShown")}</div>
              <div className="text-lg font-semibold tabular-nums">{fmt.money(data?.total_amount)}</div>
            </div>
            <ExportButtons pdf onExport={(f) => openFile("/expenses", { ...params, page: undefined, format: f })} />
          </div>
        </div>
        <DataTable rows={data?.items} loading={loading} onRowClick={setEdit} columns={[
          { key: "date", header: t("common.date"), render: (e: any) => fmt.date(e.date) },
          { key: "category", header: t("common.category") },
          { key: "description", header: t("common.description"), render: (e: any) => e.description ?? "—" },
          { key: "paid_to", header: t("exp.paidTo"), render: (e: any) => e.paid_to ?? "—" },
          { key: "clinic", header: t("common.clinic"), render: (e: any) => <ClinicBadge clinic={e.clinic} /> },
          { key: "receipt", header: t("exp.receipt"), render: (e: any) => (e.has_receipt ? <a className="underline" onClick={(ev) => ev.stopPropagation()} href={`${API}/expenses/${e.id}/receipt`} target="_blank" rel="noopener">{t("common.view")}</a> : "—") },
          { key: "amount", header: t("common.amount"), align: "end", render: (e: any) => fmt.money(e.amount) },
        ]} />
        {data && <Pagination page={page} total={data.total} pageSize={data.page_size} onPage={setPage} />}
      </Card>
      <ExpenseModal expense={edit} onClose={() => setEdit(null)} onSaved={reload} />
    </>
  );
}

function ExpenseModal({ expense, onClose, onSaved }: { expense: any | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { settings, me } = useSession();
  const [v, setV] = useState<any>({});
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (expense) setV(expense.id ? { ...expense } : { clinic: me.clinic_scope === "both" ? "shared" : me.clinic_scope, date: todayISO(), category: settings.expense_categories[0] ?? "", description: "", amount: 0, paid_to: "" });
  }, [expense, me.clinic_scope, settings.expense_categories]);
  if (!expense) return null;
  const set = (k: string, x: unknown) => setV((s: any) => ({ ...s, [k]: x }));
  const save = async () => {
    try {
      const body = { clinic: v.clinic, date: v.date, category: v.category, description: v.description || null, amount: v.amount, paid_to: v.paid_to || null };
      const saved = expense.id ? await api.patch(`/expenses/${expense.id}`, { ...body, version: expense.version }) : await api.post("/expenses", body);
      const f = file.current?.files?.[0];
      if (f) {
        const form = new FormData();
        form.append("file", f);
        await api.post(`/expenses/${saved.id}/receipt`, form);
      }
      onSaved();
      onClose();
    } catch (e) {
      fb.error(e);
    }
  };
  const clinics = me.clinic_scope === "both" ? ["shared", "dental", "derma"] : ["shared", me.clinic_scope];
  return (
    <Modal open onClose={onClose} title={expense.id ? t("common.edit") : t("exp.new")}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={!v.amount || !v.category} onClick={save}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("common.date")} required><Input type="date" value={v.date ?? ""} onChange={(e) => set("date", e.target.value)} /></Field>
        <Field label={t("common.amount")} required><MoneyInput decimals={settings.currency_decimals} value={v.amount} onChange={(x) => set("amount", x)} /></Field>
        <Field label={t("common.category")} required>
          <Select value={v.category ?? ""} onChange={(e) => set("category", e.target.value)}>
            {[...new Set([...settings.expense_categories, v.category].filter(Boolean))].map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label={t("common.clinic")}><Select value={v.clinic} onChange={(e) => set("clinic", e.target.value)}>{clinics.map((c) => <option key={c} value={c}>{t(`clinic.${c}`)}</option>)}</Select></Field>
        <Field label={t("common.description")} className="sm:col-span-2"><Input value={v.description ?? ""} onChange={(e) => set("description", e.target.value)} /></Field>
        <Field label={t("exp.paidTo")}><Input value={v.paid_to ?? ""} onChange={(e) => set("paid_to", e.target.value)} /></Field>
        <Field label={t("exp.receipt")} hint={t("pat.uploadHint")}><input ref={file} type="file" accept="image/*,application/pdf" className="text-sm" /></Field>
      </div>
    </Modal>
  );
}
