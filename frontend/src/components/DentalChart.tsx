"use client";
// FDI dental chart with per-tooth history (CHART-01..03).
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Button, Card, Field, Input, Select, Tabs, cx, useFeedback } from "./ui";

// Fill + text pairs chosen for ≥ 4.5:1 contrast on the tooth number
const COND: Record<string, { bg: string; text: string }> = {
  Healthy: { bg: "#ffffff", text: "#0f172a" },
  Caries: { bg: "#fecaca", text: "#7f1d1d" },
  Filling: { bg: "#bfdbfe", text: "#1e3a8a" },
  Crown: { bg: "#fde68a", text: "#78350f" },
  "Root canal": { bg: "#fbcfe8", text: "#831843" },
  Implant: { bg: "#c7d2fe", text: "#312e81" },
  Missing: { bg: "#cbd5e1", text: "#334155" },
  "Planned extraction": { bg: "#fed7aa", text: "#7c2d12" },
};

const PERMANENT = { upper: [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28], lower: [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38] };
const PRIMARY = { upper: [55, 54, 53, 52, 51, 61, 62, 63, 64, 65], lower: [85, 84, 83, 82, 81, 71, 72, 73, 74, 75] };

export function DentalChart({ patientId }: { patientId: number }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { can, fmt } = useSession();
  const { data, reload } = useApi<any>(`/patients/${patientId}/teeth`);
  const [set, setSet] = useState<"permanent" | "primary">("permanent");
  const [tooth, setTooth] = useState<number | null>(null);
  const [condition, setCondition] = useState("Caries");
  const [surface, setSurface] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const rows = set === "permanent" ? PERMANENT : PRIMARY;
  const current = data?.current ?? {};

  const save = async () => {
    if (!tooth) return;
    setBusy(true);
    try {
      await api.post(`/patients/${patientId}/teeth`, { tooth, condition, surface: surface || null, note: note || null });
      setNote("");
      setSurface("");
      await reload();
      fb.ok(t("common.saved"));
    } catch (e) {
      fb.error(e);
    } finally {
      setBusy(false);
    }
  };

  const Tooth = ({ n }: { n: number }) => {
    const c = current[n]?.condition ?? "Healthy";
    const style = COND[c];
    return (
      <button type="button" onClick={() => setTooth(n)} aria-pressed={tooth === n} aria-label={`${n} ${t(`cond.${c}`)}`}
        className={cx("flex h-10 w-8 flex-col items-center justify-center rounded-md border text-xs font-semibold tabular-nums sm:h-11 sm:w-9",
          tooth === n ? "ring-2 ring-brand-600 ring-offset-1" : "", c === "Missing" ? "border-dashed border-slate-400" : "border-slate-300")}
        style={{ background: style.bg, color: style.text }}>
        {n}
      </button>
    );
  };

  return (
    <div className="grid gap-4 2xl:grid-cols-3">
      <Card className="2xl:col-span-2">
        <Tabs tabs={[{ id: "permanent", label: t("chart.permanent") }, { id: "primary", label: t("chart.primary") }]} active={set} onChange={(v) => { setSet(v as "permanent"); setTooth(null); }} />
        <div className="overflow-x-auto" dir="ltr">
          <div className="mx-auto w-max space-y-3 py-2">
            {[rows.upper, rows.lower].map((row, i) => (
              <div key={i} className="flex gap-1">
                {row.map((n, j) => (
                  <span key={n} className={cx("flex", j === row.length / 2 && "ms-2 border-s-2 border-slate-300 ps-2 dark:border-slate-600")}><Tooth n={n} /></span>
                ))}
              </div>
            ))}
          </div>
        </div>
        <ul className="mt-3 flex flex-wrap gap-3 text-xs" aria-label="Legend">
          {Object.entries(COND).map(([k, v]) => (
            <li key={k} className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-sm border border-slate-300" style={{ background: v.bg }} />{t(`cond.${k}`)}
            </li>
          ))}
        </ul>
      </Card>
      <Card title={tooth ? t("chart.history", { tooth }) : t("chart.pick")}>
        {tooth && can("chart.write") && (
          <div className="mb-4 space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <Field label={t("chart.condition")}>
                <Select value={condition} onChange={(e) => setCondition(e.target.value)}>
                  {Object.keys(COND).map((k) => <option key={k} value={k}>{t(`cond.${k}`)}</option>)}
                </Select>
              </Field>
              <Field label={t("chart.surface")}>
                <Select value={surface} onChange={(e) => setSurface(e.target.value)}>
                  <option value="">—</option>{["M", "O", "D", "B", "L", "MO", "DO", "MOD"].map((s) => <option key={s}>{s}</option>)}
                </Select>
              </Field>
            </div>
            <Field label={t("common.notes")}><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            <Button variant="primary" size="sm" loading={busy} onClick={save}>{t("chart.add")}</Button>
          </div>
        )}
        {tooth && (
          <ol className="space-y-2">
            {(data?.history?.[tooth] ?? []).map((h: any) => (
              <li key={h.id} className="rounded-md border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{t(`cond.${h.condition}`)}{h.surface ? ` · ${h.surface}` : ""}</span>
                  <span className="text-xs text-slate-500">{fmt.dateTime(h.at)}</span>
                </div>
                {h.note && <div className="text-slate-600 dark:text-slate-300">{h.note}</div>}
                <div className="text-xs text-slate-500">{h.user}</div>
              </li>
            ))}
            {!(data?.history?.[tooth]?.length) && <li className="text-sm text-slate-500">{t("cond.Healthy")}</li>}
          </ol>
        )}
      </Card>
    </div>
  );
}
