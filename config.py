import json
import os
import time

# Seluruh timestamp di database disimpan sebagai waktu naive UTC (sama seperti
# versi sebelumnya di Railway). Paksa TZ=UTC supaya perilaku sama di lokal.
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
DATABASE_URL = os.environ["DATABASE_URL"]

# API credentials milik admin (1 untuk semua user)
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]

RESTRICTED_CHANNELS_RAW = os.environ.get("RESTRICTED_CHANNELS", "[]")
try:
    RESTRICTED_CHANNELS: list = json.loads(RESTRICTED_CHANNELS_RAW)
except Exception:
    RESTRICTED_CHANNELS = []

# Log channel: isi dengan ID channel log admin, atau 0 untuk nonaktif
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "0"))

# ── Opsional (baru) ───────────────────────────────────────────────────────────
# Channel tujuan auto backup (selain PM admin). Bisa juga diatur dari menu admin.
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", "0"))
# Kontak admin yang ditampilkan ke user.
ADMIN_CONTACT = os.environ.get("ADMIN_CONTACT", "@kqrbit")
BOT_NAME = os.environ.get("BOT_NAME", "RamsBot")

DEVICE_MODEL = "RamsBot VIP"
SYSTEM_VERSION = "iOS 26.4"
APP_VERSION = "11.4.1"
LANG_CODE = "id"
SYSTEM_LANG_CODE = "id-ID"
