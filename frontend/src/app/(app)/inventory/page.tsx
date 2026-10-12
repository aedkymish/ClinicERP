"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ClinicBadge, DataTable, ExportButtons, Field, Input, Modal, MoneyInput, PageHeader, Select, Tabs, useFeedback } from "@/components/ui";
import { api, openFile } from "@/lib/api";
import { useApi, useDebounced } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function InventoryPage() {
  const { t } = useI18n();
  const { clinicParam, can, fmt } = useSession();
  const [flag, setFlag] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [edit, setEdit] = useState<any | null>(null);
  const [move, setMove] = useState<any | null>(null);
  const params = { clinic: clinicParam, flag, q: dq };
  const { data, loading, reload } = useApi<any[]>("/inventory", params);
  const write = can("inventory.write");

  return (
    <>
      <PageHeader title={t("stock.title")} actions={write && <Button variant="primary" onClick={() => setEdit({})}>+ {t("stock.new")}</Button>} />
      <Tabs tabs={[{ id: "", label: t("common.all") }, { id: "low", label: t("stock.filter.low") }, { id: "expiring", label: t("stock.filter.expiring") }]} active={flag} onChange={setFlag} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-3 dark:border-slate-700">
          <Input className="max-w-xs" type="search" placeholder={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("common.search")} />
          <div className="ms-auto"><ExportButtons onExport={(f) => openFile("/inventory", { ...params, format: f })} /></div>
        </div>
        <DataTable rows={data} loading={loading} onRowClick={setMove} columns={[
          { key: "name", header: t("common.name"), render: (i: any) => <span className="font-medium">{i.name}</span> },
          { key: "clinic", header: t("common.clinic"), render: (i: any) => <ClinicBadge clinic={i.clinic} /> },
          { key: "category", header: t("common.category"), render: (i: any) => i.category ?? "—" },
          { key: "qty", header: t("stock.onHand"), align: "end", render: (i: any) => `${fmt.number(i.qty, 2)} ${i.unit}` },
          { key: "reorder_level", header: t("stock.reorder"), align: "end", render: (i: any) => fmt.number(i.reorder_level, 2) },
          { key: "expiry", header: t("stock.expiry"), render: (i: any) => (i.expiry ? fmt.date(i.expiry) : "—") },
          { key: "flags", header: t("common.status"), render: (i: any) => (
            <span className="flex flex-wrap gap-1">
              {i.low && <Badge tone="red">{t("stock.low")}</Badge>}
              {i.expired ? <Badge tone="red">{t("stock.expired")}</Badge> : i.expiring && <Badge tone="amber">{t("stock.expiring")}</Badge>}
            </span>) },
          ...(write ? [{ key: "edit", header: "", render: (i: any) => <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setEdit(i); }}>{t("common.edit")}</Button> }] : []),
        ]} />
      </Card>
      <ItemModal item={edit} onClose={() => setEdit(null)} onSaved={reload} />
      <MovementModal item={move} onClose={() => setMove(null)} onSaved={reload} />
    </>
  );
}

function ItemModal({ item, onClose, onSaved }: { item: any | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { settings, me } = useSession();
  const [v, setV] = useState<any>({});
  useEffect(() => {
    if (item) setV(item.id ? { ...item } : { clinic: me.clinic_scope === "both" ? "shared" : me.clinic_scope, name: "", category: "", unit: "pcs", reorder_level: 0, unit_cost: 0, supplier: "", expiry: "", opening_qty: 0 });
  }, [item, me.clinic_scope]);
  if (!item) return null;
  const set = (k: string, x: unknown) => setV((s: any) => ({ ...s, [k]: x }));
  const save = async () => {
    try {
      const body = { clinic: v.clinic, name: v.name, category: v.category || null, unit: v.unit, reorder_level: Number(v.reorder_level), unit_cost: v.unit_cost, supplier: v.supplier || null, expiry: v.expiry || null };
      if (item.id) await api.patch(`/inventory/${item.id}`, { ...body, version: item.version, active: v.active });
      else await api.post("/inventory", { ...body, opening_qty: Number(v.opening_qty) });
      onSaved();
      onClose();
    } catch (e) {
      fb.error(e);
    }
  };
  const clinics = me.clinic_scope === "both" ? ["shared", "dental", "derma"] : ["shared", me.clinic_scope];
  return (
    <Modal open onClose={onClose} title={item.id ? item.name : t("stock.new")} size="lg"
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button variant="primary" onClick={save}>{t("common.save")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("common.name")} required><Input value={v.name ?? ""} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label={t("common.clinic")}><Select value={v.clinic} onChange={(e) => set("clinic", e.target.value)}>{clinics.map((c) => <option key={c} value={c}>{t(`clinic.${c}`)}</option>)}</Select></Field>
        <Field label={t("common.category")}><Input value={v.category ?? ""} onChange={(e) => set("category", e.target.value)} /></Field>
        <Field label={t("stock.unit")}><Input value={v.unit ?? ""} onChange={(e) => set("unit", e.target.value)} /></Field>
        <Field label={t("stock.reorder")}><Input type="number" min={0} step="any" value={v.reorder_level ?? 0} onChange={(e) => set("reorder_level", e.target.value)} /></Field>
        <Field label={t("stock.unitCost")}><MoneyInput decimals={settings.currency_decimals} value={v.unit_cost} onChange={(x) => set("unit_cost", x)} /></Field>
        <Field label={t("stock.supplier")}><Input value={v.supplier ?? ""} onChange={(e) => set("supplier", e.target.value)} /></Field>
        <Field label={t("stock.expiry")}><Input type="date" value={v.expiry ?? ""} onChange={(e) => set("expiry", e.target.value)} /></Field>
        {!item.id && <Field label={t("stock.opening")}><Input type="number" min={0} step="any" value={v.opening_qty} onChange={(e) => set("opening_qty", e.target.value)} /></Field>}
      </div>
    </Modal>
  );
}

function MovementModal({ item, onClose, onSaved }: { item: any | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const { can, fmt } = useSession();
  const [kind, setKind] = useState("Receive");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const moves = useApi<any[]>(item ? `/inventory/${item.id}/movements` : null);
  useEffect(() => { setKind("Receive"); setQty(""); setReason(""); }, [item]);
  if (!item) return null;
  const save = async () => {
    try {
      await api.post(`/inventory/${item.id}/movements`, { kind, qty: Number(qty), reason: reason || null });
      setQty("");
      setReason("");
      moves.reload();
      onSaved();
      fb.ok(t("common.saved"));
    } catch (e) {
      fb.error(e);
    }
  };
  return (
    <Modal open onClose={onClose} title={`${item.name} · ${fmt.number(item.qty, 2)} ${item.unit}`} size="lg" footer={<Button onClick={onClose}>{t("common.close")}</Button>}>
      {can("inventory.write") && (
        <div className="mb-4 grid grid-cols-2 items-end gap-2 sm:grid-cols-4">
          <Field label={t("common.type")}>
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>{["Receive", "Use", "Adjust"].map((k) => <option key={k} value={k}>{t(`stock.kind.${k}`)}</option>)}</Select>
          </Field>
          <Field label={t("common.qty")} hint={kind === "Adjust" ? t("stock.adjustHint") : undefined}><Input type="number" step="any" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
          <Field label={t("common.reason")} required={kind === "Adjust"}><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <Button variant="primary" disabled={!qty || Number(qty) === 0 || (kind === "Adjust" && !reason.trim())} onClick={save}>{t("common.save")}</Button>
        </div>
      )}
      <h3 className="mb-1 text-sm font-semibold">{t("stock.movements")}</h3>
      <DataTable rows={moves.data} loading={moves.loading} columns={[
        { key: "local", header: t("common.date") },
        { key: "kind", header: t("common.type"), render: (m: any) => t(`stock.kind.${m.kind}`) },
        { key: "qty", header: t("common.qty"), align: "end", render: (m: any) => (m.qty > 0 ? `+${fmt.number(m.qty, 3)}` : fmt.number(m.qty, 3)) },
        { key: "reason", header: t("common.reason"), render: (m: any) => m.reason ?? "—" },
        { key: "user", header: t("common.user"), render: (m: any) => m.user ?? "—" },
      ]} />
    </Modal>
  );
}
