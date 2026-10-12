"use client";
import { useState } from "react";
import { Badge, Card, DataTable, ExportButtons, Field, Input, PageHeader, Pagination, Select } from "@/components/ui";
import { openFile } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";

const ACTIONS = ["create", "update", "delete", "login", "login_failed", "logout", "view", "void", "refund", "override", "export", "print", "password_reset", "password_change", "unlock", "backup", "restore", "import_v1", "import_fill"];

function Changes({ before, after }: { before: any; after: any }) {
  if (!before && !after) return null;
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].filter((k) => !["created_at", "updated_at", "version"].includes(k));
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-slate-500">{keys.length} fields</summary>
      <table className="mt-1"><tbody>
        {keys.map((k) => (
          <tr key={k} className="align-top">
            <td className="pe-2 font-medium">{k}</td>
            {before && <td className="pe-2 text-red-700 line-through dark:text-red-400">{JSON.stringify(before[k] ?? null)}</td>}
            <td className="text-emerald-800 dark:text-emerald-300">{after ? JSON.stringify(after[k] ?? null) : ""}</td>
          </tr>
        ))}
      </tbody></table>
    </details>
  );
}

export default function AuditPage() {
  const { t } = useI18n();
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const params = { entity, action, from, to, page };
  const { data, loading } = useApi<any>("/audit", params);
  const f = (fn: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { fn(e.target.value); setPage(1); };

  return (
    <>
      <PageHeader title={t("audit.title")} actions={<ExportButtons onExport={(fmt) => openFile("/audit", { ...params, page: undefined, format: fmt })} />} />
      <Card padded={false}>
        <div className="grid grid-cols-2 gap-3 border-b border-slate-200 p-3 dark:border-slate-700 md:grid-cols-4">
          <Field label={t("audit.entity")}><Select value={entity} onChange={f(setEntity)}><option value="">{t("common.all")}</option>{(data?.entities ?? []).map((e: string) => <option key={e}>{e}</option>)}</Select></Field>
          <Field label={t("audit.action")}><Select value={action} onChange={f(setAction)}><option value="">{t("common.all")}</option>{ACTIONS.map((a) => <option key={a}>{a}</option>)}</Select></Field>
          <Field label={t("common.from")}><Input type="date" value={from} onChange={f(setFrom)} /></Field>
          <Field label={t("common.to")}><Input type="date" value={to} onChange={f(setTo)} /></Field>
        </div>
        <DataTable rows={data?.items} loading={loading} columns={[
          { key: "local", header: t("common.time"), className: "whitespace-nowrap tabular-nums" },
          { key: "user", header: t("common.user"), render: (a: any) => a.user ?? "—" },
          { key: "action", header: t("audit.action"), render: (a: any) => <Badge tone={["void", "refund", "override", "login_failed", "restore"].includes(a.action) ? "amber" : "gray"}>{a.action}</Badge> },
          { key: "entity", header: t("audit.entity") },
          { key: "entity_id", header: t("audit.record"), render: (a: any) => a.entity_id ?? "—" },
          { key: "changes", header: t("audit.changes"), render: (a: any) => <Changes before={a.before} after={a.after} /> },
          { key: "ip", header: t("audit.ip"), render: (a: any) => a.ip ?? "—" },
        ]} />
        {data && <Pagination page={page} total={data.total} pageSize={data.page_size} onPage={setPage} />}
      </Card>
    </>
  );
}
