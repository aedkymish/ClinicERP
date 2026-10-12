"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function LoginForm() {
  const { t, lang, setLang } = useI18n();
  const router = useRouter();
  const reason = useSearchParams().get("reason");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(reason && reason !== "unauthenticated" ? t("auth.expired") : "");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const me = await api.post("/auth/login", { username, password });
      router.replace(me.must_change_pw ? "/change-password" : "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-xl font-bold text-white">C</div>
          <h1 className="text-2xl font-semibold">{t("app.name")}</h1>
          <p className="text-sm text-slate-500">{t("auth.title")}</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900">
          {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{error}</p>}
          <Field label={t("auth.username")} required>
            <Input autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </Field>
          <Field label={t("auth.password")} required>
            <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Button type="submit" variant="primary" className="w-full" loading={busy}>{t("auth.signin")}</Button>
        </form>
        <div className="mt-4 text-center">
          <button type="button" className="text-sm text-brand-700 underline dark:text-brand-100" onClick={() => setLang(lang === "ar" ? "en" : "ar")}>
            {t("lang.switch")}
          </button>
        </div>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
