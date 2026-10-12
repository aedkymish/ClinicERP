"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Button, Card, DataTable, Empty, Field, Input, Modal, MoneyInput, PageHeader, Select, StatusBadge, Textarea, useFeedback } from "@/components/ui";
import { api, openFile } from "@/lib/api";
import { todayISO, useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function PayrollRunPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const fb = useFeedback();
  const { fmt, can, settings } = useSession();
  const { data: run, reload, setData } = useApi<any>(`/payroll/runs/${id}`);
  const [line, setLine] = useState<any | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const [paidOn, setPaidOn] = useState(todayISO());
  const [method, setMethod] = useState("Bank transfer");
  const commission = useApi<any>(detail ? `/payroll/lines/${detail.id}/commission` : null);
  if (!run) return <Empty>{/* loading */}</Empty>;
  const draft = run.status === "Draft";

  const act = async (fn: () => Promise<any>) => {
    try {
      setData(await fn());
    } catch (e) {
      fb.error(e);
    }
  };
  const approve = async () => {
    if (await fb.confirm({ title: t("payroll.approve"), message: t("payroll.approveConfirm") })) act(() => api.post(`/payroll/runs/${run.id}/approve`));
  };
  const saveLine = async () => {
    try {
      await api.patch(`/payroll/lines/${line.id}`, { bonus: line.bonus, deductions: line.deductions, note: line.note || null });
      setLine(null);
      reload();
    } catch (e) {
      fb.error(e);
    }
  };
  const total = (k: string) => run.lines.reduce((a: number, l: any) => a + l[k], 0);

  return (
    <>
      <PageHeader title={`${t("payroll.title")} · ${run.month}`} subtitle={<StatusBadge status={run.status} prefix="payroll.st." />} actions={<>
        {draft && <Button onClick={() => act(() => api.post("/payroll/runs", { month: run.month }))}>{t("payroll.generate")}</Button>}
        {draft && can("payroll.approve") && <Button variant="primary" onClick={approve}>{t("payroll.approve")}</Button>}
        {run.status === "Approved" && <Button variant="primary" onClick={() => setPayOpen(true)}>{t("payroll.pay")}</Button>}
      </>} />
      <Card padded={false}>
        <DataTable rows={run.lines} onRowClick={draft ? (l: any) => setLine({ ...l }) : undefined} columns={[
          { key: "staff_name", header: t("att.employee"), render: (l: any) => <span className="font-medium">{l.staff_name}</span> },
          { key: "role", header: t("staff.role"), render: (l: any) => t(`role.${l.role}`) },
          { key: "base", header: t("payroll.base"), align: "end", render: (l: any) => fmt.money(l.base) },
          { key: "absence", header: t("payroll.absence"), align: "end", render: (l: any) => (l.absence_deduction ? `−${fmt.money(l.absence_deduction)} (${l.absence_days})` : "—") },
          { key: "commission", header: t("payroll.commission"), align: "end", render: (l: any) => (l.commission ? <button type="button" className="underline" onClick={(e) => { e.stopPropagation(); setDetail(l); }}>{fmt.money(l.commission)}</button> : "—") },
          { key: "bonus", header: t("payroll.bonus"), align: "end", render: (l: any) => (l.bonus ? fmt.money(l.bonus) : "—") },
          { key: "deductions", header: t("payroll.deductions"), align: "end", render: (l: any) => (l.deductions ? `−${fmt.money(l.deductions)}` : "—") },
          { key: "net", header: t("payroll.net"), align: "end", render: (l: any) => <strong>{fmt.money(l.net)}</strong> },
          { key: "slip", header: "", render: (l: any) => <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); openFile(`/payroll/lines/${l.id}/payslip`); }}>{t("payroll.payslip")}</Button> },
        ]} footer={
          <tfoot className="border-t-2 border-slate-300 font-semibold dark:border-slate-600">
            <tr>
              <td className="px-3 py-2" colSpan={2}>{t("common.total")}</td>
              {["base", "absence_deduction", "commission", "bonus", "deductions", "net"].map((k) => <td key={k} className="px-3 py-2 text-end tabular-nums">{fmt.money(total(k))}</td>)}
              <td />
            </tr>
          </tfoot>
        } />
      </Card>
      <div className="mt-4 text-sm"><Link className="text-slate-500 underline" href="/payroll">← {t("payroll.title")}</Link></div>

      <Modal open={Boolean(line)} onClose={() => setLine(null)} title={line?.staff_name ?? ""} size="sm"
        footer={<><Button onClick={() => setLine(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={saveLine}>{t("common.save")}</Button></>}>
        {line && <div className="space-y-3">
          <Field label={t("payroll.bonus")}><MoneyInput decimals={settings.currency_decimals} value={line.bonus} onChange={(v) => setLine({ ...line, bonus: v })} /></Field>
          <Field label={t("payroll.deductions")}><MoneyInput decimals={settings.currency_decimals} value={line.deductions} onChange={(v) => setLine({ ...line, deductions: v })} /></Field>
          <Field label={t("common.notes")}><Textarea value={line.note ?? ""} onChange={(e) => setLine({ ...line, note: e.target.value })} /></Field>
        </div>}
      </Modal>

      <Modal open={payOpen} onClose={() => setPayOpen(false)} title={t("payroll.pay")} size="sm"
        footer={<><Button onClick={() => setPayOpen(false)}>{t("common.cancel")}</Button><Button variant="primary" onClick={() => { setPayOpen(false); act(() => api.post(`/payroll/runs/${run.id}/pay`, { paid_on: paidOn, method })); }}>{t("common.save")}</Button></>}>
        <div className="space-y-3">
          <Field label={t("payroll.paidOn")}><Input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} /></Field>
          <Field label={t("common.method")}><Select value={method} onChange={(e) => setMethod(e.target.value)}>{["Bank transfer", "Cash", "Cheque", "Other"].map((m) => <option key={m}>{m}</option>)}</Select></Field>
        </div>
      </Modal>

      <Modal open={Boolean(detail)} onClose={() => setDetail(null)} title={`${t("payroll.commission")} · ${detail?.staff_name ?? ""}`} size="xl">
        <DataTable rows={commission.data?.lines?.map((l: any, i: number) => ({ ...l, id: i }))} loading={commission.loading} columns={[
          { key: "invoice_number", header: t("inv.number") },
          { key: "description", header: t("common.service") },
          { key: "qty", header: t("common.qty"), align: "end" },
          { key: "unit_price", header: t("common.price"), align: "end", render: (l: any) => fmt.money(l.unit_price) },
          { key: "discount", header: t("inv.discount"), align: "end", render: (l: any) => fmt.money(l.discount) },
          { key: "lab_cost", header: t("inv.lab"), align: "end", render: (l: any) => fmt.money(l.lab_cost) },
          { key: "share_pct", header: t("inv.share"), align: "end" },
          { key: "paid", header: t("rep.paidPct"), align: "end", render: (l: any) => `${(l.paid_fraction * 100).toFixed(1)}%` },
          { key: "commission", header: t("payroll.commission"), align: "end", render: (l: any) => fmt.money(l.commission) },
        ]} />
      </Modal>
    </>
  );
}
