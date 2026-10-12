"use client";
import { AttendanceSheet } from "@/components/AttendanceSheet";
import { PageHeader } from "@/components/ui";
import { useI18n } from "@/lib/i18n";

export default function AttendancePage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("att.title")} />
      <AttendanceSheet />
    </>
  );
}
