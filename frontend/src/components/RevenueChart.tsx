"use client";
// 6-month revenue per clinic: grouped bars on one axis, legend + hover tooltip + table view.
// Series colours validated for colour-vision deficiency in light and dark (dental #1d4ed8, derma #a855f7).
import { useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const SERIES = [
  { key: "dental", color: "#1d4ed8" },
  { key: "derma", color: "#a855f7" },
] as const;

type Row = { month: string; dental?: number; derma?: number };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / p / 2) * 2 * p;
}

export function RevenueChart({ data }: { data: Row[] }) {
  const { t, lang } = useI18n();
  const { fmt, settings } = useSession();
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const series = SERIES.filter((s) => data.some((r) => r[s.key] !== undefined));
  const max = niceMax(Math.max(0, ...data.flatMap((r) => series.map((s) => r[s.key] ?? 0))));
  const W = 640, H = 220, padL = 8, padB = 24, padT = 16;
  const plotH = H - padB - padT;
  const groupW = (W - padL) / Math.max(1, data.length);
  const barW = Math.min(28, (groupW * 0.6) / Math.max(1, series.length));
  const monthName = (m: string) =>
    new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en-GB", { month: "short", timeZone: "UTC" }).format(new Date(`${m}-01T00:00:00Z`));
  const ticks = [0, 0.5, 1].map((f) => f * max);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-slate-600 dark:text-slate-300">
        {series.length > 1 && series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {settings.clinics[s.key]?.name ?? t(`clinic.${s.key}`)}
          </span>
        ))}
        <button type="button" className="ms-auto underline" onClick={() => setTable((v) => !v)} aria-pressed={table}>
          {table ? t("common.chart") : t("common.table")}
        </button>
      </div>
      {table ? (
        <table className="w-full text-sm">
          <thead><tr className="text-slate-500"><th className="text-start font-medium">{t("payroll.month")}</th>
            {series.map((s) => <th key={s.key} className="text-end font-medium">{settings.clinics[s.key]?.name}</th>)}</tr></thead>
          <tbody>{data.map((r) => (
            <tr key={r.month} className="border-t border-slate-100 dark:border-slate-800"><td>{monthName(r.month)} {r.month.slice(0, 4)}</td>
              {series.map((s) => <td key={s.key} className="text-end tabular-nums">{fmt.money(r[s.key] ?? 0)}</td>)}</tr>
          ))}</tbody>
        </table>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={t("dash.chart")}>
            {ticks.map((v) => {
              const y = padT + plotH - (v / max) * plotH;
              return (
                <g key={v}>
                  <line x1={padL} x2={W} y1={y} y2={y} className="stroke-slate-200 dark:stroke-slate-700" strokeWidth={1} />
                  {v > 0 && <text x={W} y={y - 3} textAnchor="end" className="fill-slate-500 text-[10px] dark:fill-slate-400">{fmt.money(v)}</text>}
                </g>
              );
            })}
            {data.map((r, i) => {
              const gx = padL + i * groupW + groupW / 2 - (series.length * barW + (series.length - 1) * 2) / 2;
              return (
                <g key={r.month} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                  <rect x={padL + i * groupW} y={0} width={groupW} height={H} fill={hover === i ? "currentColor" : "transparent"} className="text-slate-100 dark:text-slate-800" opacity={hover === i ? 0.6 : 0} />
                  {series.map((s, j) => {
                    const v = Math.max(0, r[s.key] ?? 0);
                    const h = (v / max) * plotH;
                    const x = gx + j * (barW + 2);
                    const y = padT + plotH - h;
                    const rr = Math.min(4, h / 2, barW / 2);
                    // rounded data-end, square at the baseline
                    const d = h <= 0 ? "" : `M${x},${padT + plotH} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + barW - rr} Q${x + barW},${y} ${x + barW},${y + rr} V${padT + plotH} Z`;
                    return d && <path key={s.key} d={d} fill={s.color} />;
                  })}
                  <text x={padL + i * groupW + groupW / 2} y={H - 6} textAnchor="middle" className="fill-slate-500 text-[11px] dark:fill-slate-400">{monthName(r.month)}</text>
                </g>
              );
            })}
            <line x1={padL} x2={W} y1={padT + plotH} y2={padT + plotH} className="stroke-slate-300 dark:stroke-slate-600" strokeWidth={1} />
          </svg>
          {hover !== null && data[hover] && (
            <div className="pointer-events-none absolute top-0 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-md dark:border-slate-700 dark:bg-slate-900"
              style={{ insetInlineStart: `${Math.min(70, (hover / data.length) * 100)}%` }}>
              <div className="mb-1 font-medium text-slate-900 dark:text-white">{monthName(data[hover].month)} {data[hover].month.slice(0, 4)}</div>
              {series.map((s) => (
                <div key={s.key} className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                  <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />
                  <span>{settings.clinics[s.key]?.name}</span>
                  <span className="ms-auto ps-3 tabular-nums">{fmt.money(data[hover][s.key] ?? 0)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
