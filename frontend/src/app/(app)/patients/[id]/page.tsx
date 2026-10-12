"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { DentalChart } from "@/components/DentalChart";
import { AppointmentModal, PatientModal, VisitModal } from "@/components/forms";
import { Badge, Button, Card, ClinicBadge, DataTable, Empty, PageHeader, StatusBadge, Tabs, useFeedback } from "@/components/ui";
import { api, API } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="col-span-2 whitespace-pre-wrap">{value || "—"}</dd>
    </div>
  );
}

export default function PatientFile() {
  const { id } = useParams<{ id: string }>();
  const pid = Number(id);
  const { t } = useI18n();
  const fb = useFeedback();
  const router = useRouter();
  const { can, fmt } = useSession();
  const { data: p, reload, error } = useApi<any>(`/patients/${pid}`);
  const [tab, setTab] = useState("overview");
  const [editing, setEditing] = useState(false);
  const [visitModal, setVisitModal] = useState<{ visit?: any } | null>(null);
  const [apptModal, setApptModal] = useState<{ appt?: any } | null>(null);

  const visits = useApi<any>(tab === "notes" && can("visits.read") ? "/visits" : null, { patient_id: pid, page_size: 200 });
  const appts = useApi<any[]>(tab === "appts" && can("appointments.read") ? "/appointments" : null, { patient_id: pid });
  const invoices = useApi<any>(tab === "billing" && can("billing.read") ? "/invoices" : null, { patient_id: pid, page_size: 200 });
  const files = useApi<any[]>(tab === "docs" ? `/patients/${pid}/files` : null);
  const fileInput = useRef<HTMLInputElement>(null);

  if (error) return <Empty>{error.message}</Empty>;
  if (!p) return <Empty>{t("common.loading")}</Empty>;
  const dentalPatient = p.clinic_scope !== "derma";

  const tabs = [
    { id: "overview", label: t("pat.tab.overview") },
    ...(can("visits.read") ? [{ id: "notes", label: t("pat.tab.notes") }] : []),
    ...(can("chart.read") && dentalPatient ? [{ id: "chart", label: t("pat.tab.chart") }] : []),
    ...(can("appointments.read") ? [{ id: "appts", label: t("pat.tab.appts") }] : []),
    ...(can("billing.read") ? [{ id: "billing", label: t("pat.tab.billing") }] : []),
    { id: "docs", label: t("pat.tab.docs") },
  ];

  const archive = async () => {
    const ok = await fb.confirm({ title: p.archived ? t("pat.unarchive") : t("pat.archive"), message: p.archived ? undefined : t("pat.archiveConfirm"), danger: !p.archived });
    if (!ok) return;
    try {
      await api.post(`/patients/${pid}/archive`, undefined, { archived: !p.archived });
      reload();
    } catch (e) {
      fb.error(e);
    }
  };

  const upload = async (file: File) => {
    if (file.size > 10 * 1024 * 1024) return fb.error(new Error(t("pat.uploadHint")));
    const form = new FormData();
    form.append("file", file);
    try {
      await api.post(`/patients/${pid}/files`, form);
      files.reload();
      fb.ok(t("common.saved"));
    } catch (e) {
      fb.error(e);
    }
  };

  return (
    <>
      <PageHeader
        title={p.name}
        subtitle={<span className="flex flex-wrap items-center gap-2"><span className="tabular-nums">{p.file_no}</span>· {p.phone}
          <Badge tone={p.clinic_scope === "dental" ? "blue" : p.clinic_scope === "derma" ? "purple" : "gray"}>{t(`clinic.${p.clinic_scope}`)}</Badge>
          {p.archived && <Badge tone="gray">{t("pat.archived")}</Badge>}</span>}
        actions={<>
          {can("patients.write") && <Button onClick={() => setEditing(true)}>{t("common.edit")}</Button>}
          {can("patients.archive") && <Button variant="ghost" onClick={archive}>{p.archived ? t("pat.unarchive") : t("pat.archive")}</Button>}
        </>}
      />
      {(p.allergies || p.balance > 0) && (
        <div className="mb-4 flex flex-wrap gap-2" role="alert">
          {p.allergies && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100"><strong>⚠ {t("pat.allergyAlert")}:</strong> {p.allergies}</div>}
          {p.balance > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100"><strong>{t("pat.balance")}:</strong> {fmt.money(p.balance)}</div>}
        </div>
      )}
      <Tabs tabs={tabs} active={tab} onChange={setTab} />

      {tab === "overview" && (
        <Card>
          <dl className="grid gap-x-8 md:grid-cols-2">
            <Row label={t("pat.dob")} value={p.dob && fmt.date(p.dob)} />
            <Row label={t("pat.gender")} value={p.gender && t(`pat.${p.gender}`)} />
            <Row label={t("common.email")} value={p.email} />
            <Row label={t("pat.address")} value={p.address} />
            <Row label={t("pat.insurance")} value={p.insurance} />
            <Row label={t("pat.allergies")} value={p.allergies} />
            <Row label={t("pat.history")} value={p.history} />
            <Row label={t("common.notes")} value={p.notes} />
          </dl>
        </Card>
      )}

      {tab === "notes" && (
        <Card padded={false} title={t("pat.tab.notes")} actions={can("visits.write") && <Button size="sm" variant="primary" onClick={() => setVisitModal({})}>+ {t("visit.new")}</Button>}>
          <DataTable rows={visits.data?.items} loading={visits.loading} onRowClick={(v: any) => setVisitModal({ visit: v })} columns={[
            { key: "date", header: t("common.date"), render: (v: any) => fmt.date(v.date) },
            { key: "clinic", header: t("common.clinic"), render: (v: any) => <ClinicBadge clinic={v.clinic} /> },
            { key: "doctor_name", header: t("common.doctor"), render: (v: any) => v.doctor_name ?? "—" },
            { key: "diagnosis", header: t("visit.diagnosis"), render: (v: any) => v.diagnosis ?? "—" },
            { key: "lock", header: "", render: (v: any) => (v.locked ? <Badge>{t("visit.locked")}</Badge> : null) },
          ]} />
        </Card>
      )}

      {tab === "chart" && <DentalChart patientId={pid} />}

      {tab === "appts" && (
        <Card padded={false} title={t("pat.tab.appts")} actions={can("appointments.write") && <Button size="sm" variant="primary" onClick={() => setApptModal({})}>+ {t("appt.new")}</Button>}>
          <DataTable rows={appts.data} loading={appts.loading} onRowClick={(a: any) => setApptModal({ appt: a })} columns={[
            { key: "date", header: t("common.date"), render: (a: any) => `${fmt.date(a.date)} ${a.time}` },
            { key: "clinic", header: t("common.clinic"), render: (a: any) => <ClinicBadge clinic={a.clinic} /> },
            { key: "service_name", header: t("common.service"), render: (a: any) => a.service_name ?? "—" },
            { key: "doctor_name", header: t("common.doctor"), render: (a: any) => a.doctor_name ?? "—" },
            { key: "status", header: t("common.status"), render: (a: any) => <StatusBadge status={a.status} prefix="st." /> },
          ]} />
        </Card>
      )}

      {tab === "billing" && (
        <Card padded={false} title={t("pat.tab.billing")} actions={can("billing.create") && <Button size="sm" variant="primary" onClick={() => router.push(`/billing/new?patient=${pid}`)}>+ {t("inv.new")}</Button>}>
          <DataTable rows={invoices.data?.items} loading={invoices.loading} onRowClick={(i: any) => router.push(`/billing/${i.id}`)} columns={[
            { key: "number", header: t("inv.number"), className: "tabular-nums" },
            { key: "date", header: t("common.date"), render: (i: any) => fmt.date(i.date) },
            { key: "status", header: t("common.status"), render: (i: any) => <StatusBadge status={i.status} prefix="inv.status." /> },
            { key: "payment_status", header: "", render: (i: any) => <StatusBadge status={i.payment_status} prefix="pay." /> },
            { key: "total", header: t("common.total"), align: "end", render: (i: any) => fmt.money(i.total) },
            { key: "balance", header: t("inv.balance"), align: "end", render: (i: any) => fmt.money(i.balance) },
          ]} />
        </Card>
      )}

      {tab === "docs" && (
        <Card title={t("pat.tab.docs")} actions={can("patients.write") && (
          <>
            <input ref={fileInput} type="file" accept="image/*,application/pdf" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            <Button size="sm" variant="primary" onClick={() => fileInput.current?.click()}>{t("common.upload")}</Button>
          </>
        )}>
          <p className="mb-3 text-xs text-slate-500">{t("pat.uploadHint")}</p>
          {files.data?.length ? (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {files.data.map((f) => (
                <li key={f.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <a className="font-medium text-brand-700 underline dark:text-brand-100" href={`${API}/patients/${pid}/files/${f.id}`} target="_blank" rel="noopener">{f.filename}</a>
                  <span className="text-xs text-slate-500">{(f.size / 1024).toFixed(0)} KB · {fmt.dateTime(f.created_at + "Z")}</span>
                </li>
              ))}
            </ul>
          ) : <Empty />}
        </Card>
      )}

      <PatientModal open={editing} onClose={() => setEditing(false)} patient={p} onSaved={() => reload()} />
      <VisitModal open={Boolean(visitModal)} onClose={() => setVisitModal(null)} visit={visitModal?.visit}
        preset={{ patient: p }} onSaved={(v) => { visits.reload(); if (visitModal?.visit) setVisitModal({ visit: v }); }} />
      <AppointmentModal open={Boolean(apptModal)} onClose={() => setApptModal(null)} appt={apptModal?.appt}
        preset={{ patient: p }} onSaved={() => appts.reload()} />
      <div className="mt-6 text-sm"><Link className="text-slate-500 underline" href="/patients">← {t("pat.title")}</Link></div>
    </>
  );
}
