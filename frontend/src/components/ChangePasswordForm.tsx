"use client";
import { useState } from "react";
import { Button, Field, Input, useFeedback } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function ChangePasswordForm({ onDone, forced }: { onDone: () => void; forced?: boolean }) {
  const { t } = useI18n();
  const fb = useFeedback();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw.length < 8) return setErrors({ new_password: t("auth.min") });
    if (pw !== pw2) return setErrors({ repeat: t("auth.mismatch") });
    setBusy(true);
    setErrors({});
    try {
      await api.post("/auth/change-password", { current_password: cur, new_password: pw });
      fb.ok(t("auth.changed"));
      onDone();
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) setErrors(err.fields);
      else fb.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      {forced && <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">{t("auth.mustChange")}</p>}
      <Field label={t("auth.current")} required error={errors.current_password}>
        <Input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required />
      </Field>
      <Field label={t("auth.newpw")} required error={errors.new_password} hint={t("auth.min")}>
        <Input type="password" autoComplete="new-password" minLength={8} value={pw} onChange={(e) => setPw(e.target.value)} required />
      </Field>
      <Field label={t("auth.repeat")} required error={errors.repeat}>
        <Input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required />
      </Field>
      <Button type="submit" variant="primary" loading={busy}>{t("auth.change")}</Button>
    </form>
  );
}
