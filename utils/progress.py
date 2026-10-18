import asyncio
import time

_BAR_WIDTH = 14


def _build_bar(current: int, total: int) -> str:
    pct = (current / total) if total > 0 else 0.0
    filled = int(pct * _BAR_WIDTH)
    return f"{'█' * filled}{'░' * (_BAR_WIDTH - filled)}  {pct * 100:.1f}%"


def _build_eta(current: int, total: int, elapsed: float) -> str:
    if current <= 0 or elapsed <= 0 or total <= 0:
        return ""
    speed = current / elapsed
    remaining = total - current
    eta_sec = remaining / speed if speed > 0 else 0
    speed_str = f"{speed / 1_048_576:.1f} MB/s" if speed >= 1_048_576 else (f"{speed / 1024:.0f} KB/s" if speed >= 1024 else f"{speed:.0f} B/s")
    eta_str = f"~{int(eta_sec)} dtk lagi" if eta_sec < 60 else f"~{int(eta_sec // 60)}m {int(eta_sec % 60)}s lagi"
    return f"{eta_str}  •  {speed_str}"


def _build_progress_text(label: str, current: int, total: int, start_ts: float, task_id: str | None = None) -> str:
    lines = [f"{label}...", _build_bar(current, total)]
    eta = _build_eta(current, total, time.monotonic() - start_ts)
    if eta:
        lines.append(eta)
    if task_id:
        lines.append(f"\n⛔ Ketik `.cancel #{task_id}` untuk membatalkan")
    return "\n".join(lines)


async def download_bytes_with_progress(client, media, status_msg, task_id: str, start_text: str | None = None):
    label = start_text or "⏳ Mendownload"
    start_ts = time.monotonic()
    loop = asyncio.get_running_loop()
    state = {"last_ts": 0.0, "last_pct": -1.0}
    try:
        await status_msg.edit(_build_progress_text(label, 0, 1, start_ts, task_id))
    except Exception:
        pass

    async def _dl_progress(current, total):
        now = loop.time(); pct = (current / total * 100) if total else 0.0
        if (now - state["last_ts"] < 1.0) and (pct - state["last_pct"] < 1.5):
            return
        state.update({"last_ts": now, "last_pct": pct})
        try:
            await status_msg.edit(_build_progress_text(label, current, total, start_ts, task_id))
        except Exception:
            pass

    data = await client.download_media(media, bytes, progress_callback=_dl_progress)
    try:
        await status_msg.edit(_build_progress_text("☁️ Mengupload", 0, 1, time.monotonic(), task_id))
    except Exception:
        pass
    return data


def make_upload_progress(status_msg, task_id: str):
    loop = asyncio.get_event_loop()
    state = {"last_ts": 0.0, "last_pct": -1.0}
    start_ts = time.monotonic()

    async def _up_progress(current, total):
        now = loop.time(); pct = (current / total * 100) if total else 0.0
        if (now - state["last_ts"] < 1.0) and (pct - state["last_pct"] < 1.5):
            return
        state.update({"last_ts": now, "last_pct": pct})
        try:
            await status_msg.edit(_build_progress_text("☁️ Mengupload", current, total, start_ts, task_id))
        except Exception:
            pass

    return _up_progress
