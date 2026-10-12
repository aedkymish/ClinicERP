"use client";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { PatientPicker, useLookups, useServices } from "@/components/forms";
import {
  Badge, Button, Card, Checkbox, ClinicBadge, DataTable, Empty, Field, Input, Modal, MoneyInput, PageHeader, Select, StatusBadge, Textarea, useFeedback,
} from "@/components/ui";
import { api, ApiError, openFile } from "@/lib/api";
import { todayISO } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const METHODS = ["Cash", "Card", "Bank transfer", "Cheque", "Other"];

interface Line { service_id: number | null; description: string; qty: number; unit_price: number; share_pct: number | null; lab_cost: number | null; vat_applies: boolean; touched?: boolean }

function Editor() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const isNew = id === "new";
  const router = useRouter();
  const { t } = useI18n();
  const fb = useFeedback();
  const { can, fmt, settings, me, view } = useSession();
  const lookups = useLookups();
  const [inv, setInv] = useState<any | null>(null);
  const [patient, setPatient] = useState<any | null>(null);
  const [clinic, setClinic] = useState<string>(me.clinic_scope !== "both" ? me.clinic_scope : view !== "both" ? view : "dental");
  const [doctorId, setDoctorId] = useState("");
  const [date, setDate] = useState(todayISO());
  const [discountType, setDiscountType] = useState("amount");
  const [discountValue, setDiscountValue] = useState(0);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [appointmentId, setAppointmentId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [payOpen, setPayOpen] = useState(false);
  const [creditOpen, setCreditOpen] = useState(false);
  const services = useServices(clinic);
  const override = can("billing.override");
  const decimals = settings.currency_decimals;

  const loadInvoice = (data: any) => {
    setInv(data);
    setPatient({ id: data.patient_id, name: data.patient_name, file_no: data.patient_file_no });
    setClinic(data.clinic);
    setDoctorId(data.doctor_id ? String(data.doctor_id) : "");
    setDate(data.date);
    setDiscountType(data.discount_type);
    setDiscountValue(data.discount_value);
    setNotes(data.notes ?? "");
    setLines(data.lines.map((l: any) => ({ ...l })));
  };

  useEffect(() => {
    if (!isNew) {
      api.get(`/invoices/${id}`).then(loadInvoice).catch((e) => fb.error(e));
      return;
    }
    const pid = search.get("patient");
    const appt = search.get("appointment");
    if (pid) api.get(`/patients/${pid}`).then(setPatient).catch(() => {});
    if (appt) {
      api.get("/billing/prefill", { appointment_id: appt }).then(async (p) => {
        setAppointmentId(p.appointment_id);
        setClinic(p.clinic);
        setDoctorId(p.doctor_id ? String(p.doctor_id) : "");
        setPatient(await api.get(`/patients/${p.patient_id}`));
        setLines(p.lines.map((l: any) => ({ service_id: l.service_id, description: "", qty: 1, unit_price: 0, share_pct: null, lab_cost: null, vat_applies: false })));
      }).catch((e) => fb.error(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // fill service values for lines that were pre-filled by id only
  useEffect(() => {
    if (!services.length) return;
    setLines((ls) => ls.map((l) => {
      if (!l.service_id || l.description) return l;
      const s = services.find((x) => x.id === l.service_id);
      return s ? { ...l, description: s.name, unit_price: s.price, share_pct: s.share_pct, lab_cost: s.lab_cost, vat_applies: s.vat_applies } : l;
    }));
  }, [services]);

  const draft = isNew || inv?.status === "Draft";
  const editable = draft && can("billing.create");

  const preview = useMemo(() => {
    const gross = lines.map((l) => Math.round(l.qty * l.unit_price));
    const subtotal = gross.reduce((a, b) => a + b, 0);
    const discount = discountType === "percent" ? Math.round((subtotal * Math.min(100, discountValue)) / 100) : Math.min(discountValue, subtotal);
    const rate = settings.vat_enabled ? settings.vat_rate : 0;
    const vat = lines.reduce((acc, l, i) => acc + (l.vat_applies && subtotal ? Math.round(((gross[i] - (discount * gross[i]) / subtotal) * rate) / 100) : 0), 0);
    return { subtotal, discount, vat, total: subtotal - discount + vat };
  }, [lines, discountType, discountValue, settings]);
  const shown = draft ? preview : inv;

  const setLine = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch, touched: true } : l)));
  const pickService = (i: number, sid: string) => {
    const s = services.find((x) => String(x.id) === sid);
    if (s) setLine(i, { service_id: s.id, description: s.name, unit_price: s.price, share_pct: s.share_pct, lab_cost: s.lab_cost, vat_applies: s.vat_applies });
    else setLine(i, { service_id: null });
  };

  const body = () => ({
    doctor_id: doctorId ? Number(doctorId) : null, date, discount_type: discountType, discount_value: discountValue, notes: notes || null,
    lines: lines.map((l) => ({
      service_id: l.service_id, description: l.description || null, qty: l.qty,
      unit_price: l.service_id && !override && !services.find((s) => s.id === l.service_id && s.price === 0) ? null : l.unit_price,
      ...(override ? { share_pct: l.share_pct, lab_cost: l.lab_cost, vat_applies: l.vat_applies } : l.service_id ? {} : { vat_applies: l.vat_applies }),
    })),
  });

  const save = async (): Promise<any | null> => {
    if (!patient) {
      fb.error(new Error(`${t("common.patient")}: ${t("common.required")}`));
      return null;
    }
    setBusy(true);
    try {
      const saved = isNew
        ? await api.post("/invoices", { ...body(), patient_id: patient.id, clinic, appointment_id: appointmentId })
        : await api.patch(`/invoices/${inv.id}`, { ...body(), patient_id: patient.id, version: inv.version });
      fb.ok(t("common.saved"));
      if (isNew) router.replace(`/billing/${saved.id}`);
      else loadInvoice(saved);
      return saved;
    } catch (e) {
      fb.error(e);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const action = async (fn: () => Promise<any>) => {
    try {
      const res = await fn();
      if (res?.id) loadInvoice(res);
    } catch (e) {
      fb.error(e);
    }
  };

  const post = async () => {
    if (!(await fb.confirm({ title: t("inv.post"), message: t("inv.postConfirm") }))) return;
    action(() => api.post(`/invoices/${inv.id}/post`));
  };
  const voidIt = async () => {
    const reason = await fb.confirm({ title: t("inv.void"), danger: true, input: { label: t("inv.voidReason"), minLength: 3 } });
    if (reason) action(() => api.post(`/invoices/${inv.id}/void`, { reason }));
  };
  const refund = async (p: any) => {
    const reason = await fb.confirm({ title: `${t("inv.refund")} · ${fmt.money(p.refundable)}`, danger: true, input: { label: t("common.reason"), minLength: 3 } });
    if (reason) action(() => api.post(`/payments/${p.id}/refund`, { reason }));
  };

  if (!isNew && !inv) return <Empty>{t("common.loading")}</Empty>;

  return (
    <>
      <PageHeader
        title={isNew ? t("inv.new") : inv.number}
        subtitle={inv && <span className="flex flex-wrap items-center gap-2"><ClinicBadge clinic={inv.clinic} /><StatusBadge status={inv.status} prefix="inv.status." />{inv.status !== "Void" && <StatusBadge status={inv.payment_status} prefix="pay." />}</span>}
        actions={<>
          {editable && <Button variant="primary" loading={busy} onClick={save}>{t("inv.saveDraft")}</Button>}
          {inv && draft && can("billing.create") && <Button onClick={post}>{t("inv.post")}</Button>}
          {inv && inv.status !== "Void" && can("billing.pay") && inv.balance > 0 && <Button variant="primary" onClick={() => setPayOpen(true)}>{t("inv.payment")}</Button>}
          {inv && (
            <Select className="!w-auto" value="" aria-label={t("common.print")} onChange={(e) => {
              const [kind, paper] = e.target.value.split(":");
              if (kind) openFile(`/invoices/${inv.id}/pdf`, { kind, paper });
              if (draft) setTimeout(() => api.get(`/invoices/${inv.id}`).then(loadInvoice), 1500);
            }}>
              <option value="">{t("common.print")}…</option>
              <option value="invoice:a4">{t("inv.printInvoice")} · {t("inv.a4")}</option>
              <option value="invoice:thermal">{t("inv.printInvoice")} · {t("inv.thermal")}</option>
              <option value="receipt:a4">{t("inv.receipt")} · {t("inv.a4")}</option>
              <option value="receipt:thermal">{t("inv.receipt")} · {t("inv.thermal")}</option>
            </Select>
          )}
          {inv?.status === "Posted" && can("billing.void") && <Button onClick={() => setCreditOpen(true)}>{t("inv.creditNote")}</Button>}
          {inv && inv.status !== "Void" && can("billing.void") && <Button variant="danger" onClick={voidIt}>{t("inv.void")}</Button>}
        </>}
      />
      {inv?.status === "Posted" && <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">{t("inv.lockedText")}</p>}
      {inv?.status === "Void" && <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-900 dark:bg-red-950 dark:text-red-100">{t("inv.status.Void")}: {inv.void_reason}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              {editable ? <PatientPicker value={patient} onChange={setPatient} /> : (
                <Field label={t("common.patient")}><div className="py-2 text-sm"><Link className="font-medium underline" href={`/patients/${inv.patient_id}`}>{inv.patient_name}</Link> <span className="text-slate-500">{inv.patient_file_no}</span></div></Field>
              )}
            </div>
            {isNew && me.clinic_scope === "both" && (
              <Field label={t("common.clinic")} required>
                <Select value={clinic} onChange={(e) => { setClinic(e.target.value); setLines([]); }}>
                  <option value="dental">{settings.clinics.dental.name}</option><option value="derma">{settings.clinics.derma.name}</option>
                </Select>
              </Field>
            )}
            <Field label={t("common.doctor")}>
              <Select value={doctorId} disabled={!editable} onChange={(e) => setDoctorId(e.target.value)}>
                <option value="">—</option>{lookups.doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
            </Field>
            <Field label={t("common.date")}><Input type="date" value={date} disabled={!editable} onChange={(e) => setDate(e.target.value)} /></Field>
          </div>

          <h3 className="mb-2 mt-5 text-sm font-semibold">{t("inv.lines")}</h3>
          <div className="space-y-2">
            {lines.map((l, i) => (
              <div key={i} className="grid grid-cols-12 items-end gap-2 rounded-md border border-slate-200 p-2 dark:border-slate-700">
                <Field label={t("common.service")} className="col-span-12 sm:col-span-5">
                  {l.service_id || !editable ? (
                    <Select value={l.service_id ?? ""} disabled={!editable} onChange={(e) => pickService(i, e.target.value)}>
                      <option value="">{t("inv.freeLine")}</option>
                      {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                      {l.service_id && !services.some((s) => s.id === l.service_id) && <option value={l.service_id}>{l.description}</option>}
                    </Select>
                  ) : (
                    <Input value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} placeholder={t("common.description")} />
                  )}
                </Field>
                <Field label={t("common.qty")} className="col-span-3 sm:col-span-2">
                  <Input type="number" min={0.01} step="any" value={l.qty} disabled={!editable} onChange={(e) => setLine(i, { qty: Number(e.target.value) })} />
                </Field>
                <Field label={t("common.price")} className="col-span-5 sm:col-span-3">
                  <MoneyInput decimals={decimals} value={l.unit_price} onChange={(v) => setLine(i, { unit_price: v })}
                    disabled={!editable || (Boolean(l.service_id) && !override && !services.some((s) => s.id === l.service_id && s.price === 0))} />
                </Field>
                <div className="col-span-4 pb-2 text-end text-sm tabular-nums sm:col-span-2">{fmt.money(Math.round(l.qty * l.unit_price))}</div>
                {(override || !l.service_id) && (
                  <div className="col-span-12 flex flex-wrap items-end gap-3">
                    {override && <>
                      <Field label={t("inv.share")} className="w-32"><Input type="number" min={0} max={100} step="any" disabled={!editable} value={l.share_pct ?? ""} onChange={(e) => setLine(i, { share_pct: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
                      <Field label={t("inv.lab")} className="w-40"><MoneyInput decimals={decimals} disabled={!editable} value={l.lab_cost ?? 0} onChange={(v) => setLine(i, { lab_cost: v })} /></Field>
                    </>}
                    {settings.vat_enabled && <Checkbox label={t("inv.vatApplies")} disabled={!editable} checked={l.vat_applies} onChange={(v) => setLine(i, { vat_applies: v })} />}
                    {editable && <Button size="sm" variant="ghost" className="ms-auto" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>✕</Button>}
                  </div>
                )}
                {!override && l.service_id && editable && (
                  <div className="col-span-12 text-end"><Button size="sm" variant="ghost" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>✕</Button></div>
                )}
              </div>
            ))}
            {editable && (
              <div className="flex gap-2">
                <Button size="sm" onClick={() => setLines((ls) => [...ls, { service_id: services[0]?.id ?? null, description: services[0]?.name ?? "", qty: 1, unit_price: services[0]?.price ?? 0, share_pct: services[0]?.share_pct ?? null, lab_cost: services[0]?.lab_cost ?? 0, vat_applies: services[0]?.vat_applies ?? false }])}>+ {t("inv.addLine")}</Button>
                <Button size="sm" variant="ghost" onClick={() => setLines((ls) => [...ls, { service_id: null, description: "", qty: 1, unit_price: 0, share_pct: null, lab_cost: 0, vat_applies: false }])}>+ {t("inv.freeLine")}</Button>
              </div>
            )}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Field label={t("inv.discount")}>
              <div className="flex gap-2">
                <Select className="!w-24" value={discountType} disabled={!editable} onChange={(e) => setDiscountType(e.target.value)}>
                  <option value="amount">{t("inv.discountAmount")}</option><option value="percent">{t("inv.discountPercent")}</option>
                </Select>
                {discountType === "percent"
                  ? <Input type="number" min={0} max={100} step="any" disabled={!editable} value={discountValue} onChange={(e) => setDiscountValue(Number(e.target.value))} />
                  : <MoneyInput decimals={decimals} disabled={!editable} value={discountValue} onChange={setDiscountValue} />}
              </div>
            </Field>
            <Field label={t("common.notes")}><Textarea rows={2} disabled={!editable} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <dl className="space-y-1.5 text-sm tabular-nums">
              {[["inv.subtotal", shown.subtotal], ...(shown.discount ? [["inv.discount", -shown.discount]] : []), ...(shown.vat ? [["inv.vat", shown.vat]] : [])].map(([k, v]) => (
                <div key={k as string} className="flex justify-between"><dt className="text-slate-500">{t(k as string)}</dt><dd>{fmt.money(v as number)}</dd></div>
              ))}
              <div className="flex justify-between border-t border-slate-200 pt-1.5 text-base font-semibold dark:border-slate-700"><dt>{t("common.total")}</dt><dd>{fmt.money(shown.total)}</dd></div>
              {inv && <>
                {inv.credited > 0 && <div className="flex justify-between"><dt className="text-slate-500">{t("inv.credited")}</dt><dd>{fmt.money(-inv.credited)}</dd></div>}
                <div className="flex justify-between"><dt className="text-slate-500">{t("inv.paid")}</dt><dd>{fmt.money(-inv.paid)}</dd></div>
                {inv.refunded > 0 && <div className="flex justify-between"><dt className="text-slate-500">{t("inv.refunded")}</dt><dd>{fmt.money(inv.refunded)}</dd></div>}
                <div className="flex justify-between border-t border-slate-200 pt-1.5 text-base font-semibold dark:border-slate-700"><dt>{t("inv.balance")}</dt><dd className={inv.balance > 0 ? "text-red-700 dark:text-red-400" : ""}>{fmt.money(inv.balance)}</dd></div>
              </>}
            </dl>
          </Card>
          {inv && (
            <Card title={t("inv.payments")} padded={false}>
              <DataTable rows={inv.payments} columns={[
                { key: "date", header: t("common.date"), render: (p: any) => fmt.date(p.date) },
                { key: "method", header: t("common.method"), render: (p: any) => <span>{p.method}{p.kind === "Refund" && <> <Badge tone="red">{t("inv.refund")}</Badge></>}</span> },
                { key: "amount", header: t("common.amount"), align: "end", render: (p: any) => fmt.money(p.kind === "Refund" ? -p.amount : p.amount) },
                { key: "act", header: "", render: (p: any) => (p.kind === "Payment" && p.refundable > 0 && can("billing.void") ? <Button size="sm" variant="ghost" onClick={() => refund(p)}>{t("inv.refund")}</Button> : null) },
              ]} />
              {inv.credit_notes.length > 0 && (
                <ul className="border-t border-slate-200 p-3 text-sm dark:border-slate-700">
                  {inv.credit_notes.map((c: any) => (
                    <li key={c.id} className="flex justify-between gap-2">
                      <button type="button" className="underline" onClick={() => openFile(`/invoices/${inv.id}/pdf`, { credit_note_id: c.id })}>{c.number}</button>
                      <span className="truncate text-slate-500">{c.reason}</span><span className="tabular-nums">{fmt.money(-c.amount)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </div>
      </div>

      {inv && <PaymentModal open={payOpen} onClose={() => setPayOpen(false)} inv={inv} onDone={loadInvoice} />}
      {inv && <CreditModal open={creditOpen} onClose={() => setCreditOpen(false)} inv={inv} onDone={loadInvoice} />}
    </>
  );
}

function PaymentModal({ open, onClose, inv, onDone }: { open: boolean; onClose: () => void; inv: any; onDone: (i: any) => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { settings, fmt } = useSession();
  const [amount, setAmount] = useState(inv.balance);
  const [method, setMethod] = useState("Cash");
  const [date, setDate] = useState(todayISO());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { if (open) { setAmount(inv.balance); setErr(""); } }, [open, inv.balance]);
  const submit = async () => {
    setBusy(true);
    try {
      onDone(await api.post(`/invoices/${inv.id}/payments`, { amount, method, date }));
      fb.ok(t("common.saved"));
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={`${t("inv.payment")} · ${inv.number}`} size="sm"
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" loading={busy} disabled={amount <= 0} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("inv.balance")}: <strong>{fmt.money(inv.balance)}</strong></p>
        <Field label={t("common.amount")} required error={err}><MoneyInput decimals={settings.currency_decimals} value={amount} onChange={setAmount} /></Field>
        <Field label={t("common.method")}><Select value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map((m) => <option key={m}>{m}</option>)}</Select></Field>
        <Field label={t("common.date")}><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        {inv.status === "Draft" && <p className="text-xs text-slate-500">{t("inv.postConfirm")}</p>}
      </div>
    </Modal>
  );
}

function CreditModal({ open, onClose, inv, onDone }: { open: boolean; onClose: () => void; inv: any; onDone: (i: any) => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { settings } = useSession();
  const [amount, setAmount] = useState(0);
  const [reason, setReason] = useState("");
  const submit = async () => {
    try {
      onDone(await api.post(`/invoices/${inv.id}/credit-notes`, { amount, reason }));
      onClose();
    } catch (e) {
      fb.error(e);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={t("inv.creditNote")} size="sm"
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={amount <= 0 || reason.trim().length < 3} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("common.amount")} required><MoneyInput decimals={settings.currency_decimals} value={amount} onChange={setAmount} /></Field>
        <Field label={t("common.reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

export default function InvoicePage() {
  return <Suspense><Editor /></Suspense>;
}
