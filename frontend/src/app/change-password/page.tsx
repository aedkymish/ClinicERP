"use client";
import { useRouter } from "next/navigation";
import { ChangePasswordForm } from "@/components/ChangePasswordForm";
import { useI18n } from "@/lib/i18n";

export default function ChangePasswordPage() {
  const { t } = useI18n();
  const router = useRouter();
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <h1 className="mb-4 text-lg font-semibold">{t("auth.change")}</h1>
        <ChangePasswordForm forced onDone={() => router.replace("/")} />
      </div>
    </main>
  );
}
