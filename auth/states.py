PHONE_STEP, CODE_STEP, PASSWORD_STEP = range(3)

temp_store: dict[int, dict] = {}
waiting_restore: set[int] = set()
waiting_gift: set[int] = set()
waiting_revoke: set[int] = set()

# ── State baru (v2) ───────────────────────────────────────────────────────────
# User: sedang diminta mengirim gambar QRIS statis / bukti bayar.
waiting_qris_upload: set[int] = set()
waiting_payment_proof: dict[int, int] = {}      # user_id -> order_id
# Admin: 1 state aktif sekaligus. {"action": str, ...konteks}
admin_state: dict[int, dict] = {}


def clear_input_waits(uid: int):
    """Bersihkan state input user (upload QRIS / bukti bayar)."""
    waiting_qris_upload.discard(uid)
    waiting_payment_proof.pop(uid, None)


def clear_user_state(uid: int):
    temp_store.pop(uid, None)
    waiting_restore.discard(uid)
    waiting_gift.discard(uid)
    waiting_revoke.discard(uid)
    clear_input_waits(uid)
    admin_state.pop(uid, None)
    try:
        from admin.callbacks import waiting_bl_add, waiting_bl_remove
        waiting_bl_add.discard(uid)
        waiting_bl_remove.discard(uid)
    except Exception:
        pass
