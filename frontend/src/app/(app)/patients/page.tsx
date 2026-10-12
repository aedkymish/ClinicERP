"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PatientModal } from "@/components/forms";
import { Badge, Button, Card, Checkbox, DataTable, ExportButtons, Input, PageHeader, Pagination } from "@/components/ui";
import { openFile } from "@/lib/api";
import { useApi, useDebounced } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function PatientsPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { clinicParam, can, fmt } = useSession();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const dq = useDebounced(q);
  const params = { q: dq, page, clinic: clinicParam, archived: archived || undefined };
  const { data, loading } = useApi<any>("/patients", params);

  return (
    <>
      <PageHeader title={t("pat.title")} actions={can("patients.write") && <Button variant="primary" onClick={() => setCreating(true)}>+ {t("pat.new")}</Button>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-3 dark:border-slate-700">
          <Input className="max-w-xs" type="search" placeholder={t("common.search")} value={q} aria-label={t("common.search")}
            onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          {can("patients.archive") && <Checkbox label={t("pat.showArchived")} checked={archived} onChange={(v) => { setArchived(v); setPage(1); }} />}
          <div className="ms-auto"><ExportButtons onExport={(f) => openFile("/patients", { ...params, page: undefined, format: f })} /></div>
        </div>
        <DataTable rows={data?.items} loading={loading} onRowClick={(p: any) => router.push(`/patients/${p.id}`)} columns={[
          { key: "file_no", header: t("pat.fileNo"), className: "tabular-nums whitespace-nowrap" },
          { key: "name", header: t("common.name"), render: (p: any) => (
            <span className="font-medium">{p.name}{p.allergies && <span className="ms-2"><Badge tone="red">{t("pat.allergyAlert")}</Badge></span>}</span>) },
          { key: "phone", header: t("common.phone"), className: "whitespace-nowrap" },
          { key: "dob", header: t("pat.dob"), render: (p: any) => (p.dob ? fmt.date(p.dob) : "—") },
          { key: "clinic_scope", header: t("pat.scope"), render: (p: any) => <Badge tone={p.clinic_scope === "dental" ? "blue" : p.clinic_scope === "derma" ? "purple" : "gray"}>{t(`clinic.${p.clinic_scope}`)}</Badge> },
        ]} />
        {data && <Pagination page={page} total={data.total} pageSize={data.page_size} onPage={setPage} />}
      </Card>
      <PatientModal open={creating} onClose={() => setCreating(false)} onSaved={(p) => router.push(`/patients/${p.id}`)} />
    </>
  );
}
