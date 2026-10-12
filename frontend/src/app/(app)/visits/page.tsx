"use client";
import Link from "next/link";
import { useState } from "react";
import { useLookups, VisitModal } from "@/components/forms";
import { Badge, Button, Card, ClinicBadge, DataTable, Field, Input, PageHeader, Pagination, Select } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function VisitsPage() {
  const { t } = useI18n();
  const { clinicParam, can, fmt } = useSession();
  const lookups = useLookups();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [doctor, setDoctor] = useState("");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ visit?: any } | null>(null);
  const { data, loading, reload } = useApi<any>("/visits", { clinic: clinicParam, from, to, doctor, page });

  return (
    <>
      <PageHeader title={t("visit.title")} actions={can("visits.write") && <Button variant="primary" onClick={() => setModal({})}>+ {t("visit.new")}</Button>} />
      <Card padded={false}>
        <div className="grid grid-cols-2 gap-3 border-b border-slate-200 p-3 dark:border-slate-700 sm:grid-cols-4">
          <Field label={t("common.from")}><Input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} /></Field>
          <Field label={t("common.to")}><Input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} /></Field>
          <Field label={t("common.doctor")}>
            <Select value={doctor} onChange={(e) => { setDoctor(e.target.value); setPage(1); }}>
              <option value="">{t("common.all")}</option>{lookups.doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </Field>
        </div>
        <DataTable rows={data?.items} loading={loading} onRowClick={(v: any) => setModal({ visit: v })} columns={[
          { key: "date", header: t("common.date"), render: (v: any) => fmt.date(v.date) },
          { key: "patient_name", header: t("common.patient"), render: (v: any) => <Link className="font-medium hover:underline" href={`/patients/${v.patient_id}`} onClick={(e) => e.stopPropagation()}>{v.patient_name}</Link> },
          { key: "clinic", header: t("common.clinic"), render: (v: any) => <ClinicBadge clinic={v.clinic} /> },
          { key: "doctor_name", header: t("common.doctor"), render: (v: any) => v.doctor_name ?? "—" },
          { key: "diagnosis", header: t("visit.diagnosis"), render: (v: any) => v.diagnosis ?? "—" },
          { key: "follow_up", header: t("visit.followUp"), render: (v: any) => (v.follow_up ? fmt.date(v.follow_up) : "—") },
          { key: "locked", header: "", render: (v: any) => (v.locked ? <Badge>{t("visit.locked")}</Badge> : null) },
        ]} />
        {data && <Pagination page={page} total={data.total} pageSize={data.page_size} onPage={setPage} />}
      </Card>
      <VisitModal open={Boolean(modal)} onClose={() => setModal(null)} visit={modal?.visit}
        onSaved={(v) => { reload(); if (modal?.visit) setModal({ visit: v }); }} />
    </>
  );
}
