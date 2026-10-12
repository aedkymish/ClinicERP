"use client";
import Link from "next/link";
import { useState } from "react";
import { RevenueChart } from "@/components/RevenueChart";
import { Badge, Button, Card, ClinicBadge, DataTable, PageHeader, Stat, StatusBadge, useFeedback } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

function ClockCard() {
  const { t } = useI18n();
  const fb = useFeedback();
  const { me } = useSession();
  const { data, reload } = useApi<any>(me.staff_id ? "/attendance/today" : null);
  const [busy, setBusy] = useState(false);
  if (!me.staff_id) return null;
  const act = async (path: string) => {
    setBusy(true);
    try {
      await api.post(path);
      await reload();
    } catch (e) {
      fb.error(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      {!data?.clock_in ? (
        <Button variant="primary" loading={busy} onClick={() => act("/attendance/clock-in")}>{t("dash.clockIn")}</Button>
      ) : !data.clock_out ? (
        <>
          <span className="text-sm">{t("dash.clockedIn", { time: data.clock_in })}</span>
          <StatusBadge status={data.status} prefix="att." />
          <Button loading={busy} onClick={() => act("/attendance/clock-out")}>{t("dash.clockOut")}</Button>
        </>
      ) : (
        <span className="text-sm">{t("dash.clockedOut", { in: data.clock_in, out: data.clock_out })}</span>
      )}
    </div>
  );
}

export default function Dashboard() {
  const { t } = useI18n();
  const fb = useFeedback();
  const { clinicParam, fmt, can } = useSession();
  const { data: d, reload } = useApi<any>("/dashboard", { clinic: clinicParam });

  const done = async (visitId: number) => {
    try {
      await api.post(`/visits/${visitId}/follow-up-done`);
      reload();
    } catch (e) {
      fb.error(e);
    }
  };

  return (
    <>
      <PageHeader title={t("dash.title")} subtitle={d && fmt.date(d.today)} actions={<ClockCard />} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {d?.appointments && <Stat label={t("dash.todayAppts")} value={d.appointments.length} />}
        <Stat label={t("dash.patients")} value={fmt.number(d?.total_patients)} />
        {d?.low_stock && <Stat label={t("dash.lowStock")} value={d.low_stock.length} tone={d.low_stock.length ? "red" : undefined} />}
        {d?.mtd_commission !== undefined && <Stat label={t("dash.commission")} value={fmt.money(d.mtd_commission)} />}
        {d?.cash_today !== undefined && <Stat label={t("dash.cashToday")} value={fmt.money(d.cash_today)} />}
        {d?.finance && (
          <>
            <Stat label={t("dash.mtdRevenue")} value={fmt.money(d.finance.mtd_revenue)} tone="green" />
            <Stat label={t("dash.mtdExpenses")} value={fmt.money(d.finance.mtd_expenses)} />
            <Stat label={t("dash.outstanding")} value={fmt.money(d.finance.outstanding)} tone={d.finance.outstanding ? "red" : undefined} />
          </>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {d?.appointments && (
          <Card title={t("dash.todayAppts")} className="lg:col-span-2" padded={false}
            actions={<Link className="text-sm text-brand-700 underline dark:text-brand-100" href="/appointments">{t("nav.appointments")}</Link>}>
            <DataTable rows={d.appointments} columns={[
              { key: "time", header: t("common.time"), className: "tabular-nums" },
              { key: "patient", header: t("common.patient"), render: (a: any) => <Link className="font-medium hover:underline" href={`/patients/${a.patient_id}`}>{a.patient_name}</Link> },
              { key: "doctor", header: t("common.doctor"), render: (a: any) => a.doctor_name ?? "—" },
              { key: "service", header: t("common.service"), render: (a: any) => a.service_name ?? "—" },
              { key: "clinic", header: t("common.clinic"), render: (a: any) => <ClinicBadge clinic={a.clinic} /> },
              { key: "status", header: t("common.status"), render: (a: any) => <StatusBadge status={a.status} prefix="st." /> },
            ]} />
          </Card>
        )}

        {d?.follow_ups && (
          <Card title={t("dash.followUps")}>
            {d.follow_ups.length === 0 ? <p className="text-sm text-slate-500">{t("common.none")}</p> : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {d.follow_ups.map((f: any) => (
                  <li key={f.visit_id} className="flex items-center gap-2 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <Link href={`/patients/${f.patient_id}`} className="font-medium hover:underline">{f.patient_name}</Link>
                      <div className="text-xs text-slate-500">{fmt.date(f.follow_up)} {f.diagnosis ? `· ${f.diagnosis}` : ""}</div>
                    </div>
                    {f.overdue && <Badge tone="red">{t("dash.overdue")}</Badge>}
                    {can("visits.write") && <Button size="sm" onClick={() => done(f.visit_id)}>{t("dash.markDone")}</Button>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}

        {d?.finance && (
          <Card title={t("dash.chart")} className="lg:col-span-2">
            <RevenueChart data={d.finance.chart} />
          </Card>
        )}

        {d?.low_stock && (
          <Card title={`${t("dash.lowStock")} · ${t("dash.expiring")}`}>
            {d.low_stock.length + d.expiring.length === 0 ? <p className="text-sm text-slate-500">{t("common.none")}</p> : (
              <ul className="space-y-1.5 text-sm">
                {d.low_stock.map((i: any) => (
                  <li key={`l${i.id}`} className="flex justify-between gap-2">
                    <span>{i.name}</span>
                    <Badge tone="red">{t("stock.low")} · {fmt.number(i.qty, 2)} {i.unit}</Badge>
                  </li>
                ))}
                {d.expiring.map((i: any) => (
                  <li key={`e${i.id}`} className="flex justify-between gap-2">
                    <span>{i.name}</span>
                    <Badge tone="amber">{i.expired ? t("stock.expired") : t("stock.expiring")} · {fmt.date(i.expiry)}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
      </div>
    </>
  );
}
