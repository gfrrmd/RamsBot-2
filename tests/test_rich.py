import sys; sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__file__), '..'))
import asyncio
import types
from unittest import mock

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:           # lingkungan tes tanpa httpx: cukup stub, jaringan selalu di-mock
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)

from utils import rich
from utils.rich import (RichError, build_plain_html, build_rich_html, button_rows, buttons_markup, call_api,
                        parse_buttons, parse_chat_ref, post_link, send_rich, strip_markers,
                        make_block, render_block, plain_block, media_list, block_summary)

# ── build_rich_html: tiap gaya
b = "Halo <b>dunia</b>\nbaris dua"
assert build_rich_html(b) == "<p>Halo <b>dunia</b><br/>baris dua</p>"
assert build_rich_html(b, style="quote") == "<blockquote>Halo <b>dunia</b><br/>baris dua</blockquote>"
assert build_rich_html("x", style="expand") == "<blockquote expandable>x</blockquote>"
assert build_rich_html("x", style="aside") == "<aside>x</aside>"
assert build_rich_html("x", style="details") == "<details><summary>Selengkapnya</summary>x</details>"
# judul: heading di gaya biasa, summary di gaya lipat (tidak dobel)
assert build_rich_html("x", title="Info <1>") == "<h2>Info &lt;1&gt;</h2><p>x</p>"
assert build_rich_html("x", style="details", title="Info") == "<details><summary>Info</summary>x</details>"
# spoiler, pemisah, footer
assert build_rich_html("x", spoiler=True) == "<p><tg-spoiler>x</tg-spoiler></p>"
assert build_rich_html("x", divider=True, footer="@ch & co") == "<p>x</p><hr/><footer>@ch &amp; co</footer>"
# media
assert build_rich_html("cap", media_kind="photo").startswith('<figure><img src="tg://photo?id=m1"/></figure>')
assert build_rich_html("cap", media_kind="video").startswith('<figure><video src="tg://video?id=m1"/></figure>')
# blok <pre> tidak diubah newline-nya dan tidak dibungkus <p>
pre = "<pre>a\nb</pre>"
assert build_rich_html(pre) == pre
# isi kosong + judul saja
assert build_rich_html("", title="T") == "<h2>T</h2>"

# ── Tombol dalam teks
A = ("Gabung", "https://t.me/abc", "primary"); B = ("Web & Co", "https://x.co/?a=1&b=2", "")
tagA = '<tg-button type="url" url="https://t.me/abc" style="primary">Gabung</tg-button>'
tagB = '<tg-button type="url" url="https://x.co/?a=1&amp;b=2">Web &amp; Co</tg-button>'
assert button_rows([A]) == f"<tg-button-row>{tagA}</tg-button-row>"
assert button_rows([A, B], cols=2, align="center") == f'<tg-button-row align="center">{tagA}{tagB}</tg-button-row>'
assert button_rows([A, B], cols=1) == f"<tg-button-row>{tagA}</tg-button-row><tg-button-row>{tagB}</tg-button-row>"
assert button_rows([A, B, A], cols=2, align="right").count("<tg-button-row") == 2 and 'align="right"' in button_rows([A], align="right")
assert 'align=' not in button_rows([A], align="left")
# di akhir isi (tanpa penanda)
assert build_rich_html("x", buttons=[A], buttons_inline=True) == f"<p>x</p><tg-button-row>{tagA}</tg-button-row>"
# sebelum pemisah dan footer
assert build_rich_html("x", buttons=[A], buttons_inline=True, divider=True, footer="f") == f"<p>x</p><tg-button-row>{tagA}</tg-button-row><hr/><footer>f</footer>"
# tombol biasa (bukan inline): tidak masuk HTML
assert build_rich_html("x", buttons=[A]) == "<p>x</p>"
# penanda di tengah: semua tombol
r = build_rich_html("atas\n{tombol}\nbawah", buttons=[A, B], buttons_inline=True, cols=2)
assert r == f"<p>atas</p><tg-button-row>{tagA}{tagB}</tg-button-row><p>bawah</p>", r
# penanda bernomor, sisanya ke akhir
r = build_rich_html("a\n{tombol:2}\nb", buttons=[A, B], buttons_inline=True)
assert r == f"<p>a</p><tg-button-row>{tagB}</tg-button-row><p>b</p><tg-button-row>{tagA}</tg-button-row>", r
# penanda di awal, di akhir, huruf besar, dan nomor di luar jangkauan (diabaikan, tombol tetap muncul di akhir)
assert build_rich_html("{TOMBOL:1}\nisi", buttons=[A], buttons_inline=True) == f"<tg-button-row>{tagA}</tg-button-row><p>isi</p>"
assert build_rich_html("isi\n{tombol:9}", buttons=[A], buttons_inline=True) == f"<p>isi</p><tg-button-row>{tagA}</tg-button-row>"
# gaya kutipan: tiap segmen teks dibungkus sendiri, tombol di luar kutipan
r = build_rich_html("a\n{tombol}\nb", style="quote", buttons=[A], buttons_inline=True)
assert r == f"<blockquote>a</blockquote><tg-button-row>{tagA}</tg-button-row><blockquote>b</blockquote>", r
# gaya lipat: tombol ikut di dalam <details>
r = build_rich_html("a\n{tombol}\nb", style="details", title="T", buttons=[A], buttons_inline=True)
assert r == f"<details><summary>T</summary>a<tg-button-row>{tagA}</tg-button-row>b</details>", r
# spoiler membungkus tiap segmen teks, bukan tombol
r = build_rich_html("a\n{tombol}", spoiler=True, buttons=[A], buttons_inline=True)
assert r == f"<p><tg-spoiler>a</tg-spoiler></p><tg-button-row>{tagA}</tg-button-row>", r
# penanda dibuang bila tombol bukan inline, atau tidak ada tombol
assert build_rich_html("a\n{tombol}\nb", buttons=[A]) == "<p>a<br/>b</p>"
assert build_rich_html("a\n{tombol:1}\nb") == "<p>a<br/>b</p>"
assert strip_markers("a\n  {tombol}  \nb\n{tombol:3}") == "a\nb\n"
# penanda di tengah kalimat bukan penanda (harus di baris sendiri)
assert "{tombol}" in build_rich_html("klik {tombol} ini", buttons=[A], buttons_inline=True)
# media + judul + tombol
r = build_rich_html("cap", media_kind="photo", title="J", buttons=[A], buttons_inline=True)
assert r == f'<figure><img src="tg://photo?id=m1"/></figure><h2>J</h2><p>cap</p><tg-button-row>{tagA}</tg-button-row>', r
# hanya tombol tanpa isi teks
assert build_rich_html("", buttons=[A], buttons_inline=True) == f"<tg-button-row>{tagA}</tg-button-row>"

# ── Blok tambahan: make_block (validasi) dan render_block (HTML)
def mk(t, opt, text, loc=None):
    b, e = make_block(t, opt, text, loc); return b, e

b, e = mk("heading", "2", "Judul Bagian"); assert render_block(b) == "<h2>Judul Bagian</h2>"
assert mk("heading", "2", "")[1] and mk("heading", "2", "x" * 151)[1]
b, e = mk("list", "ul", "- satu\n* dua\n• tiga\n\n4) empat"); assert [i[0] for i in b["items"]] == ["satu", "dua", "tiga", "empat"]
assert render_block(b) == "<ul><li>satu</li><li>dua</li><li>tiga</li><li>empat</li></ul>"
b, e = mk("list", "ol", "a\nb"); assert render_block(b) == "<ol><li>a</li><li>b</li></ol>"
b, e = mk("list", "chk", "[x] selesai\n[ ] belum\ntanpa tanda"); assert [i[1] for i in b["items"]] == [True, False, False]
assert render_block(b) == "<ul><li>☑ selesai</li><li>☐ belum</li><li>☐ tanpa tanda</li></ul>"
assert mk("list", "ul", "  \n ")[1] and mk("list", "ul", "\n".join("x" * 3 for _ in range(31)))[1]
b, e = mk("list", "ul", "<b>&"); assert render_block(b) == "<ul><li>&lt;b&gt;&amp;</li></ul>"   # input user di-escape
b, e = mk("table", None, "Paket | Harga\nMingguan | 20rb\n| Bulanan | 50rb |")
assert b["rows"] == [["Paket", "Harga"], ["Mingguan", "20rb"], ["Bulanan", "50rb"]]
assert render_block(b) == ("<table bordered striped><tr><th>Paket</th><th>Harga</th></tr><tr><td>Mingguan</td><td>20rb</td></tr>"
                           "<tr><td>Bulanan</td><td>50rb</td></tr></table>")
b, e = mk("table", None, "a | b | c\n1 | 2"); assert b["rows"][1] == ["1", "2", ""]       # baris pendek dilengkapi
assert mk("table", None, "hanya satu baris")[1] and mk("table", None, "a\nb")[1] and mk("table", None, "a|b|c|d|e|f|g|h|i\n1|2|3|4|5|6|7|8|9")[1]
b, e = mk("code", "python", "print('<hai>')\nx = 1")
assert render_block(b) == '<pre><code class="language-python">print(\'&lt;hai&gt;\')\nx = 1</code></pre>'.replace("\\'", "'")
b, e = mk("code", "-", "ls -la"); assert render_block(b) == "<pre><code>ls -la</code></pre>"
assert mk("code", "json", "")[1] and mk("code", "json", "x" * 3001)[1]
b, e = mk("quote", None, "Belajar terus | Budi"); assert b == {"t": "quote", "text": "Belajar terus", "credit": "Budi"}
assert render_block(b) == "<blockquote>Belajar terus<cite>Budi</cite></blockquote>"
b, e = mk("pull", None, "Tanpa sumber"); assert render_block(b) == "<aside>Tanpa sumber</aside>"
assert mk("quote", None, " | Budi")[1]
b, e = mk("fold", None, "Syarat\nMinimal 18\nBawa KTP")
assert render_block(b) == "<details><summary>Syarat</summary><p>Minimal 18<br/>Bawa KTP</p></details>"
assert mk("fold", None, "Judul saja")[1]
b, e = mk("math", None, "E = mc^2 < 5"); assert render_block(b) == "<tg-math-block>E = mc^2 &lt; 5</tg-math-block>"
b, e = mk("map", None, "-6.2088, 106.8456"); assert render_block(b) == '<tg-map lat="-6.2088" long="106.8456" zoom="14"/>'
b, e = mk("map", None, "", (1.5, 2.5)); assert (b["lat"], b["lon"]) == (1.5, 2.5)
assert mk("map", None, "bukan koordinat")[1] and mk("map", None, "95, 10")[1] and mk("map", None, "10, 190")[1]
b = {"t": "gallery", "kind": "collage", "files": ["F1", "F2"]}
assert render_block(b, 3) == '<tg-collage><img src="tg://photo?id=g3x0"/><img src="tg://photo?id=g3x1"/></tg-collage>'
assert render_block({**b, "kind": "slideshow"}, 0).startswith("<tg-slideshow>")
assert render_block({"t": "divider"}) == "<hr/>"
assert mk("zzz", None, "x")[1]

# media_list: utama + galeri
assert media_list(None, None, []) == []
assert media_list("video", "V", [{"t": "divider"}, b]) == [
    {"id": "m1", "media": {"type": "video", "media": "V"}},
    {"id": "g1x0", "media": {"type": "photo", "media": "F1"}}, {"id": "g1x1", "media": {"type": "photo", "media": "F2"}}]

# blok di builder: urutan = isi, blok, pemisah, footer
H = {"t": "heading", "size": 3, "text": "Bagian"}; L = mk("list", "ul", "a\nb")[0]
r = build_rich_html("isi", blocks=[H, L], divider=True, footer="f")
assert r == "<p>isi</p><h3>Bagian</h3><ul><li>a</li><li>b</li></ul><hr/><footer>f</footer>", r
# blok "Tombol" menentukan posisi tombol (tidak dobel di akhir)
r = build_rich_html("isi", buttons=[A], buttons_inline=True, blocks=[H, {"t": "btns"}, L])
assert r == f"<p>isi</p><h3>Bagian</h3><tg-button-row>{tagA}</tg-button-row><ul><li>a</li><li>b</li></ul>", r
# blok "Tombol" diabaikan bila tombol bukan inline
assert "tg-button" not in build_rich_html("isi", buttons=[A], blocks=[{"t": "btns"}])
# ukuran judul, ==sorot==, spoiler media
assert build_rich_html("x", title="J", title_size=4) == "<h4>J</h4><p>x</p>"
assert build_rich_html("pakai ==sorot== ini") == "<p>pakai <mark>sorot</mark> ini</p>"
assert build_rich_html("a == b == c") == "<p>a == b == c</p>"
assert 'tg-spoiler/>' in build_rich_html("c", media_kind="photo", spoiler=True)
# ringkasan + versi pesan biasa
assert block_summary(L) == "📋 Daftar: 2 item" and block_summary({"t": "divider"}) == "➖ Pemisah"
assert plain_block(L) == "• a\n• b" and plain_block(mk("list", "ol", "a\nb")[0]) == "1. a\n2. b"
assert plain_block(mk("table", None, "A | B\nxx | y")[0]) == "<pre>A  | B\n------\nxx | y</pre>"
assert plain_block(mk("quote", None, "q | s")[0]) == "<blockquote>q\n— s</blockquote>"
assert "google.com/maps?q=1.5,2.5" in plain_block({"t": "map", "lat": 1.5, "lon": 2.5, "zoom": 14})
assert plain_block({"t": "gallery", "kind": "collage", "files": ["a", "b"]}) == ""
assert build_plain_html("isi", blocks=[H, L], footer="f") == "isi\n\n<b>Bagian</b>\n\n• a\n• b\n\n<i>f</i>"

# ── build_plain_html (cadangan)
assert build_plain_html("x") == "x"
assert build_plain_html("x", style="quote", title="T", footer="f") == "<b>T</b>\n\n<blockquote>x</blockquote>\n\n<i>f</i>"
assert build_plain_html("x", style="details") == "<blockquote>x</blockquote>"
assert build_plain_html("x", style="expand") == "<blockquote expandable>x</blockquote>"
assert build_plain_html("x", spoiler=True) == "<tg-spoiler>x</tg-spoiler>"
assert build_plain_html("a\n{tombol}\nb") == "a\nb"

# ── parse_buttons
ok, err = parse_buttons("Gabung | https://t.me/abc\nWeb|http://x.co\nApp | tg://resolve?domain=abc")
assert len(ok) == 3 and not err and ok[0] == ("Gabung", "https://t.me/abc", "")
ok, err = parse_buttons("tanpa pemisah")
assert not ok and len(err) == 1
# warna tombol
ok, err = parse_buttons("A | https://x.co | hijau\nB | https://x.co | MERAH\nC | https://x.co | biru\nD | https://x.co | polos\nE | https://x.co | danger")
assert [b[2] for b in ok] == ["success", "danger", "primary", "", "danger"] and not err
ok, err = parse_buttons("A | https://x.co | ungu"); assert not ok and "warna" in err[0]
ok, err = parse_buttons("A | https://x.co | biru | lagi"); assert not ok and err
ok, err = parse_buttons("A | ftp://x")
assert not ok and "link" in err[0]
ok, err = parse_buttons(" | https://x.co")
assert not ok and err
ok, err = parse_buttons("\n".join(f"b{i} | https://x.co/{i}" for i in range(12)))
assert len(ok) == 8 and any("Maksimal" in e for e in err)
assert buttons_markup([]) is None
assert buttons_markup([("A", "https://x.co", "success")]) == {"inline_keyboard": [[{"text": "A", "url": "https://x.co", "style": "success"}]]}
assert buttons_markup([("A", "https://x.co")]) == {"inline_keyboard": [[{"text": "A", "url": "https://x.co"}]]}

# ── parse_chat_ref & post_link
assert parse_chat_ref("-1001234567890") == -1001234567890
assert parse_chat_ref("@namachannel") == "@namachannel"
assert parse_chat_ref("https://t.me/namachannel") == "@namachannel"
assert parse_chat_ref("t.me/namachannel/45") == "@namachannel"
assert parse_chat_ref("https://t.me/c/1234567890/55") == -1001234567890
assert parse_chat_ref("https://t.me/+AbCdEf") is None          # invite link tidak bisa di-resolve
assert parse_chat_ref("halo") is None and parse_chat_ref("") is None and parse_chat_ref(None) is None
assert post_link(-1001234567890, "abc", 9) == "https://t.me/abc/9"
assert post_link(-1001234567890, None, 9) == "https://t.me/c/1234567890/9"
assert post_link(123, None, 9) is None


# ── call_api / send_rich dengan httpx di-mock
class FakeResp:
    def __init__(self, status, body): self.status_code, self._b = status, body
    def json(self):
        if self._b is None: raise ValueError("bukan json")
        return self._b


class FakeClient:
    calls = []
    queue = []
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None):
        FakeClient.calls.append((url, json)); return FakeClient.queue.pop(0)


def run(coro): return asyncio.run(coro)


with mock.patch.object(rich.httpx, "AsyncClient", FakeClient), mock.patch.object(rich.asyncio, "sleep", mock.AsyncMock()):
    # sukses + bentuk payload
    FakeClient.calls, FakeClient.queue = [], [FakeResp(200, {"ok": True, "result": {"message_id": 7}})]
    r = run(send_rich("TOKEN", -100123, "<p>x</p>", media=media_list("photo", "FID", []),
                      buttons=[("A", "https://x.co")], silent=True, protect=True))
    assert r == {"message_id": 7}
    url, payload = FakeClient.calls[0]
    assert url == "https://api.telegram.org/botTOKEN/sendRichMessage"
    assert payload["chat_id"] == -100123 and payload["rich_message"]["html"] == "<p>x</p>"
    assert payload["rich_message"]["media"] == [{"id": "m1", "media": {"type": "photo", "media": "FID"}}]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://x.co"
    assert payload["disable_notification"] is True and payload["protect_content"] is True
    # tanpa opsi: kunci opsional tidak ikut
    FakeClient.calls, FakeClient.queue = [], [FakeResp(200, {"ok": True, "result": {"message_id": 1}})]
    run(send_rich("T", 1, "<p>x</p>"))
    p = FakeClient.calls[0][1]
    assert "reply_markup" not in p and "disable_notification" not in p and "media" not in p["rich_message"]
    # error Telegram -> RichError membawa deskripsi asli
    FakeClient.queue = [FakeResp(400, {"ok": False, "error_code": 400, "description": "Bad Request: method not found"})]
    try: run(call_api("T", "sendRichMessage", {})); raise SystemExit("harus gagal")
    except RichError as e: assert "method not found" in e.description and e.code == 400
    # 429 -> retry sekali lalu sukses
    FakeClient.calls, FakeClient.queue = [], [FakeResp(429, {"ok": False, "description": "Too Many", "parameters": {"retry_after": 2}}),
                                              FakeResp(200, {"ok": True, "result": {"message_id": 3}})]
    assert run(call_api("T", "m", {}))["message_id"] == 3 and len(FakeClient.calls) == 2
    # 429 berulang -> menyerah
    FakeClient.queue = [FakeResp(429, {"ok": False, "description": "x", "parameters": {"retry_after": 1}})] * 2
    try: run(call_api("T", "m", {})); raise SystemExit("harus gagal")
    except RichError as e: assert e.code == 429
    # respons bukan JSON
    FakeClient.queue = [FakeResp(502, None)]
    try: run(call_api("T", "m", {})); raise SystemExit("harus gagal")
    except RichError as e: assert "502" in e.description
    # terlalu panjang: ditolak tanpa memanggil API
    FakeClient.calls = []
    try: run(send_rich("T", 1, "x" * (rich.MAX_RICH_CHARS + 1))); raise SystemExit("harus gagal")
    except RichError as e: assert "terlalu panjang" in e.description and not FakeClient.calls

print("test_rich: semua lolos")
