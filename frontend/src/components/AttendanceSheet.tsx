"use client";
// Monthly attendance sheet (ATT-04); Admin/Finance can record and correct days (ATT-03).
import { useState } from "react";
import { api, openFile } from "@/lib/api";
import { monthISO, todayISO, useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { useLookups } from "./forms";
import { Button, Card, DataTable, ExportButtons, Field, Input, Modal, Select, StatusBadge, Textarea, useFeedback } from "./ui";

const STATUSES = ["Present", "Late", "Absent", "Paid leave", "Unpaid leave", "Day off"];

export function AttendanceSheet({ own }: { own?: boolean }) {
  const { t } = useI18n();
  const { can } = useSession();
  const lookups = useLookups();
  const manage = can("attendance.manage") && !own;
  const [month, setMonth] = useState(monthISO());
  const [staffId, setStaffId] = useState("");
  const [edit, setEdit] = useState<any | null>(null);
  const params = { month, staff_id: staffId || undefined };
  const { data, loading, reload } = useApi<any>("/attendance", params);

  return (
    <>
      <Card padded={false} title={own ? t("prof.attendance") : undefined}>
        <div className="flex flex-wrap items-end gap-3 border-b border-slate-200 p-3 dark:border-slate-700">
          <Field label={t("att.month")}><Input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></Field>
          {manage && (
            <Field label={t("att.employee")}>
              <Select value={staffId} onChange={(e) => setStaffId(e.target.value)}>
                <option value="">{t("common.all")}</option>{lookups.staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            </Field>
          )}
          <div className="ms-auto flex gap-2">
            {manage && <Button onClick={() => setEdit({ staff_id: staffId, date: todayISO(), status: "Absent" })}>+ {t("att.record")}</Button>}
            <ExportButtons pdf onExport={(f) => openFile("/attendance", { ...params, format: f })} />
          </div>
        </div>
        {data?.summary && Object.keys(data.summary).length > 0 && (
          <div className="overflow-x-auto border-b border-slate-200 dark:border-slate-700">
            <table className="min-w-full text-xs">
              <thead><tr className="text-slate-500">
                <th className="px-3 py-2 text-start font-medium">{t("att.employee")}</th>
                {STATUSES.map((s) => <th key={s} className="px-2 py-2 text-end font-medium">{t(`att.${s}`)}</th>)}
                <th className="px-3 py-2 text-end font-medium">{t("att.hours")}</th>
              </tr></thead>
              <tbody>{Object.entries<any>(data.summary).map(([sid, s]) => (
                <tr key={sid} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-1.5 font-medium">{s.staff_name}</td>
                  {STATUSES.map((st) => <td key={st} className="px-2 py-1.5 text-end tabular-nums">{s[st] || ""}</td>)}
                  <td className="px-3 py-1.5 text-end tabular-nums">{s.hours}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <DataTable rows={data?.rows} loading={loading} onRowClick={manage ? setEdit : undefined} columns={[
          { key: "date", header: t("common.date") },
          ...(own ? [] : [{ key: "staff_name", header: t("att.employee") }]),
          { key: "status", header: t("common.status"), render: (r: any) => <StatusBadge status={r.status} prefix="att." /> },
          { key: "clock_in", header: t("att.in"), render: (r: any) => r.clock_in ?? "—" },
          { key: "clock_out", header: t("att.out"), render: (r: any) => r.clock_out ?? "—" },
          { key: "hours", header: t("att.hours"), align: "end", render: (r: any) => r.hours ?? "—" },
          { key: "note", header: t("common.notes"), render: (r: any) => r.note ?? "" },
          { key: "corrected_by", header: t("att.correctedBy"), render: (r: any) => r.corrected_by ?? "" },
        ]} />
      </Card>
      {manage && <RecordModal rec={edit} onClose={() => setEdit(null)} onSaved={reload} staff={lookups.staff} />}
    </>
  );
}

function RecordModal({ rec, onClose, onSaved, staff }: { rec: any | null; onClose: () => void; onSaved: () => void; staff: { id: number; name: string }[] }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const [v, setV] = useState<any>({});
  const [key, setKey] = useState<any>(null);
  if (rec !== key) {
    setKey(rec);
    if (rec) setV({ staff_id: rec.staff_id ?? "", date: rec.date, status: rec.status, clock_in: rec.clock_in ?? "", clock_out: rec.clock_out ?? "", note: "" });
  }
  if (!rec) return null;
  const set = (k: string, x: unknown) => setV((s: any) => ({ ...s, [k]: x }));
  const save = async () => {
    try {
      if (rec.id) {
        await api.patch(`/attendance/${rec.id}`, { status: v.status, clock_in: v.clock_in || null, clock_out: v.clock_out || null, note: v.note, version: rec.version });
      } else {
        await api.post("/attendance", { staff_id: Number(v.staff_id), date: v.date, status: v.status, clock_in: v.clock_in || null, clock_out: v.clock_out || null, note: v.note });
      }
      onSaved();
      onClose();
    } catch (e) {
      fb.error(e);
    }
  };
  return (
    <Modal open onClose={onClose} title={rec.id ? `${t("att.correct")} · ${rec.staff_name} · ${rec.date}` : t("att.record")}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" disabled={v.note.trim().length < 3 || !v.staff_id} onClick={save}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        {!rec.id && <>
          <Field label={t("att.employee")} required><Select value={v.staff_id} onChange={(e) => set("staff_id", e.target.value)}><option value="">—</option>{staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
          <Field label={t("common.date")} required><Input type="date" value={v.date} onChange={(e) => set("date", e.target.value)} /></Field>
        </>}
        <Field label={t("common.status")}><Select value={v.status} onChange={(e) => set("status", e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{t(`att.${s}`)}</option>)}</Select></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label={t("att.in")}><Input type="time" value={v.clock_in} onChange={(e) => set("clock_in", e.target.value)} /></Field>
          <Field label={t("att.out")}><Input type="time" value={v.clock_out} onChange={(e) => set("clock_out", e.target.value)} /></Field>
        </div>
        <Field label={t("common.reason")} required className="sm:col-span-2"><Textarea value={v.note} onChange={(e) => set("note", e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
