"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Card, Checkbox, DataTable, ExportButtons, Field, Input, Modal, MoneyInput, PageHeader, Select, useFeedback } from "@/components/ui";
import { api, openFile } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const ROLES = ["doctor", "nurse", "assistant", "receptionist", "finance", "admin"];

export default function StaffPage() {
  const { t } = useI18n();
  const { clinicParam, can, fmt } = useSession();
  const [showInactive, setShowInactive] = useState(false);
  const [edit, setEdit] = useState<any | null>(null);
  const { data, loading, reload } = useApi<any[]>("/staff", { clinic: clinicParam, active: showInactive ? undefined : true });

  return (
    <>
      <PageHeader title={t("staff.title")} actions={can("staff.write") && <Button variant="primary" onClick={() => setEdit({})}>+ {t("staff.new")}</Button>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-3 dark:border-slate-700">
          <Checkbox label={t("common.inactive")} checked={showInactive} onChange={setShowInactive} />
          <div className="ms-auto"><ExportButtons onExport={(f) => openFile("/staff", { clinic: clinicParam, format: f })} /></div>
        </div>
        <DataTable rows={data} loading={loading} onRowClick={setEdit} columns={[
          { key: "name", header: t("common.name"), render: (s: any) => <span className="font-medium">{s.name}{!s.active && <> <Badge>{t("common.inactive")}</Badge></>}</span> },
          { key: "role", header: t("staff.role"), render: (s: any) => t(`role.${s.role}`) },
          { key: "clinic_scope", header: t("common.clinic"), render: (s: any) => t(`clinic.${s.clinic_scope}`) },
          { key: "specialty", header: t("staff.specialty"), render: (s: any) => s.specialty ?? "—" },
          { key: "phone", header: t("common.phone"), render: (s: any) => s.phone ?? "—" },
          { key: "salary", header: t("staff.salary"), align: "end", render: (s: any) => fmt.money(s.salary) },
          { key: "share", header: t("staff.share"), align: "end", render: (s: any) => (s.role === "doctor" ? `${s.default_share_pct}%` : "—") },
          { key: "username", header: t("staff.login"), render: (s: any) => s.username ?? "—" },
        ]} />
      </Card>
      <StaffModal staff={edit} onClose={() => setEdit(null)} onSaved={reload} />
    </>
  );
}

function StaffModal({ staff, onClose, onSaved }: { staff: any | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { can, settings, me } = useSession();
  const admin = can("staff.write");
  const [v, setV] = useState<any>({});
  useEffect(() => {
    if (staff) setV(staff.id ? { ...staff } : { name: "", role: "doctor", clinic_scope: me.clinic_scope, specialty: "", phone: "", email: "", hire_date: "", salary: 0, default_share_pct: 0 });
  }, [staff, me.clinic_scope]);
  if (!staff) return null;
  const set = (k: string, x: unknown) => setV((s: any) => ({ ...s, [k]: x }));
  const save = async () => {
    try {
      const pay = { salary: v.salary, default_share_pct: Number(v.default_share_pct) };
      const body = admin
        ? { name: v.name, role: v.role, clinic_scope: v.clinic_scope, specialty: v.specialty || null, phone: v.phone || null, email: v.email || null, hire_date: v.hire_date || null, ...pay, ...(staff.id ? { active: v.active } : {}) }
        : pay;
      if (staff.id) await api.patch(`/staff/${staff.id}`, { ...body, version: staff.version });
      else await api.post("/staff", body);
      onSaved();
      onClose();
    } catch (e) {
      fb.error(e);
    }
  };
  const d = { disabled: !admin };
  return (
    <Modal open onClose={onClose} title={staff.id ? staff.name : t("staff.new")} size="lg"
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>{can("staff.write", "staff.salary") && <Button variant="primary" onClick={save}>{t("common.save")}</Button>}</>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("common.name")} required><Input value={v.name ?? ""} onChange={(e) => set("name", e.target.value)} {...d} /></Field>
        <Field label={t("staff.role")}><Select value={v.role} onChange={(e) => set("role", e.target.value)} {...d}>{ROLES.map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}</Select></Field>
        <Field label={t("common.clinic")}><Select value={v.clinic_scope} onChange={(e) => set("clinic_scope", e.target.value)} {...d}>{["both", "dental", "derma"].map((c) => <option key={c} value={c}>{c === "both" ? t("clinic.both") : settings.clinics[c as "dental"].name}</option>)}</Select></Field>
        <Field label={t("staff.specialty")}><Input value={v.specialty ?? ""} onChange={(e) => set("specialty", e.target.value)} {...d} /></Field>
        <Field label={t("common.phone")}><Input value={v.phone ?? ""} onChange={(e) => set("phone", e.target.value)} {...d} /></Field>
        <Field label={t("common.email")}><Input type="email" value={v.email ?? ""} onChange={(e) => set("email", e.target.value)} {...d} /></Field>
        <Field label={t("staff.hireDate")}><Input type="date" value={v.hire_date ?? ""} onChange={(e) => set("hire_date", e.target.value)} {...d} /></Field>
        <Field label={t("staff.salary")}><MoneyInput decimals={settings.currency_decimals} value={v.salary} onChange={(x) => set("salary", x)} disabled={!can("staff.salary")} /></Field>
        <Field label={t("staff.share")}><Input type="number" min={0} max={100} step="any" value={v.default_share_pct ?? 0} onChange={(e) => set("default_share_pct", e.target.value)} disabled={!can("staff.salary")} /></Field>
        {staff.id && admin && <div className="flex items-end pb-2"><Checkbox label={t("common.active")} checked={Boolean(v.active)} onChange={(x) => set("active", x)} /></div>}
      </div>
    </Modal>
  );
}
