"""Role permission matrix — SRS section 2.2. The API is the single place these are enforced."""

ALL = frozenset({"admin", "doctor", "nurse", "assistant", "receptionist", "finance"})
CLINICAL = frozenset({"admin", "doctor", "nurse", "assistant"})

PERMS: dict[str, frozenset[str]] = {
    "patients.read": ALL,
    "patients.write": frozenset({"admin", "doctor", "nurse", "assistant", "receptionist"}),
    "patients.archive": frozenset({"admin"}),
    "appointments.read": frozenset({"admin", "doctor", "nurse", "assistant", "receptionist"}),
    "appointments.write": frozenset({"admin", "doctor", "nurse", "assistant", "receptionist"}),
    "appointments.override": frozenset({"admin"}),
    "visits.read": CLINICAL,
    "visits.write": frozenset({"admin", "doctor", "nurse"}),
    "chart.read": CLINICAL,
    "chart.write": frozenset({"admin", "doctor", "nurse"}),
    # doctors may read billing but only their own invoices (enforced in the router)
    "billing.read": frozenset({"admin", "doctor", "receptionist", "finance"}),
    "billing.create": frozenset({"admin", "receptionist", "finance"}),
    "billing.pay": frozenset({"admin", "receptionist", "finance"}),
    "billing.override": frozenset({"admin", "finance"}),
    "billing.void": frozenset({"admin", "finance"}),
    "services.read": ALL,
    "services.write": frozenset({"admin"}),
    "services.price": frozenset({"admin", "finance"}),
    "inventory.read": frozenset({"admin", "doctor", "nurse", "assistant", "finance"}),
    "inventory.write": frozenset({"admin", "nurse", "assistant"}),
    "expenses": frozenset({"admin", "finance"}),
    "staff.read_all": frozenset({"admin", "finance"}),
    "staff.write": frozenset({"admin"}),
    "staff.salary": frozenset({"admin", "finance"}),
    "users": frozenset({"admin"}),
    "attendance.manage": frozenset({"admin", "finance"}),
    "payroll.manage": frozenset({"admin", "finance"}),
    "payroll.approve": frozenset({"admin"}),
    "reports.full": frozenset({"admin", "finance"}),
    "reports.commission_own": frozenset({"doctor"}),
    "reports.cash": frozenset({"admin", "finance", "receptionist"}),
    "audit": frozenset({"admin", "finance"}),
    "settings": frozenset({"admin"}),
}


def can(role: str, perm: str) -> bool:
    return role in PERMS[perm]


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMS.items() if role in roles)
