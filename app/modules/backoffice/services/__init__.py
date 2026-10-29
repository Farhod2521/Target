from app.modules.backoffice.services.accounts import (
    attach_old_receipts,
    delete_account,
    set_customer_password,
)
from app.modules.backoffice.services.entitlement import (
    Payment,
    add_days,
    add_slots,
    give_plan,
    set_referral,
    take_payment,
    take_slots,
)
from app.modules.backoffice.services.journal import record, seen
from app.modules.backoffice.services.pages import (
    add_page,
    change_page_account,
    move_page,
    remove_page_account,
)
from app.modules.backoffice.services.payouts import (
    pay_ask,
    payout_currencies,
    record_withdrawal,
    refuse_ask,
    void_withdrawal,
)
from app.modules.backoffice.services.promo import (
    approve_promo,
    create_code,
    delete_code,
    refuse_promo,
    update_code,
)
from app.modules.backoffice.services.support_access import (
    holds_any_role,
    may_answer_support,
    may_read_faults,
)

__all__ = [
    "Payment",
    "add_days",
    "add_page",
    "add_slots",
    "approve_promo",
    "attach_old_receipts",
    "change_page_account",
    "create_code",
    "delete_account",
    "delete_code",
    "give_plan",
    "holds_any_role",
    "may_answer_support",
    "may_read_faults",
    "move_page",
    "pay_ask",
    "payout_currencies",
    "record",
    "record_withdrawal",
    "refuse_ask",
    "refuse_promo",
    "remove_page_account",
    "seen",
    "set_customer_password",
    "set_referral",
    "take_payment",
    "take_slots",
    "update_code",
    "void_withdrawal",
]
