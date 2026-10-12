"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AppointmentModal, useLookups, VisitModal } from "@/components/forms";
import { Button, Card, ClinicBadge, Input, Modal, PageHeader, Select, StatusBadge, Tabs, cx, useFeedback } from "@/components/ui";
import { api } from "@/lib/api";
import { addDays, todayISO, useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const STATUSES = ["Scheduled", "Confirmed", "Checked-in", "In progress", "Completed", "Cancelled", "No-show"];
const START_H = 7, END_H = 21, PX_PER_MIN = 1.1;
const toMin = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));

function weekStart(iso: string) {
  const d = new Date(`${iso}T00:00:00Z`);
  const dow = (d.getUTCDay() + 1) % 7; // weeks start on Saturday
  return addDays(iso, -dow);
}

export default function AppointmentsPage() {
  const { t, lang } = useI18n();
  const fb = useFeedback();
  const router = useRouter();
  const { clinicParam, settings, can, fmt } = useSession();
  const lookups = useLookups();
  const [mode, setMode] = useState<"day" | "week">("day");
  const [by, setBy] = useState<"doctor" | "room">("doctor");
  const [date, setDate] = useState(todayISO());
  const [filter, setFilter] = useState("");
  const [edit, setEdit] = useState<{ appt?: any; preset?: any } | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [completed, setCompleted] = useState<any | null>(null);
  const [visitPreset, setVisitPreset] = useState<any | null>(null);

  const from = mode === "day" ? date : weekStart(date);
  const params = { date: from, days: mode === "day" ? 1 : 7, clinic: clinicParam,
    doctor: mode === "week" && by === "doctor" && filter ? filter : undefined,
    room: mode === "week" && by === "room" && filter ? filter : undefined };
  const { data: appts, reload } = useApi<any[]>("/appointments", params);
  const history = useApi<any[]>(detail ? `/appointments/${detail.id}/history` : null);

  const columns = useMemo(() => {
    if (by === "room") return [...settings.rooms.map((r) => ({ key: r, label: r })), { key: "", label: t("appt.unassigned") }];
    const docs = lookups.doctors.filter((d) => !clinicParam || d.clinic_scope === "both" || d.clinic_scope === clinicParam);
    return [...docs.map((d) => ({ key: String(d.id), label: d.name })), { key: "", label: t("appt.unassigned") }];
  }, [by, settings.rooms, lookups.doctors, clinicParam, t]);

  const keyOf = (a: any) => (by === "room" ? a.room ?? "" : String(a.doctor_id ?? ""));
  const visibleCols = columns.filter((c) => c.key !== "" || (appts ?? []).some((a) => keyOf(a) === ""));

  const setStatus = async (a: any, status: string) => {
    try {
      const res = await api.post(`/appointments/${a.id}/status`, { status });
      setDetail(res);
      reload();
      if (status === "Completed" && res.next && (res.next.visit || res.next.invoice)) setCompleted(res);
    } catch (e) {
      fb.error(e);
    }
  };

  const dayLabel = (iso: string) =>
    new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));

  const Card_ = ({ a, style }: { a: any; style?: React.CSSProperties }) => (
    <button type="button" onClick={() => setDetail(a)} style={style}
      className={cx("w-full overflow-hidden rounded-md border-s-4 px-2 py-1 text-start text-xs shadow-sm",
        a.clinic === "dental" ? "border-dental-600 bg-dental-50 dark:bg-slate-800" : "border-derma-600 bg-derma-50 dark:bg-slate-800",
        ["Cancelled", "No-show"].includes(a.status) && "opacity-50 line-through")}>
      <div className="font-semibold text-slate-900 dark:text-white">{a.time} · {a.patient_name}</div>
      <div className="truncate text-slate-600 dark:text-slate-300">{a.service_name ?? ""} {by === "doctor" ? a.room ?? "" : a.doctor_name ?? ""}</div>
    </button>
  );

  const hours = Array.from({ length: END_H - START_H }, (_, i) => START_H + i);
  const height = (END_H - START_H) * 60 * PX_PER_MIN;

  return (
    <>
      <PageHeader title={t("appt.title")} actions={can("appointments.write") && <Button variant="primary" onClick={() => setEdit({ preset: { date } })}>+ {t("appt.new")}</Button>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 p-3 dark:border-slate-700">
          <Button size="sm" onClick={() => setDate(addDays(date, mode === "day" ? -1 : -7))} aria-label={t("common.prev")}><span className="flip-rtl">‹</span></Button>
          <Input type="date" className="!w-auto" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} aria-label={t("common.date")} />
          <Button size="sm" onClick={() => setDate(addDays(date, mode === "day" ? 1 : 7))} aria-label={t("common.next")}><span className="flip-rtl">›</span></Button>
          <Button size="sm" variant="ghost" onClick={() => setDate(todayISO())}>{t("common.today")}</Button>
          <div className="ms-auto flex flex-wrap items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-md border border-slate-300 text-sm dark:border-slate-600" role="group">
              {(["day", "week"] as const).map((m) => (
                <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}
                  className={cx("px-3 py-1.5", mode === m ? "bg-brand-600 text-white" : "bg-white dark:bg-slate-800")}>{t(`appt.${m}`)}</button>
              ))}
            </div>
            <Select className="!w-auto" value={by} onChange={(e) => { setBy(e.target.value as "doctor"); setFilter(""); }} aria-label={t("appt.byDoctor")}>
              <option value="doctor">{t("appt.byDoctor")}</option><option value="room">{t("appt.byRoom")}</option>
            </Select>
            {mode === "week" && (
              <Select className="!w-auto" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={by === "doctor" ? t("common.doctor") : t("common.room")}>
                <option value="">{t("common.all")}</option>
                {columns.filter((c) => c.key).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
              </Select>
            )}
          </div>
        </div>

        {mode === "day" ? (
          <div className="overflow-x-auto">
            <div className="flex min-w-max">
              <div className="w-14 shrink-0 border-e border-slate-200 dark:border-slate-700">
                <div className="h-9" />
                <div className="relative" style={{ height }}>
                  {hours.map((h) => (
                    <div key={h} className="absolute w-full pe-1 text-end text-[11px] tabular-nums text-slate-500" style={{ top: (h - START_H) * 60 * PX_PER_MIN - 6 }}>{String(h).padStart(2, "0")}:00</div>
                  ))}
                </div>
              </div>
              {visibleCols.map((col) => (
                <div key={col.key || "none"} className="w-48 shrink-0 border-e border-slate-200 dark:border-slate-700">
                  <div className="sticky top-0 h-9 truncate border-b border-slate-200 bg-slate-50 px-2 py-2 text-xs font-semibold dark:border-slate-700 dark:bg-slate-800">{col.label}</div>
                  <div className="relative" style={{ height }}
                    onClick={(e) => {
                      if (!can("appointments.write") || e.target !== e.currentTarget) return;
                      const y = e.nativeEvent.offsetY / PX_PER_MIN;
                      const m = Math.floor(y / 15) * 15 + START_H * 60;
                      const time = `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
                      setEdit({ preset: { date, time, ...(by === "doctor" ? { doctor_id: col.key ? Number(col.key) : undefined } : { room: col.key }) } });
                    }}>
                    {hours.map((h) => <div key={h} className="pointer-events-none absolute w-full border-t border-slate-100 dark:border-slate-800" style={{ top: (h - START_H) * 60 * PX_PER_MIN }} />)}
                    {(appts ?? []).filter((a) => keyOf(a) === col.key).map((a) => {
                      const top = Math.max(0, (toMin(a.time) - START_H * 60) * PX_PER_MIN);
                      return <div key={a.id} className="absolute inset-x-1" style={{ top }}><Card_ a={a} style={{ height: Math.max(22, a.duration_min * PX_PER_MIN - 2) }} /></div>;
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 divide-y divide-slate-200 dark:divide-slate-700 md:grid-cols-7 md:divide-x md:divide-y-0 rtl:md:divide-x-reverse">
            {Array.from({ length: 7 }, (_, i) => addDays(from, i)).map((d) => (
              <div key={d} className="min-h-32 p-2">
                <button type="button" className={cx("mb-2 text-xs font-semibold", d === todayISO() && "text-brand-700 dark:text-brand-100")} onClick={() => { setDate(d); setMode("day"); }}>{dayLabel(d)}</button>
                <div className="space-y-1">{(appts ?? []).filter((a) => a.date === d).map((a) => <Card_ key={a.id} a={a} />)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Modal open={Boolean(detail)} onClose={() => setDetail(null)} title={detail ? `${detail.patient_name} · ${fmt.date(detail.date)} ${detail.time}` : ""}
        footer={detail && <>
          {detail.invoice_id && <Link className="text-sm underline" href={`/billing/${detail.invoice_id}`}>{t("appt.openInvoice")}</Link>}
          <Button onClick={() => setDetail(null)}>{t("common.close")}</Button>
          {can("appointments.write") && <Button variant="primary" onClick={() => { setEdit({ appt: detail }); setDetail(null); }}>{t("common.edit")}</Button>}
        </>}>
        {detail && (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-2"><ClinicBadge clinic={detail.clinic} /><StatusBadge status={detail.status} prefix="st." /></div>
            <dl className="grid grid-cols-3 gap-y-1">
              <dt className="text-slate-500">{t("common.patient")}</dt><dd className="col-span-2"><Link className="underline" href={`/patients/${detail.patient_id}`}>{detail.patient_name}</Link> · {detail.patient_phone}</dd>
              <dt className="text-slate-500">{t("common.doctor")}</dt><dd className="col-span-2">{detail.doctor_name ?? "—"}</dd>
              <dt className="text-slate-500">{t("common.service")}</dt><dd className="col-span-2">{detail.service_name ?? "—"} ({detail.duration_min}′)</dd>
              <dt className="text-slate-500">{t("common.room")}</dt><dd className="col-span-2">{detail.room ?? "—"}</dd>
              {detail.notes && <><dt className="text-slate-500">{t("common.notes")}</dt><dd className="col-span-2 whitespace-pre-wrap">{detail.notes}</dd></>}
              {detail.override_reason && <><dt className="text-slate-500">{t("appt.overrideReason")}</dt><dd className="col-span-2">{detail.override_reason}</dd></>}
            </dl>
            {can("appointments.write") && (
              <div className="flex flex-wrap gap-1.5">
                {STATUSES.filter((s) => s !== detail.status).map((s) => (
                  <Button key={s} size="sm" variant={s === "Completed" ? "primary" : "secondary"} onClick={() => setStatus(detail, s)}>{t(`st.${s}`)}</Button>
                ))}
              </div>
            )}
            <div>
              <h3 className="mb-1 font-semibold">{t("appt.history")}</h3>
              <ol className="space-y-0.5 text-xs text-slate-600 dark:text-slate-400">
                {(history.data ?? []).map((h, i) => <li key={i}>{h.local} · {h.from ? `${t(`st.${h.from}`)} → ` : ""}{t(`st.${h.to}`)} · {h.user}</li>)}
              </ol>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={Boolean(completed)} onClose={() => setCompleted(null)} title={t("appt.complete")} size="sm"
        footer={<>
          <Button onClick={() => setCompleted(null)}>{t("common.close")}</Button>
          {completed?.next?.visit && can("visits.write") && (
            <Button onClick={() => { setVisitPreset({ ...completed.next.visit, patient: { id: completed.patient_id, name: completed.patient_name, file_no: completed.patient_file_no, phone: completed.patient_phone } }); setCompleted(null); setDetail(null); }}>{t("appt.openNote")}</Button>
          )}
          {completed?.next?.invoice && can("billing.create") && (
            <Button variant="primary" onClick={() => router.push(`/billing/new?appointment=${completed.id}`)}>{t("appt.openInvoice")}</Button>
          )}
        </>}>
        <p className="text-sm">{t("appt.completeText")}</p>
      </Modal>

      <AppointmentModal open={Boolean(edit)} onClose={() => setEdit(null)} appt={edit?.appt} preset={edit?.preset} onSaved={() => reload()} />
      <VisitModal open={Boolean(visitPreset)} onClose={() => setVisitPreset(null)} preset={visitPreset ?? undefined} onSaved={() => reload()} />
    </>
  );
}
