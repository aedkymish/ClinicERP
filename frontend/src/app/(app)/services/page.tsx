"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Card, Checkbox, ClinicBadge, DataTable, ExportButtons, Field, Input, Modal, MoneyInput, PageHeader, Select, useFeedback } from "@/components/ui";
import { api, openFile } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function ServicesPage() {
  const { t } = useI18n();
  const { clinicParam, can, fmt } = useSession();
  const [showInactive, setShowInactive] = useState(false);
  const [edit, setEdit] = useState<any | null>(null);
  const { data, loading, reload } = useApi<any[]>("/services", { clinic: clinicParam, active: showInactive ? undefined : true });
  const editable = can("services.write", "services.price");

  return (
    <>
      <PageHeader title={t("svc.title")} actions={can("services.write") && <Button variant="primary" onClick={() => setEdit({})}>+ {t("svc.new")}</Button>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-3 dark:border-slate-700">
          <Checkbox label={t("common.inactive")} checked={showInactive} onChange={setShowInactive} />
          <div className="ms-auto"><ExportButtons onExport={(f) => openFile("/services", { clinic: clinicParam, format: f })} /></div>
        </div>
        <DataTable rows={data} loading={loading} onRowClick={editable ? setEdit : undefined} columns={[
          { key: "name", header: t("common.name"), render: (s: any) => <span className="font-medium">{s.name}{!s.active && <> <Badge>{t("common.inactive")}</Badge></>}</span> },
          { key: "clinic", header: t("common.clinic"), render: (s: any) => <ClinicBadge clinic={s.clinic} /> },
          { key: "category", header: t("common.category"), render: (s: any) => s.category ?? "—" },
          { key: "duration_min", header: t("svc.duration"), align: "end" },
          { key: "price", header: t("common.price"), align: "end", render: (s: any) => fmt.money(s.price) },
          { key: "share_pct", header: t("svc.share"), align: "end", render: (s: any) => (s.share_pct ?? "—") },
          { key: "lab_cost", header: t("svc.lab"), align: "end", render: (s: any) => fmt.money(s.lab_cost) },
          { key: "vat", header: t("inv.vat"), render: (s: any) => (s.vat_applies ? "✓" : "") },
        ]} />
      </Card>
      <ServiceModal service={edit} onClose={() => setEdit(null)} onSaved={reload} />
    </>
  );
}

function ServiceModal({ service, onClose, onSaved }: { service: any | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { can, settings, me } = useSession();
  const full = can("services.write");
  const [v, setV] = useState<any>({});
  const [items, setItems] = useState<{ item_id: number; qty_per_unit: number }[]>([]);
  const stock = useApi<any[]>(service && full ? "/inventory" : null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!service) return;
    setV(service.id ? { ...service } : { clinic: me.clinic_scope === "derma" ? "derma" : "dental", name: "", category: "", duration_min: 30, price: 0, vat_applies: false, share_pct: null, lab_cost: 0 });
    setItems(service.items?.map((i: any) => ({ item_id: i.item_id, qty_per_unit: i.qty_per_unit })) ?? []);
  }, [service, me.clinic_scope]);
  if (!service) return null;
  const set = (k: string, val: unknown) => setV((s: any) => ({ ...s, [k]: val }));

  const save = async () => {
    setBusy(true);
    try {
      const priceFields = { price: v.price, share_pct: v.share_pct === "" ? null : v.share_pct, lab_cost: v.lab_cost, vat_applies: v.vat_applies };
      const body = full ? { clinic: v.clinic, name: v.name, category: v.category || null, duration_min: Number(v.duration_min), ...priceFields } : priceFields;
      const saved = service.id ? await api.patch(`/services/${service.id}`, { ...body, active: full ? v.active : undefined, version: service.version }) : await api.post("/services", body);
      if (full) await api.put(`/services/${saved.id}/items`, items.filter((i) => i.item_id && i.qty_per_unit > 0));
      fb.ok(t("common.saved"));
      onSaved();
      onClose();
    } catch (e) {
      fb.error(e);
    } finally {
      setBusy(false);
    }
  };

  const clinicItems = (stock.data ?? []).filter((i) => i.clinic === "shared" || i.clinic === v.clinic);
  return (
    <Modal open onClose={onClose} title={service.id ? service.name : t("svc.new")} size="lg"
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" loading={busy} onClick={save}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("common.name")} required><Input value={v.name ?? ""} disabled={!full} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label={t("common.clinic")}>
          <Select value={v.clinic} disabled={!full || me.clinic_scope !== "both"} onChange={(e) => set("clinic", e.target.value)}>
            <option value="dental">{settings.clinics.dental.name}</option><option value="derma">{settings.clinics.derma.name}</option>
          </Select>
        </Field>
        <Field label={t("common.category")}><Input value={v.category ?? ""} disabled={!full} onChange={(e) => set("category", e.target.value)} /></Field>
        <Field label={t("svc.duration")}><Input type="number" min={5} step={5} value={v.duration_min ?? 30} disabled={!full} onChange={(e) => set("duration_min", e.target.value)} /></Field>
        <Field label={t("common.price")} required><MoneyInput decimals={settings.currency_decimals} value={v.price} onChange={(x) => set("price", x)} /></Field>
        <Field label={t("svc.share")} hint={t("svc.shareBlank")}><Input type="number" min={0} max={100} step="any" value={v.share_pct ?? ""} onChange={(e) => set("share_pct", e.target.value === "" ? null : Number(e.target.value))} /></Field>
        <Field label={t("svc.lab")}><MoneyInput decimals={settings.currency_decimals} value={v.lab_cost} onChange={(x) => set("lab_cost", x)} /></Field>
        <div className="flex items-end gap-4 pb-2">
          <Checkbox label={t("svc.vat")} checked={Boolean(v.vat_applies)} onChange={(x) => set("vat_applies", x)} />
          {service.id && full && <Checkbox label={t("common.active")} checked={Boolean(v.active)} onChange={(x) => set("active", x)} />}
        </div>
      </div>
      {full && (
        <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-700">
          <h3 className="mb-2 text-sm font-semibold">{t("svc.items")}</h3>
          {items.map((it, i) => (
            <div key={i} className="mb-2 flex items-end gap-2">
              <Select value={it.item_id || ""} aria-label={t("nav.inventory")} onChange={(e) => setItems((s) => s.map((x, j) => (j === i ? { ...x, item_id: Number(e.target.value) } : x)))}>
                <option value="">—</option>{clinicItems.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.unit})</option>)}
              </Select>
              <Input className="!w-28" type="number" min={0} step="any" aria-label={t("common.qty")} value={it.qty_per_unit} onChange={(e) => setItems((s) => s.map((x, j) => (j === i ? { ...x, qty_per_unit: Number(e.target.value) } : x)))} />
              <Button size="sm" variant="ghost" onClick={() => setItems((s) => s.filter((_, j) => j !== i))}>✕</Button>
            </div>
          ))}
          <Button size="sm" onClick={() => setItems((s) => [...s, { item_id: 0, qty_per_unit: 1 }])}>+ {t("svc.addItem")}</Button>
        </div>
      )}
    </Modal>
  );
}
