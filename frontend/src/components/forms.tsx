"use client";
// Domain forms reused across pages: patient, appointment, clinical note.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { todayISO, useApi, useDebounced } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, Button, Checkbox, ClinicBadge, Field, Input, Modal, Select, Textarea, useFeedback, useForm } from "./ui";

export interface Lookups { doctors: { id: number; name: string; clinic_scope: string }[]; staff: { id: number; name: string; role: string }[]; time_zones: string[] }

export function useLookups() {
  return useApi<Lookups>("/lookups").data ?? { doctors: [], staff: [], time_zones: [] };
}

export function useServices(clinic?: string, activeOnly = true) {
  const { clinicParam } = useSession();
  return useApi<any[]>("/services", { clinic: clinic ?? clinicParam, active: activeOnly ? true : undefined }).data ?? [];
}

// ---------------------------------------------------------------- patient picker
export function PatientPicker({ value, onChange, label }: { value: any | null; onChange: (p: any | null) => void; label?: string }) {
  const { t } = useI18n();
  const { clinicParam } = useSession();
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const { data } = useApi<any>(dq.length >= 2 ? "/patients" : null, { q: dq, page_size: 8, clinic: clinicParam });
  if (value) {
    return (
      <Field label={label ?? t("common.patient")} required>
        <div className="flex items-center justify-between rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800">
          <span><span className="font-medium">{value.name}</span> <span className="text-slate-500">{value.file_no} · {value.phone}</span></span>
          <button type="button" className="text-xs underline" onClick={() => onChange(null)}>{t("common.edit")}</button>
        </div>
      </Field>
    );
  }
  return (
    <div className="relative">
      <Field label={label ?? t("common.patient")} required>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("common.search")} autoComplete="off" />
      </Field>
      {dq.length >= 2 && data?.items && (
        <ul className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
          {data.items.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">{t("common.none")}</li>}
          {data.items.map((p: any) => (
            <li key={p.id}>
              <button type="button" className="block w-full px-3 py-2 text-start text-sm hover:bg-slate-50 dark:hover:bg-slate-800" onClick={() => onChange(p)}>
                <span className="font-medium">{p.name}</span> <span className="text-slate-500">{p.file_no} · {p.phone}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- patient form (PAT-01/02)
const emptyPatient = { name: "", phone: "", email: "", dob: "", gender: "", address: "", insurance: "", allergies: "", history: "", notes: "", clinic_scope: "both" };

export function PatientModal({ open, onClose, patient, onSaved }: { open: boolean; onClose: () => void; patient?: any; onSaved: (p: any) => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { me } = useSession();
  const f = useForm<typeof emptyPatient>(emptyPatient);
  const [dups, setDups] = useState<any[] | null>(null);
  useEffect(() => {
    if (open) {
      f.setValues(patient ? { ...emptyPatient, ...Object.fromEntries(Object.entries(patient).map(([k, v]) => [k, v ?? ""])) } as any
        : { ...emptyPatient, clinic_scope: me.clinic_scope });
      setDups(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, patient]);

  const save = (confirmDuplicate = false) => f.run(async () => {
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(f.values)) body[k] = v === "" ? null : v;
    body.name = f.values.name.trim();
    body.phone = f.values.phone.trim();
    if (!body.name || !body.phone) {
      f.setErrors({ ...(body.name ? {} : { name: t("common.required") }), ...(body.phone ? {} : { phone: t("common.required") }) });
      return;
    }
    try {
      const saved = patient
        ? await api.patch(`/patients/${patient.id}`, { ...body, version: patient.version })
        : await api.post("/patients", body, { confirm_duplicate: confirmDuplicate });
      fb.ok(t("common.saved"));
      onSaved(saved);
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.code === "duplicate" && Array.isArray(e.detail.candidates)) setDups(e.detail.candidates as any[]);
      else throw e;
    }
  }, (e) => !(e instanceof ApiError && Object.keys(e.fields).length) && fb.error(e));

  const scopes = me.clinic_scope === "both" ? ["both", "dental", "derma"] : [me.clinic_scope, "both"];
  return (
    <Modal open={open} onClose={onClose} size="lg" title={patient ? patient.name : t("pat.new")}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" loading={f.busy} onClick={() => save(false)}>{t("common.save")}</Button></>}>
      {dups ? (
        <div className="space-y-3">
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"><strong>{t("pat.duplicate")}.</strong> {t("pat.duplicateText")}</p>
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 dark:divide-slate-800 dark:border-slate-700">
            {dups.map((d) => (
              <li key={d.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <span><span className="font-medium">{d.name}</span> <span className="text-slate-500">{d.file_no} · {d.phone} · {d.dob ?? ""}</span></span>
                <Link className="text-brand-700 underline" href={`/patients/${d.id}`} onClick={onClose}>{t("common.open")}</Link>
              </li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <Button onClick={() => setDups(null)}>{t("common.back")}</Button>
            <Button variant="primary" loading={f.busy} onClick={() => save(true)}>{t("pat.createAnyway")}</Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("common.name")} required error={f.errors.name}><Input {...f.bind("name")} /></Field>
          <Field label={t("common.phone")} required error={f.errors.phone}><Input type="tel" {...f.bind("phone")} /></Field>
          <Field label={t("pat.dob")} error={f.errors.dob}><Input type="date" {...f.bind("dob")} /></Field>
          <Field label={t("pat.gender")}>
            <Select {...f.bind("gender")}>
              <option value="">—</option><option value="male">{t("pat.male")}</option><option value="female">{t("pat.female")}</option><option value="other">{t("pat.other")}</option>
            </Select>
          </Field>
          <Field label={t("common.email")} error={f.errors.email}><Input type="email" {...f.bind("email")} /></Field>
          <Field label={t("pat.scope")}>
            <Select {...f.bind("clinic_scope")}>{scopes.map((s) => <option key={s} value={s}>{t(`clinic.${s}`)}</option>)}</Select>
          </Field>
          <Field label={t("pat.insurance")}><Input {...f.bind("insurance")} /></Field>
          <Field label={t("pat.address")}><Input {...f.bind("address")} /></Field>
          <Field label={t("pat.allergies")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("allergies")} /></Field>
          <Field label={t("pat.history")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("history")} /></Field>
          <Field label={t("common.notes")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("notes")} /></Field>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------- appointment form (APPT-02/03/05)
export function AppointmentModal({ open, onClose, appt, preset, onSaved }: {
  open: boolean; onClose: () => void; appt?: any; preset?: { date?: string; time?: string; patient?: any; doctor_id?: number; room?: string }; onSaved: (a: any) => void;
}) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { me, settings, view, can } = useSession();
  const lookups = useLookups();
  const services = useServices("");
  const [patient, setPatient] = useState<any | null>(null);
  const f = useForm({ clinic: "dental", doctor_id: "", service_id: "", date: todayISO(), time: "09:00", duration_min: "30", room: "", notes: "", override_reason: "" });
  const [conflicts, setConflicts] = useState<any[] | null>(null);

  useEffect(() => {
    if (!open) return;
    setConflicts(null);
    if (appt) {
      setPatient({ id: appt.patient_id, name: appt.patient_name, file_no: appt.patient_file_no, phone: appt.patient_phone });
      f.setValues({ clinic: appt.clinic, doctor_id: String(appt.doctor_id ?? ""), service_id: String(appt.service_id ?? ""), date: appt.date, time: appt.time,
        duration_min: String(appt.duration_min), room: appt.room ?? "", notes: appt.notes ?? "", override_reason: "" });
    } else {
      setPatient(preset?.patient ?? null);
      const clinic = me.clinic_scope !== "both" ? me.clinic_scope : view !== "both" ? view : "dental";
      f.setValues({ clinic, doctor_id: preset?.doctor_id ? String(preset.doctor_id) : "", service_id: "", date: preset?.date ?? todayISO(),
        time: preset?.time ?? "09:00", duration_min: "30", room: preset?.room ?? "", notes: "", override_reason: "" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, appt]);

  const clinicServices = services.filter((s) => s.clinic === f.values.clinic);
  const doctors = lookups.doctors.filter((d) => d.clinic_scope === "both" || d.clinic_scope === f.values.clinic);
  const pickService = (id: string) => {
    const s = services.find((x) => String(x.id) === id);
    f.setValues((v) => ({ ...v, service_id: id, ...(s ? { duration_min: String(s.duration_min), clinic: s.clinic } : {}) }));
  };

  const save = () => f.run(async () => {
    if (!patient) {
      f.setErrors({ patient: t("common.required") });
      return;
    }
    const body = {
      patient_id: patient.id, clinic: f.values.clinic, doctor_id: f.values.doctor_id ? Number(f.values.doctor_id) : null,
      service_id: f.values.service_id ? Number(f.values.service_id) : null, date: f.values.date, time: f.values.time,
      duration_min: Number(f.values.duration_min) || null, room: f.values.room || null, notes: f.values.notes || null,
      override_reason: f.values.override_reason || null,
    };
    try {
      const saved = appt ? await api.patch(`/appointments/${appt.id}`, { ...body, version: appt.version }) : await api.post("/appointments", body);
      fb.ok(t("common.saved"));
      onSaved(saved);
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.code === "overlap") setConflicts(e.detail.conflicts as any[]);
      else throw e;
    }
  }, (e) => fb.error(e));

  return (
    <Modal open={open} onClose={onClose} size="lg" title={appt ? `${appt.patient_name} · ${appt.date} ${appt.time}` : t("appt.new")}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" loading={f.busy} onClick={save}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><PatientPicker value={patient} onChange={setPatient} /></div>
        {me.clinic_scope === "both" && (
          <Field label={t("common.clinic")} required>
            <Select value={f.values.clinic} onChange={(e) => f.setValues((v) => ({ ...v, clinic: e.target.value, service_id: "" }))}>
              <option value="dental">{settings.clinics.dental.name}</option><option value="derma">{settings.clinics.derma.name}</option>
            </Select>
          </Field>
        )}
        <Field label={t("common.service")}>
          <Select value={f.values.service_id} onChange={(e) => pickService(e.target.value)}>
            <option value="">—</option>
            {clinicServices.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.duration_min}′)</option>)}
          </Select>
        </Field>
        <Field label={t("common.doctor")}>
          <Select {...f.bind("doctor_id")}><option value="">{t("appt.unassigned")}</option>{doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select>
        </Field>
        <Field label={t("common.room")}>
          <Select {...f.bind("room")}><option value="">—</option>{settings.rooms.map((r) => <option key={r} value={r}>{r}</option>)}</Select>
        </Field>
        <Field label={t("common.date")} required><Input type="date" {...f.bind("date")} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("common.time")} required><Input type="time" step={300} {...f.bind("time")} /></Field>
          <Field label={t("appt.duration")}><Input type="number" min={5} step={5} {...f.bind("duration_min")} /></Field>
        </div>
        <Field label={t("common.notes")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("notes")} /></Field>
      </div>
      {conflicts && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100" role="alert">
          <p className="mb-2 font-medium">{t("appt.overlap")}</p>
          <ul className="mb-2 space-y-1">
            {conflicts.map((c) => (
              <li key={c.id}>{c.time}–{c.duration_min}′ · {c.patient_name} · {c.doctor_name ?? "—"} · {c.room ?? "—"} — {c.clash.map((k: string) => t(`appt.clash.${k}`)).join(", ")}</li>
            ))}
          </ul>
          {can("appointments.override") && (
            <Field label={t("appt.overrideReason")} hint={t("appt.override")}><Textarea rows={2} {...f.bind("override_reason")} /></Field>
          )}
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------- clinical note (VISIT-01..03)
const SKIN = ["I", "II", "III", "IV", "V", "VI"];
const emptyVisit = { clinic: "dental", doctor_id: "", date: todayISO(), complaint: "", diagnosis: "", treatment: "", prescription: "", teeth: "", skin_type: "", area: "", follow_up: "", notes: "" };

export function VisitModal({ open, onClose, visit, preset, onSaved }: {
  open: boolean; onClose: () => void; visit?: any; preset?: { patient?: any; clinic?: string; doctor_id?: number | null; appointment_id?: number; date?: string }; onSaved: (v: any) => void;
}) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { me, settings, fmt, view, can } = useSession();
  const lookups = useLookups();
  const [patient, setPatient] = useState<any | null>(null);
  const f = useForm<typeof emptyVisit>(emptyVisit);
  const [addendum, setAddendum] = useState("");
  const readOnly = Boolean(visit && !visit.can_edit);


  useEffect(() => {
    if (!open) return;
    setAddendum("");
    if (visit) {
      setPatient({ id: visit.patient_id, name: visit.patient_name });
      f.setValues(Object.fromEntries(Object.keys(emptyVisit).map((k) => [k, visit[k] ?? ""])) as any);
    } else {
      setPatient(preset?.patient ?? null);
      const clinic = preset?.clinic ?? (me.clinic_scope !== "both" ? me.clinic_scope : view !== "both" ? view : "dental");
      f.setValues({ ...emptyVisit, clinic, date: preset?.date ?? todayISO(), doctor_id: preset?.doctor_id ? String(preset.doctor_id) : me.role === "doctor" ? String(me.staff_id ?? "") : "" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, visit]);

  const save = () => f.run(async () => {
    if (!patient) return;
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(f.values)) body[k] = v === "" ? null : v;
    body.doctor_id = f.values.doctor_id ? Number(f.values.doctor_id) : null;
    const saved = visit
      ? await api.patch(`/visits/${visit.id}`, { ...body, clinic: undefined, version: visit.version })
      : await api.post("/visits", { ...body, patient_id: patient.id, appointment_id: preset?.appointment_id ?? null });
    fb.ok(t("common.saved"));
    onSaved(saved);
    onClose();
  }, (e) => fb.error(e));

  const addAddendum = async () => {
    try {
      const saved = await api.post(`/visits/${visit.id}/addenda`, { text: addendum });
      setAddendum("");
      onSaved(saved);
      fb.ok(t("common.saved"));
    } catch (e) {
      fb.error(e);
    }
  };

  const dental = f.values.clinic === "dental";
  const ro = { disabled: readOnly };
  return (
    <Modal open={open} onClose={onClose} size="lg" title={visit ? `${visit.patient_name} · ${fmt.date(visit.date)}` : t("visit.new")}
      footer={<><Button onClick={onClose}>{t("common.close")}</Button>{!readOnly && <Button variant="primary" loading={f.busy} onClick={save}>{t("common.save")}</Button>}</>}>
      {visit && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
          <ClinicBadge clinic={visit.clinic} />
          <span>{t("visit.author")}: {visit.author ?? "—"}</span>
          {visit.locked ? <Badge tone="gray">{t("visit.locked")}</Badge> : <span>{t("visit.editableUntil", { time: fmt.dateTime(visit.locked_at) })}</span>}
        </div>
      )}
      {readOnly && <p className="mb-3 rounded-md bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">{t("visit.lockedText")}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {!visit && <div className="sm:col-span-2"><PatientPicker value={patient} onChange={setPatient} /></div>}
        {!visit && me.clinic_scope === "both" && (
          <Field label={t("common.clinic")} required>
            <Select {...f.bind("clinic")}><option value="dental">{settings.clinics.dental.name}</option><option value="derma">{settings.clinics.derma.name}</option></Select>
          </Field>
        )}
        <Field label={t("common.doctor")}>
          <Select {...f.bind("doctor_id")} {...ro}><option value="">—</option>{lookups.doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select>
        </Field>
        <Field label={t("common.date")}><Input type="date" {...f.bind("date")} {...ro} /></Field>
        <Field label={t("visit.complaint")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("complaint")} {...ro} /></Field>
        <Field label={t("visit.diagnosis")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("diagnosis")} {...ro} /></Field>
        <Field label={t("visit.treatment")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("treatment")} {...ro} /></Field>
        <Field label={t("visit.prescription")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("prescription")} {...ro} /></Field>
        {dental ? (
          <Field label={t("visit.teeth")} hint="16, 17, 46" error={f.errors.teeth}><Input {...f.bind("teeth")} {...ro} /></Field>
        ) : (
          <>
            <Field label={t("visit.skin")} error={f.errors.skin_type}>
              <Select {...f.bind("skin_type")} {...ro}><option value="">—</option>{SKIN.map((s) => <option key={s} value={s}>{s}</option>)}</Select>
            </Field>
            <Field label={t("visit.area")}><Input {...f.bind("area")} {...ro} /></Field>
          </>
        )}
        <Field label={t("visit.followUp")}><Input type="date" {...f.bind("follow_up")} {...ro} /></Field>
        <Field label={t("common.notes")} className="sm:col-span-2"><Textarea rows={2} {...f.bind("notes")} {...ro} /></Field>
      </div>
      {visit && (
        <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-700">
          <h3 className="mb-2 text-sm font-semibold">{t("visit.addenda")}</h3>
          <ul className="mb-2 space-y-2">
            {visit.addenda.map((a: any) => (
              <li key={a.id} className="rounded-md bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800">
                <div className="text-xs text-slate-500">{a.user} · {fmt.dateTime(a.at)}</div>
                <div className="whitespace-pre-wrap">{a.text}</div>
              </li>
            ))}
          </ul>
          {can("visits.write") && <div className="flex gap-2">
            <Textarea rows={2} value={addendum} onChange={(e) => setAddendum(e.target.value)} aria-label={t("visit.addendum")} />
            <Button disabled={!addendum.trim()} onClick={addAddendum}>{t("visit.addendum")}</Button>
          </div>}
        </div>
      )}
    </Modal>
  );
}

export { Checkbox };
