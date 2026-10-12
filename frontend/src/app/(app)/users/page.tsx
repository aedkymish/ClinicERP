"use client";
import { useEffect, useState } from "react";
import { useLookups } from "@/components/forms";
import { Badge, Button, Card, Checkbox, DataTable, Field, Input, Modal, PageHeader, Select, useFeedback } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const ROLES = ["admin", "doctor", "nurse", "assistant", "receptionist", "finance"];

export default function UsersPage() {
  const { t } = useI18n();
  const fb = useFeedback();
  const { fmt } = useSession();
  const { data, loading, reload } = useApi<any[]>("/users");
  const [edit, setEdit] = useState<any | null>(null);
  const [otp, setOtp] = useState<{ user: string; password: string } | null>(null);

  const reset = async (u: any) => {
    if (!(await fb.confirm({ title: t("users.reset"), message: u.username }))) return;
    try {
      const r = await api.post(`/users/${u.id}/reset-password`);
      setOtp({ user: r.username, password: r.one_time_password });
      reload();
    } catch (e) {
      fb.error(e);
    }
  };
  const unlock = async (u: any) => {
    try {
      await api.post(`/users/${u.id}/unlock`);
      reload();
    } catch (e) {
      fb.error(e);
    }
  };

  return (
    <>
      <PageHeader title={t("users.title")} actions={<Button variant="primary" onClick={() => setEdit({})}>+ {t("users.new")}</Button>} />
      <Card padded={false}>
        <DataTable rows={data} loading={loading} columns={[
          { key: "username", header: t("auth.username"), render: (u: any) => <span className="font-medium">{u.username}</span> },
          { key: "staff_name", header: t("users.staff"), render: (u: any) => u.staff_name ?? "—" },
          { key: "role", header: t("staff.role"), render: (u: any) => t(`role.${u.role}`) },
          { key: "clinic_scope", header: t("users.scope"), render: (u: any) => t(`clinic.${u.clinic_scope}`) },
          { key: "flags", header: t("common.status"), render: (u: any) => (
            <span className="flex flex-wrap gap-1">
              {!u.active && <Badge>{t("common.inactive")}</Badge>}
              {u.locked_until && new Date(u.locked_until + "Z") > new Date() && <Badge tone="red">{t("users.locked")} · {fmt.dateTime(u.locked_until + "Z")}</Badge>}
              {u.must_change_pw && <Badge tone="amber">{t("users.mustChange")}</Badge>}
            </span>) },
          { key: "actions", header: "", render: (u: any) => (
            <span className="flex flex-wrap justify-end gap-1">
              <Button size="sm" variant="ghost" onClick={() => setEdit(u)}>{t("common.edit")}</Button>
              <Button size="sm" variant="ghost" onClick={() => reset(u)}>{t("users.reset")}</Button>
              {u.locked_until && <Button size="sm" variant="ghost" onClick={() => unlock(u)}>{t("users.unlock")}</Button>}
            </span>) },
        ]} />
      </Card>
      <UserModal user={edit} onClose={() => setEdit(null)} onSaved={(r) => { reload(); if (r?.one_time_password) setOtp({ user: r.username, password: r.one_time_password }); }} />
      <Modal open={Boolean(otp)} onClose={() => setOtp(null)} title={t("users.otp")} size="sm" footer={<Button variant="primary" onClick={() => setOtp(null)}>{t("common.close")}</Button>}>
        {otp && <>
          <p className="mb-3 text-sm">{t("users.otpText", { user: otp.user })}</p>
          <p className="select-all rounded-md bg-slate-100 px-3 py-3 text-center font-mono text-lg tracking-wider dark:bg-slate-800" dir="ltr">{otp.password}</p>
        </>}
      </Modal>
    </>
  );
}

function UserModal({ user, onClose, onSaved }: { user: any | null; onClose: () => void; onSaved: (r: any) => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const lookups = useLookups();
  const [v, setV] = useState<any>({});
  useEffect(() => {
    if (user) setV(user.id ? { ...user, staff_id: user.staff_id ?? "" } : { username: "", role: "receptionist", clinic_scope: "both", staff_id: "" });
  }, [user]);
  if (!user) return null;
  const set = (k: string, x: unknown) => setV((s: any) => ({ ...s, [k]: x }));
  const pickStaff = (id: string) => {
    const s = lookups.staff.find((x) => String(x.id) === id);
    setV((cur: any) => ({ ...cur, staff_id: id, ...(s && !user.id ? { role: s.role, username: cur.username || s.name.toLowerCase().replace(/[^a-z0-9]+/g, ".").replace(/^\.|\.$/g, "") } : {}) }));
  };
  const save = async () => {
    try {
      const body = { role: v.role, clinic_scope: v.clinic_scope, staff_id: v.staff_id ? Number(v.staff_id) : null };
      const r = user.id ? await api.patch(`/users/${user.id}`, { ...body, active: v.active, version: user.version }) : await api.post("/users", { ...body, username: v.username });
      onSaved(r);
      onClose();
    } catch (e) {
      fb.error(e);
    }
  };
  return (
    <Modal open onClose={onClose} title={user.id ? user.username : t("users.new")}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" onClick={save}>{t("common.save")}</Button></>}>
      <div className="grid gap-3">
        <Field label={t("users.staff")}>
          <Select value={v.staff_id ?? ""} onChange={(e) => pickStaff(e.target.value)}>
            <option value="">—</option>{lookups.staff.map((s) => <option key={s.id} value={s.id}>{s.name} · {t(`role.${s.role}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("auth.username")} required><Input value={v.username ?? ""} disabled={Boolean(user.id)} dir="ltr" onChange={(e) => set("username", e.target.value)} /></Field>
        <Field label={t("staff.role")}><Select value={v.role} onChange={(e) => set("role", e.target.value)}>{ROLES.map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}</Select></Field>
        <Field label={t("users.scope")}><Select value={v.clinic_scope} onChange={(e) => set("clinic_scope", e.target.value)}>{["both", "dental", "derma"].map((c) => <option key={c} value={c}>{t(`clinic.${c}`)}</option>)}</Select></Field>
        {user.id && <Checkbox label={t("common.active")} checked={Boolean(v.active)} onChange={(x) => set("active", x)} />}
      </div>
    </Modal>
  );
}
