import flet as ft
import flet.canvas as cv
import asyncio
import math
import flet_ads as fta
import flet_audio as fta_audio
import json
import datetime
import random
import calendar
import os
import re
import hashlib
import time
from fpdf import FPDF
try:
    from bank_notification_parser import parse as parse_bank_notification
    PARSER_LOAD_ERROR = None
except Exception as _parser_ex:  # missing file, or an error inside it
    parse_bank_notification = None
    PARSER_LOAD_ERROR = f"{type(_parser_ex).__name__}: {_parser_ex}"

NOTIF_PACKAGE_NAME = "com.linton.naira_finance_hub"

# ---------------------------------------------------------------------------
# Local time on Android: embedded Python often can't see the phone's time zone and
# silently runs on UTC (1 hour behind Lagos, so times were wrong and "today" changed at
# 1 AM instead of midnight). Read the phone's zone and apply it.
# ---------------------------------------------------------------------------
_POSIX_TZ = {
    "Africa/Lagos": "WAT-1", "Africa/Douala": "WAT-1", "Africa/Kinshasa": "WAT-1", "Africa/Luanda": "WAT-1",
    "Africa/Porto-Novo": "WAT-1", "Africa/Niamey": "WAT-1", "Africa/Ndjamena": "WAT-1", "Africa/Algiers": "CET-1",
    "Africa/Tunis": "CET-1", "Africa/Accra": "GMT0", "Africa/Abidjan": "GMT0", "Africa/Dakar": "GMT0",
    "Africa/Monrovia": "GMT0", "Africa/Freetown": "GMT0", "Africa/Banjul": "GMT0", "Africa/Lome": "GMT0",
    "Africa/Casablanca": "<+01>-1", "Africa/Cairo": "EET-2EEST,M4.5.5/0,M10.5.4/24",
    "Africa/Johannesburg": "SAST-2", "Africa/Harare": "CAT-2", "Africa/Lusaka": "CAT-2", "Africa/Kigali": "CAT-2",
    "Africa/Nairobi": "EAT-3", "Africa/Addis_Ababa": "EAT-3", "Africa/Kampala": "EAT-3", "Africa/Dar_es_Salaam": "EAT-3",
    "Europe/London": "GMT0BST,M3.5.0/1,M10.5.0", "Europe/Dublin": "IST-1GMT0,M10.5.0,M3.5.0/1",
    "Europe/Paris": "CET-1CEST,M3.5.0,M10.5.0/3", "Europe/Berlin": "CET-1CEST,M3.5.0,M10.5.0/3",
    "Europe/Amsterdam": "CET-1CEST,M3.5.0,M10.5.0/3", "Europe/Madrid": "CET-1CEST,M3.5.0,M10.5.0/3",
    "Europe/Rome": "CET-1CEST,M3.5.0,M10.5.0/3", "Asia/Dubai": "<+04>-4",
    "America/New_York": "EST5EDT,M3.2.0,M11.1.0", "America/Chicago": "CST6CDT,M3.2.0,M11.1.0",
    "America/Denver": "MST7MDT,M3.2.0,M11.1.0", "America/Los_Angeles": "PST8PDT,M3.2.0,M11.1.0",
    "America/Toronto": "EST5EDT,M3.2.0,M11.1.0", "UTC": "UTC0", "Etc/UTC": "UTC0",
}


def _fix_local_timezone():
    try:
        if os.getenv("FLET_PLATFORM", "").lower() != "android" or os.getenv("TZ") or time.timezone != 0:
            return
        import subprocess
        zone = subprocess.run(["getprop", "persist.sys.timezone"], capture_output=True,
                              text=True, timeout=2).stdout.strip()
        posix = _POSIX_TZ.get(zone)
        if posix is None:
            return  # unknown zone: leave it rather than guess wrong
        os.environ["TZ"] = posix
        time.tzset()
    except Exception:
        pass


_fix_local_timezone()


def fmt_txn_when(t):
    """'30 Oct, 2:15 PM' for entries with a time, '30 Oct' otherwise (year shown if not this year)."""
    try:
        d = datetime.date.fromisoformat(t.get("date", ""))
    except Exception:
        return t.get("date", "")
    label = d.strftime("%d %b").lstrip("0") + ("" if d.year == datetime.date.today().year else d.strftime(" %Y"))
    hm = t.get("time")
    if hm:
        try:
            hh, mm = (int(x) for x in hm.split(":")[:2])
            label += f", {hh % 12 or 12}:{mm:02d} {'AM' if hh < 12 else 'PM'}"
        except Exception:
            pass
    return label


# ---------------------------------------------------------------------------
# Speed fix for Flet 0.83: when a screen is redrawn, Flet compares every removed control
# with every added one (n x n). With a few hundred rows that took seconds on a phone and
# made the app look frozen. Same logic, using fast set lookups instead.
# ---------------------------------------------------------------------------
def _install_fast_patch():
    try:
        from flet.messaging.session import Session
        from flet.messaging.protocol import ClientAction, ClientMessage, PatchControlBody
    except Exception:
        return
    if getattr(Session, "_nfh_fast_patch", False) or not hasattr(Session, "_Session__get_update_control_patch"):
        return

    def patch_control(self, control, prev_control=None, parent=None, path=None, frozen=False):
        patch, added_controls, removed_controls = self._Session__get_update_control_patch(
            control=control, prev_control=prev_control or control,
            parent=parent, path=path, frozen=frozen)
        index = self._Session__index
        added_ids = {c._i for c in added_controls}
        removed_ids = {c._i for c in removed_controls}
        for removed_control in removed_controls:
            if removed_control._i not in added_ids:
                removed_control.will_unmount()
            index.pop(removed_control._i, None)
        if len(patch) > 1:
            self._Session__send_message(
                ClientMessage(ClientAction.PATCH_CONTROL,
                              PatchControlBody(parent._i if parent else control._i, patch)))
        for added_control in added_controls:
            index[added_control._i] = added_control
            if added_control._i not in removed_ids:
                added_control.did_mount()

    Session.patch_control = patch_control
    Session._nfh_fast_patch = True


_install_fast_patch()


# ---------------------------------------------------------------------------
# Vibrate on tap: every button/card tap the phone sends to Python passes through
# Session.dispatch_event. We wrap it once so the app can give a short buzz on each
# tap (when "Vibrate on tap" is switched on in the Menu) without touching every button.
# ---------------------------------------------------------------------------
_TAP_HOOK = {"fn": None}
_TAP_EVENTS = {"click", "tap", "long_press"}

# Motion sensor flood guard. Some phones (e.g. Xiaomi/Redmi) ignore the requested sensor
# speed and send 100+ tilt readings a second. Flet redraws the WHOLE page after every event,
# so the readings piled up and a tap on Menu could wait a minute behind them. Readings that
# arrive too soon after the last one (or while Motion effects is off) are now thrown away
# before Flet touches them.
_SENSOR_GATE = {"on": False, "last": 0.0, "min_gap": 0.15}


def _install_tap_hook():
    try:
        from flet.messaging.session import Session
    except Exception:
        return
    if getattr(Session, "_nfh_tap_hook", False) or not hasattr(Session, "dispatch_event"):
        return
    original_dispatch = Session.dispatch_event

    async def dispatch_event(self, control_id, event_name, event_data, *args, **kwargs):
        if event_name == "reading":
            if not _SENSOR_GATE["on"]:
                return
            now = time.monotonic()
            if now - _SENSOR_GATE["last"] < _SENSOR_GATE["min_gap"]:
                return
            _SENSOR_GATE["last"] = now
        elif event_name in _TAP_EVENTS:
            fn = _TAP_HOOK["fn"]
            if fn is not None:
                try:
                    fn()
                except Exception:
                    pass
        return await original_dispatch(self, control_id, event_name, event_data, *args, **kwargs)

    Session.dispatch_event = dispatch_event
    Session._nfh_tap_hook = True


_install_tap_hook()


# ---------------------------------------------------------------------------
# Real phone vibration. Flutter's "haptic feedback" is silent on many low-end phones
# (and whenever the phone's own "Touch vibration" setting is off), so on Android we call
# the phone's vibrator directly. Needs pyjnius + the VIBRATE permission (pyproject.toml).
# Returns False when that isn't possible, and the app then falls back to haptic feedback.
# ---------------------------------------------------------------------------
_NATIVE_VIBE = {"tried": False, "vibrator": None, "effect": None}


def native_vibrate(ms=35):
    st = _NATIVE_VIBE
    if not st["tried"]:
        st["tried"] = True
        try:
            from jnius import autoclass, cast
            host = os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME")
            if not host:
                return False
            activity = autoclass(host).mActivity
            Context = autoclass("android.content.Context")
            vib = cast("android.os.Vibrator", activity.getSystemService(Context.VIBRATOR_SERVICE))
            if vib is None or not vib.hasVibrator():
                return False
            try:
                VibrationEffect = autoclass("android.os.VibrationEffect")
                st["effect"] = VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE)
            except Exception:
                st["effect"] = None  # Android 7 and older
            st["vibrator"] = vib
        except Exception:
            return False
    vib = st["vibrator"]
    if vib is None:
        return False
    try:
        if st["effect"] is not None:
            vib.vibrate(st["effect"])
        else:
            vib.vibrate(ms)
        return True
    except Exception:
        st["vibrator"] = None  # e.g. permission missing: stop trying, use the fallback
        return False


# ---------------------------------------------------------------------------
# Phone notifications (Android, through pyjnius). Used for to-do reminders. They can be
# posted while the app is open or still running in the background; Android needs the
# POST_NOTIFICATIONS permission (pyproject.toml) and, on Android 13+, the user's OK.
# ---------------------------------------------------------------------------
_NOTIFY_CHANNEL = "todo_reminders"
_NOTIFY = {"ready": None}


def _android_activity():
    from jnius import autoclass
    host = os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME")
    if not host:
        return None
    return autoclass(host).mActivity


def current_package_name():
    """The installed app's package: the Play version, or the side-by-side personal build
    (com.linton.naira_finance_hub.personal). Falls back to the Play package off-device."""
    try:
        activity = _android_activity()
        if activity is not None:
            return str(activity.getPackageName())
    except Exception:
        pass
    return NOTIF_PACKAGE_NAME


def is_personal_build():
    return current_package_name().endswith(".personal")


def request_notify_permission():
    """Ask once for permission to show notifications (Android 13 and newer)."""
    try:
        from jnius import autoclass
        activity = _android_activity()
        if activity is None:
            return False
        if autoclass("android.os.Build$VERSION").SDK_INT < 33:
            return True
        perm = "android.permission.POST_NOTIFICATIONS"
        if activity.checkSelfPermission(perm) == 0:  # PackageManager.PERMISSION_GRANTED
            return True
        activity.requestPermissions([perm], 4711)
        return False
    except Exception:
        return False


def native_notify(title, text, notif_id=1):
    """Show a notification in the phone's notification shade. Returns True when shown."""
    try:
        from jnius import autoclass, cast
        activity = _android_activity()
        if activity is None:
            return False
        Context = autoclass("android.content.Context")
        sdk = autoclass("android.os.Build$VERSION").SDK_INT
        manager = cast("android.app.NotificationManager", activity.getSystemService(Context.NOTIFICATION_SERVICE))
        Builder = autoclass("android.app.Notification$Builder")
        if sdk >= 26:
            if not _NOTIFY["ready"]:
                NotificationChannel = autoclass("android.app.NotificationChannel")
                NotificationManager = autoclass("android.app.NotificationManager")
                channel = NotificationChannel(_NOTIFY_CHANNEL, "To-do reminders", NotificationManager.IMPORTANCE_HIGH)
                channel.setDescription("Reminders for items on your month-end to-do list")
                manager.createNotificationChannel(channel)
                _NOTIFY["ready"] = True
            builder = Builder(activity, _NOTIFY_CHANNEL)
        else:
            builder = Builder(activity)
            builder.setPriority(1)  # PRIORITY_HIGH
            builder.setDefaults(-1)  # sound + vibration + light
        PendingIntent = autoclass("android.app.PendingIntent")
        launch = activity.getPackageManager().getLaunchIntentForPackage(activity.getPackageName())
        flags = PendingIntent.FLAG_UPDATE_CURRENT | (PendingIntent.FLAG_IMMUTABLE if sdk >= 23 else 0)
        content_intent = PendingIntent.getActivity(activity, int(notif_id) % 100000, launch, flags)
        BigText = autoclass("android.app.Notification$BigTextStyle")
        builder.setSmallIcon(activity.getApplicationInfo().icon)
        builder.setContentTitle(str(title))
        builder.setContentText(str(text))
        builder.setStyle(BigText().bigText(str(text)))
        builder.setContentIntent(content_intent)
        builder.setAutoCancel(True)
        manager.notify(int(notif_id) % 100000, builder.build())
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Faster start-up: every saved setting used to be fetched from the phone one at a time
# (dozens of round trips before the first screen). Now they are all fetched together once,
# kept in memory, and saves update both the memory copy and the phone.
# ---------------------------------------------------------------------------
class _PrefsCache:
    _LAZY_PREFIXES = ("money_transactions_",)  # big lists: fetched only when needed

    def __init__(self, real):
        self.real = real
        self.cache = {}
        self.known_keys = set()
        self.loaded = False

    async def preload(self):
        try:
            keys = await asyncio.wait_for(self.real.get_keys(""), timeout=8)
            keys = [k for k in (keys or []) if not k.startswith(self._LAZY_PREFIXES)]
            values = await asyncio.wait_for(
                asyncio.gather(*(self.real.get(k) for k in keys), return_exceptions=True), timeout=15)
            for k, v in zip(keys, values):
                if not isinstance(v, BaseException):
                    self.cache[k] = v
            self.known_keys = set(keys)
            self.loaded = True
        except Exception:
            self.loaded = False

    async def get(self, key):
        if key in self.cache:
            return self.cache[key]
        value = await self.real.get(key)
        self.cache[key] = value
        return value

    async def set(self, key, value):
        self.cache[key] = value
        return await self.real.set(key, value)

    async def remove(self, key):
        self.cache[key] = None
        return await self.real.remove(key)

    async def clear(self):
        self.cache.clear()
        self.loaded = False
        return await self.real.clear()

    def __getattr__(self, name):
        return getattr(self.real, name)

# ---------------------------------------------------------------------------
# Branded data files: backups and shared Ajo groups are saved as a PNG picture
# (app logo + label) with the real data tucked inside a private PNG chunk, so the
# file shows the app's logo in Files / WhatsApp / Gallery. Old .json files still load.
# ---------------------------------------------------------------------------
import struct
import zlib

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_DATA_CHUNK = b"nfHd"  # private, ancillary chunk: image viewers ignore it


def _asset_path(name):
    bases = [os.getenv("FLET_ASSETS_DIR"),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"),
             "assets"]
    for base in bases:
        if base and os.path.exists(os.path.join(base, name)):
            return os.path.join(base, name)
    return None


def make_branded_file(card_name, data_bytes):
    """Returns (bytes, extension). Falls back to plain JSON if the card picture is missing."""
    path = _asset_path(card_name)
    try:
        with open(path, "rb") as f:
            card = f.read()
        if not card.startswith(_PNG_SIG):
            raise ValueError("not a PNG")
        payload = zlib.compress(data_bytes, 9)
        chunk = struct.pack(">I", len(payload)) + _DATA_CHUNK + payload + \
            struct.pack(">I", zlib.crc32(_DATA_CHUNK + payload) & 0xFFFFFFFF)
        iend = card.rindex(b"IEND") - 4  # insert just before the IEND chunk
        return card[:iend] + chunk + card[iend:], "png"
    except Exception:
        return data_bytes, "json"


def read_branded_file(raw):
    """Returns the data bytes from a branded PNG or a plain JSON file.
    Raises ValueError("photo") if it's a picture whose data was stripped (e.g. sent as a WhatsApp photo)."""
    if not raw.startswith(_PNG_SIG):
        return raw
    pos = 8
    while pos + 8 <= len(raw):
        length = struct.unpack(">I", raw[pos:pos + 4])[0]
        ctype = raw[pos + 4:pos + 8]
        if ctype == _DATA_CHUNK:
            return zlib.decompress(raw[pos + 8:pos + 8 + length])
        if ctype == b"IEND":
            break
        pos += 12 + length
    raise ValueError("photo")


def make_pdf():
    """Returns (pdf, font_name). Uses the bundled DejaVu font so names/notes with ₦, ’, —, Ọ, Ẹ etc.
    print correctly; falls back to Helvetica if the font files are missing."""
    pdf = FPDF()
    regular, bold = _asset_path("DejaVuSans.ttf"), _asset_path("DejaVuSans-Bold.ttf")
    if regular and bold:
        try:
            pdf.add_font("NFH", "", regular)
            pdf.add_font("NFH", "B", bold)
            pdf.add_font("NFH", "I", regular)
            pdf.add_font("NFH", "BI", bold)
            return pdf, "NFH"
        except Exception:
            pdf = FPDF()
    return pdf, "Helvetica"


def pdf_text(text, font):
    """Makes any user text safe for the PDF font (drops emoji; Helvetica only knows Latin-1)."""
    if not text:
        return ""
    text = "".join(ch for ch in str(text) if ord(ch) <= 0xFFFF and not (0xFE00 <= ord(ch) <= 0xFE0F) and ch != "\u200d")
    if font == "Helvetica":
        text = text.replace("₦", "NGN ").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
        text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


def picked_to_date(picked):
    """DatePicker gives the chosen day as local midnight converted to UTC (e.g. 23:00 the day
    before in Lagos). Adding 12 h lands mid-day of the chosen date in every time zone."""
    if isinstance(picked, datetime.datetime):
        return (picked + datetime.timedelta(hours=12)).date()
    return picked


def to_number(text, required=False):
    """'250,000' / '₦250000' / ' 250000 ' -> 250000.0. Empty -> 0 (or ValueError if required)."""
    cleaned = re.sub(r"[,\s₦]", "", str(text or ""))
    cleaned = re.sub(r"^(?i:NGN|N)", "", cleaned)
    if not cleaned:
        if required:
            raise ValueError("empty")
        return 0.0
    value = float(cleaned)
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ValueError("bad number")
    return value


# Nigerian bank transfer (NIP) fees, VAT included: ₦10 / ₦25 / ₦50 + 7.5% VAT.
_NIP_FEE_BANDS = ((5_000.0, 10.75), (50_000.0, 26.88), (float("inf"), 53.75))
_TRANSFER_WORDS = ("TRF", "TRANSFER", "MOB/", "NIP", "FT/", "NEFT", "USSD", "MOBILE", "TO ")


def split_transfer_fee(amount, text):
    """A transfer alert often shows price + fee as one debit, e.g. ₦6,026.88 = ₦6,000 + ₦26.88.
    Splits it only when it is clearly a transfer AND the leftover is exactly the official fee
    for that amount band, so ordinary purchases like ₦1,226.88 are left alone.
    Returns (amount_without_fee, fee)."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return amount, 0.0
    upper = f" {(text or '').upper()} "
    if not any(w in upper for w in _TRANSFER_WORDS):
        return amount, 0.0
    for limit, fee in _NIP_FEE_BANDS:
        base = round(amount - fee, 2)
        if base > 0 and abs(base - round(base)) < 0.005:
            band_fee = next(f for lim, f in _NIP_FEE_BANDS if base <= lim)
            if band_fee == fee:
                return float(round(base)), fee
    return amount, 0.0


def safe_filename(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "")).strip("_") or "File"


def NFTextField(*args, **kwargs):
    """A text box without the small "6/40" counter under it (the app already warns at the limit)."""
    if kwargs.get("max_length") and "counter" not in kwargs:
        kwargs["counter"] = ""
    return ft.TextField(*args, **kwargs)


def fmt_money(value, decimals=2):
    """₦1,250.00 — and -₦1,250.00 (not ₦-1,250.00) when the amount is negative."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    return f"{'-' if value < 0 else ''}₦{abs(value):,.{decimals}f}"


def fmt_compact(value):
    """Short money for small spaces: ₦850, ₦12.5K, ₦1.2M."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}₦{v / 1_000_000:.1f}M".replace(".0M", "M")
    if v >= 10_000:
        return f"{sign}₦{v / 1_000:.1f}K".replace(".0K", "K")
    return f"{sign}₦{v:,.0f}"


def month_stats(transactions, year, month, up_to_day=31):
    """Totals for one month (optionally only up to a day of that month)."""
    income = expense = charges = 0.0
    by_cat = {}
    count = 0
    for t in transactions or []:
        try:
            d = datetime.date.fromisoformat(t["date"])
            if d.year != year or d.month != month or d.day > up_to_day:
                continue
            amount = float(t.get("amount", 0) or 0)
        except Exception:
            continue
        count += 1
        if t.get("type") == "income":
            income += amount
        else:
            expense += amount
            cat = t.get("category", "Other") or "Other"
            by_cat[cat] = by_cat.get(cat, 0.0) + amount
        try:
            charges += float(t.get("charge", 0) or 0)
        except (TypeError, ValueError):
            pass
    return {"income": income, "expense": expense, "charges": charges, "by_cat": by_cat, "count": count,
            "spent": expense + charges, "net": income - expense - charges}


def prev_month(year, month):
    return (year, month - 1) if month > 1 else (year - 1, 12)


def due_phrase(days_left):
    if days_left is None:
        return ""
    if days_left > 1:
        return f"{days_left} days left"
    if days_left == 1:
        return "1 day left"
    if days_left == 0:
        return "Due today"
    return f"Overdue by {abs(days_left)} day{'s' if abs(days_left) != 1 else ''}"


def recurring_due_dates(rule, today):
    """The dates (oldest first) on which a monthly repeating entry should have been added but
    hasn't been yet. `last_added` is the "YYYY-MM" of the last month already added.
    Never looks back more than 12 months."""
    try:
        day = max(1, min(31, int(rule.get("day", 1))))
        ly, lm = (int(x) for x in str(rule.get("last_added") or "").split("-")[:2])
    except Exception:
        return []
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        if (y, m) <= (ly, lm):
            break
        months.append((y, m))
        y, m = prev_month(y, m)
    out = []
    for y, m in reversed(months):
        due = datetime.date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if due <= today:
            out.append(due)
    return out


def ajo_round_status(group, today=None):
    """Where an Ajo group's current round stands, or None if no round is running."""
    today = today or datetime.date.today()
    try:
        order = list(group.get("order") or [])
        cur = int(group.get("current_round", 1))
        if not order or cur < 1 or cur > len(order):
            return None
        collector = order[cur - 1]
        payments = (group.get("payments") or {}).get(str(cur), {}) or {}
        contributors = [m for m in order if m != collector]
        paid = [m for m in contributors if payments.get(m)]
        unpaid = [m for m in contributors if not payments.get(m)]
        contribution = float(group.get("contribution_amount") or 0)
    except Exception:
        return None
    due = None
    month_label = ""
    months = group.get("round_months") or []
    if cur - 1 < len(months):
        try:
            y, m = (int(x) for x in str(months[cur - 1]).split("-")[:2])
            month_label = datetime.date(y, m, 1).strftime("%B %Y")
            if group.get("due_day"):
                due = datetime.date(y, m, min(int(group["due_day"]), calendar.monthrange(y, m)[1]))
        except Exception:
            due = None
    return {"name": group.get("name", "Ajo Group"), "round": cur, "rounds": len(order), "collector": collector,
            "paid": paid, "unpaid": unpaid, "contribution": contribution,
            "pot": contribution * (1 + len(paid)), "full_pot": contribution * len(order),
            "due": due, "days_left": (due - today).days if due else None, "month_label": month_label}


_CARD_STYLES = {  # name: (font size, bold, colour)
    "brand": (40, True, "#FFFFFF"), "sub": (30, True, "#FFD54F"), "title": (58, True, "#FFFFFF"),
    "gold": (34, True, "#FFD54F"), "big": (76, True, "#FFD54F"), "soft": (28, False, "#DDDDDD"),
    "good": (36, True, "#5DE88C"), "bad": (36, True, "#FF8A80"), "warn": (36, True, "#FFB74D"),
    "text": (38, False, "#FFFFFF"), "gap": (18, False, "#FFFFFF"),
}


def render_card_png(lines):
    """Draws a share card as a PNG without using the screen (backup for phones where the
    on-screen capture fails). `lines` is a list of (text, style) or (left, right, style)."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    regular, bold = _asset_path("DejaVuSans.ttf"), _asset_path("DejaVuSans-Bold.ttf")
    if not (regular and bold):
        raise RuntimeError("font files missing")
    fonts = {}

    def font(size, is_bold):
        key = (size, is_bold)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(bold if is_bold else regular, size)
        return fonts[key]

    width, pad = 900, 54
    inner = width - 2 * pad
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    def wrap(text, f):
        out, line = [], ""
        for word in str(text).split():
            trial = (line + " " + word).strip()
            if probe.textlength(trial, font=f) <= inner or not line:
                line = trial
            else:
                out.append(line)
                line = word
        return out + [line] if line else out

    rows = []  # (y, kind, payload)
    y = pad
    for item in lines:
        style = item[-1]
        size, is_bold, colour = _CARD_STYLES.get(style, _CARD_STYLES["text"])
        f = font(size, is_bold)
        if style == "gap":
            y += size
        elif len(item) == 3:
            rows.append((y, "pair", (str(item[0]), str(item[1]), f, colour)))
            y += int(size * 1.45)
        else:
            for part in wrap(item[0], f):
                rows.append((y, "text", (part, f, colour)))
                y += int(size * 1.32)
            y += int(size * 0.25)
    height = y + pad
    img = Image.new("RGB", (width, height), "#2A0845")
    draw = ImageDraw.Draw(img)
    top, bottom = (0x6A, 0x1B, 0xB0), (0x2A, 0x08, 0x45)
    for row in range(height):
        k = row / max(height - 1, 1)
        draw.line([(0, row), (width, row)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))
    for y, kind, payload in rows:
        if kind == "pair":
            left, right, f, colour = payload
            draw.text((pad, y), left, font=font(f.size, False), fill="#DDDDDD")
            draw.text((width - pad - draw.textlength(right, font=f), y), right, font=f, fill=colour)
        else:
            text, f, colour = payload
            draw.text((pad, y), text, font=f, fill=colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_GROUP_META_KEYS = ("updated_at", "last_shared_at", "is_admin")


def group_fingerprint(group):
    """The group's content, ignoring the bookkeeping fields, to tell whether anything changed."""
    try:
        return json.dumps({k: v for k, v in group.items() if k not in _GROUP_META_KEYS}, sort_keys=True, default=str)
    except Exception:
        return ""


def fmt_stamp(iso):
    """'2026-11-16T16:40:05' -> '16 Nov, 4:40 PM'."""
    try:
        d = datetime.datetime.fromisoformat(str(iso))
    except Exception:
        return ""
    return f"{d.day} {d.strftime('%b')}, {d.strftime('%I:%M %p').lstrip('0')}"


def hash_secret(secret, salt):
    return hashlib.sha256(f"{salt}|{secret}".encode("utf-8")).hexdigest()


def ui_progress_bar(pct, color, height=10):
    """A full-width progress bar (0-100%)."""
    pct = max(0.0, min(100.0, float(pct or 0)))
    filled = int(round(pct * 10))
    parts = []
    if filled > 0:
        parts.append(ft.Container(expand=filled, height=height, bgcolor=color, border_radius=height / 2))
    if filled < 1000:
        parts.append(ft.Container(expand=1000 - filled, height=height))
    return ft.Container(content=ft.Row(parts, spacing=0), height=height, border_radius=height / 2,
                        bgcolor=ft.Colors.with_opacity(0.22, ft.Colors.WHITE))


RING_COLORS = ("#FF6B6B", "#FFD54F", "#64B5F6", "#81C784", "#BA68C8", "#FFB74D")

MONEY_GREEN = "#5DE88C"   # money in / positive balance (bright enough for the dark cards)
MONEY_RED = "#FF8A80"     # money out / negative balance
CAPTION_GOLD = "#FFD54F"  # field captions on the dark cards


BACKUP_EXTRA_KEYS = ("ajo_groups", "active_ajo_group_id", "category_changes", "salary_history", "alert_category_rules", "savings_goals", "month_todos")

PHOTO_STRIPPED_MSG = ("This picture has no data inside. It was probably sent as a photo, which removes the data. "
                      "Ask the sender to send it again on WhatsApp as a Document (📎 → Document).")

async def build_ui(page: ft.Page):
    page.title = "Naira Finance Hub"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.adaptive = True
    page.padding = 0
    prefs = _PrefsCache(page.shared_preferences)

    def with_length_warning(field, max_len, existing_handler=None):
        async def _check(e):
            if len(field.value or "") >= max_len:
                page.show_dialog(ft.SnackBar(ft.Text(f"Maximum {max_len} characters reached.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=2), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()
            if existing_handler:
                result = existing_handler(e)
                if asyncio.iscoroutine(result):
                    await result
        return _check

    DARK_TEXT = "#222222"
    PURPLE_TEXT = "#4B0082"

    BANNER_AD_UNIT_ID = {
        ft.PagePlatform.ANDROID: "ca-app-pub-1457775538229669/6405669354",
        ft.PagePlatform.IOS: "ca-app-pub-3940256099942544/2934735716",
    }

    # ==================================================================
    # NIGERIA PAYE TAX (Nigeria Tax Act 2025, effective 1 Jan 2026)
    # ==================================================================
    def compute_paye_annual(taxable_annual: float) -> float:
        bands = [
            (800_000, 0.00),
            (3_000_000, 0.15),
            (12_000_000, 0.18),
            (25_000_000, 0.21),
            (50_000_000, 0.23),
            (float("inf"), 0.25),
        ]
        tax = 0.0
        lower = 0.0
        remaining = max(taxable_annual, 0.0)
        for upper, rate in bands:
            band_size = upper - lower
            if remaining <= 0:
                break
            taxed_in_band = min(remaining, band_size)
            tax += taxed_in_band * rate
            remaining -= taxed_in_band
            lower = upper
        return tax

    # ==================================================================
    # TERMS AND CONDITIONS (full-page, scroll-gated)
    # ==================================================================
    async def close_terms(e=None):
        try:
            await prefs.set("terms_accepted", True)
            await check_name()
        except Exception as ex:
            show_error_screen(ex)

    def decline_terms(e=None):
        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Agreement Required", size=22, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            "You must accept the Terms and Conditions to use this app. Please close and reopen the app if you'd like to review and accept them.",
                            size=15, color="white", text_align=ft.TextAlign.CENTER
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=15,
                ),
                padding=30,
                alignment=ft.Alignment(0, 0),
                expand=True,
            )
        )
        page.update()

    def show_terms_screen():
        scroll_hint = ft.Text(
            "⬇ Please scroll down to read the full agreement before continuing.",
            color="#FF3B30", size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER
        )

        agree_btn = ft.ElevatedButton(
            content=ft.Container(
                content=ft.Text("I Agree", weight=ft.FontWeight.BOLD, size=16, color="white"),
                padding=ft.Padding(left=10, right=10, top=6, bottom=6),
            ),
            on_click=close_terms,
            style=ft.ButtonStyle(bgcolor="#2E8B57"),
            width=280,
        )
        disagree_btn = ft.ElevatedButton(
            content=ft.Container(
                content=ft.Text("I Don't Agree", weight=ft.FontWeight.BOLD, size=16, color="white"),
                padding=ft.Padding(left=10, right=10, top=6, bottom=6),
            ),
            on_click=decline_terms,
            style=ft.ButtonStyle(bgcolor="#C62828"),
            width=280,
        )

        buttons_column = ft.Column([agree_btn, disagree_btn], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)

        def on_terms_scroll(e):
            if e.pixels >= (e.max_scroll_extent - 15):
                scroll_hint.visible = False
                page.update()

        terms_listview = ft.ListView(
            controls=[
                ft.Text("Terms and Conditions", size=18, weight=ft.FontWeight.BOLD, color=PURPLE_TEXT),
                ft.Text(
                    "1. Purpose: This application is provided as a general tool to help staff of any organization estimate their housing upfront payments and salary breakdowns, based on figures you enter yourself.\n\n"
                    "2. Accuracy: All calculations, including PAYE tax estimates, are based on the Nigeria Tax Act 2025 as understood at the time of writing and are for guidance only. Verify against your organization's official payroll policy and current tax law. Official sources: Nigeria Revenue Service (www.nrs.gov.ng) for PAYE and the Nigeria Tax Act 2025; National Pension Commission (www.pencom.gov.ng) for pension; Federal Mortgage Bank of Nigeria (www.fmbn.gov.ng) for the National Housing Fund.\n\n"
                    "Not a government app: Naira Finance Hub is an independent app. It is not affiliated with, endorsed by, or representing the Nigerian government or any government agency.\n\n"
                    "3. Disclaimer: The developer is not responsible for any financial or tax decisions made based on these calculations. Please consult your HR department or a tax professional for official confirmation.\n\n"
                    "4. Privacy: Your salary figures, transactions, Ajo groups and other entries are stored only on your device and are never sent to the developer. The app shows ads from Google AdMob; to serve and measure ads, Google may collect device information such as your advertising ID and approximate location, as described in Google's privacy policy (policies.google.com/privacy). You can reset or delete your advertising ID in your phone's Settings → Google → Ads.",
                    color=DARK_TEXT,
                    size=14
                ),
            ],
            spacing=10,
            on_scroll=on_terms_scroll,
            expand=True,
        )

        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Welcome & Agreement", size=20, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER),
                        ft.Container(
                            content=terms_listview,
                            bgcolor="#FFFFFF",
                            border_radius=10,
                            padding=15,
                            expand=True,
                        ),
                        scroll_hint,
                        buttons_column,
                        ft.Container(height=25),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=15,
                    expand=True,
                ),
                padding=20,
                expand=True,
            )
        )
        page.update()

    # ==================================================================
    # NAME PROMPT
    # ==================================================================
    greeting_name = ft.Text("Staff!", size=20, weight=ft.FontWeight.BOLD, color="white")

    def open_name_dialog(e=None):
        async def save_name(e):
            new_name = name_field.value
            greeting_name.value = f"{new_name}!" if new_name else "Staff!"
            await prefs.set("user_name", new_name)
            page.pop_dialog()
            page.update()

        name_field = NFTextField(
            label="Your Name",
            value=greeting_name.value.rstrip("!") if greeting_name.value != "Staff!" else "",
            autofocus=True,
            bgcolor="#FFFFFF",
            color=PURPLE_TEXT,
            label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            capitalization=ft.TextCapitalization.WORDS,
            max_length=30,
        )
        name_field.on_change = with_length_warning(name_field, 30)
        name_dialog = ft.AlertDialog(scrollable=True, 
            modal=True,
            bgcolor="#FFFFFF",
            title=ft.Text("Welcome!", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Please enter your name so we can greet you personally.",
                            color=DARK_TEXT,
                            size=14
                        ),
                        name_field,
                    ],
                    tight=True,
                    spacing=15
                ),
                width=300,
                padding=10
            ),
            actions=[ft.TextButton("Save", on_click=save_name, style=ft.ButtonStyle(color=PURPLE_TEXT))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(name_dialog)

    def show_error_screen(ex):
        import traceback
        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Startup Error", size=20, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(str(ex), size=14, color="yellow", selectable=True),
                        ft.Divider(color="white"),
                        ft.Text(traceback.format_exc(), size=10, color="white", selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
                padding=20,
                expand=True,
            )
        )
        page.update()

    TUTORIAL_SLIDES = [
        {
            "icon": ft.Icons.DASHBOARD_ROUNDED,
            "icon_color": "#FFD54F",
            "title": "Home",
            "text": "Home shows your month at a glance: money in, money out and your balance, how much budget is left, your next Ajo due date, your savings goals and any reminders. Tap a card or one of the four big buttons to jump straight to that tool. The ☰ menu (top-left) also takes you anywhere.",
        },
        {
            "icon": ft.Icons.HOME_ROUNDED,
            "icon_color": "#FF8C00",
            "title": "Housing Upfront",
            "text": "Calculate your housing upfront payment based on your basic salary, any increment, and your organization's rate — plus see your equivalent monthly housing allowance.",
        },
        {
            "icon": ft.Icons.WORK_ROUNDED,
            "icon_color": "#E53935",
            "title": "Salary Management",
            "text": "Get a full payslip breakdown — Gross Pay, Pension, NHF, and PAYE tax — using the current Nigeria Tax Act 2025 bands. Save calculations to compare over time.",
        },
        {
            "icon": ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED,
            "icon_color": "#1E88E5",
            "title": "Money Tracker: Log Transactions",
            "text": "Add Income or Expense entries with a Category (with its own icon), an optional Bank Charge for transfer/POS fees, an optional Note, and a Date — pick one from the calendar, or leave it blank to use today automatically. Save your regular transactions as 'Quick Add' shortcuts for one-tap logging, and tap the ↻ icon on any past entry to repeat it instantly with today's date.",
        },
        {
            "icon": ft.Icons.SWITCH_ACCOUNT_ROUNDED,
            "icon_color": "#1E88E5",
            "title": "Money Tracker: Profiles",
            "text": "Keep separate records for different purposes — e.g. Work, Business, Personal. Tap the blue profile button to switch between up to 3 profiles, each with its own transactions and budgets. Tap the pencil icon next to any profile to rename it.",
        },
        {
            "icon": ft.Icons.BAR_CHART_ROUNDED,
            "icon_color": "#1E88E5",
            "title": "Money Tracker: Summaries & Budgets",
            "text": "See Monthly and Annual totals, a category-by-category chart, and a full breakdown list. Use the month arrows to browse past months. Set a monthly spending limit per category and get a visual warning when you're close to or over it.",
        },
        {
            "icon": ft.Icons.MENU_ROUNDED,
            "icon_color": "#1E88E5",
            "title": "Money Tracker: Export & Backup",
            "text": "Tap the green Options button on the Money Tracker page for PDF export of any month or year, and Backup/Restore to save all 3 profiles to a file — useful when switching phones. Search your transactions anytime, and deleted entries can be undone within 5 seconds.",
        },
        {
            "icon": ft.Icons.GROUPS_ROUNDED,
            "icon_color": "#8E24AA",
            "title": "Ajo Groups: Setup & Admin",
            "text": "Run multiple Ajo/esusu groups at once. Whoever creates a group becomes its Admin — only they can edit it. Set the contribution amount, add members, pick your first payment due date, and optionally write Rules & Regulations everyone can view. Share a group as a file so others can load it read-only on their own phone.",
        },
        {
            "icon": ft.Icons.CASINO_ROUNDED,
            "icon_color": "#8E24AA",
            "title": "Ajo Groups: Choosing the Order",
            "text": "Two ways to set the order: 'Draw Order' runs a fair, full-screen animated random draw (with a reminder to screen-record for a bias-free record) — or 'Set Order Manually' if your group already agreed on a sequence. Either way, you'll review the full member list first, then see a full-screen reveal of the final order with each person's assigned month.",
        },
        {
            "icon": ft.Icons.CHECK_CIRCLE_ROUNDED,
            "icon_color": "#8E24AA",
            "title": "Ajo Groups: Tracking & Sharing",
            "text": "Each round shows Unpaid and Paid boxes — tap a name to move it between them as contributions come in. A separate 'Already Collected' list tracks everyone who's had their turn. The Admin can Edit Order (reposition or remove upcoming members) anytime, and export a full PDF progress report to share with the group. To keep members' apps up to date, the Admin taps 'Send update' (or Send Group File to Members) after ticking payments and sends the file on WhatsApp as a Document; members open it with Import Group from File and their copy updates.",
        },
        {
            "icon": ft.Icons.AUTO_AWESOME_ROUNDED,
            "icon_color": "#FFD54F",
            "title": "More Helpful Tools",
            "text": "Savings Goals (on Home): set a target, add money as you save and watch the bar fill. Repeating Entries (Money Tracker → Options): rent, salary or subscriptions are added for you every month. Share as Picture: send an Ajo round or a payslip estimate to WhatsApp as a clean image. App Lock (☰ → Settings): protect the app with a 4-digit PIN.",
        },
    ]

    def show_tutorial_screen():
        slide_index = {"value": 0}
        slide_icon = ft.Icon(TUTORIAL_SLIDES[0]["icon"], size=70, color=TUTORIAL_SLIDES[0]["icon_color"])
        slide_title = ft.Text(TUTORIAL_SLIDES[0]["title"], size=22, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER)
        slide_text = ft.Text(TUTORIAL_SLIDES[0]["text"], size=14, color="white", text_align=ft.TextAlign.CENTER)
        dots_row = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=8)
        next_btn_text = ft.Text("Next", weight=ft.FontWeight.BOLD, color="#4B0082")

        def build_dots():
            def make_jump(idx):
                def _jump(e):
                    slide_index["value"] = idx
                    render_slide()
                return _jump

            dots_row.controls = [
                ft.Container(
                    width=9, height=9, border_radius=5,
                    bgcolor="#FFD700" if i == slide_index["value"] else ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
                    on_click=make_jump(i),
                )
                for i in range(len(TUTORIAL_SLIDES))
            ]

        def render_slide():
            s = TUTORIAL_SLIDES[slide_index["value"]]
            slide_icon.icon = s["icon"]
            slide_icon.color = s["icon_color"]
            slide_title.value = s["title"]
            slide_text.value = s["text"]
            next_btn_text.value = "Get Started" if slide_index["value"] == len(TUTORIAL_SLIDES) - 1 else "Next"
            back_btn.visible = slide_index["value"] > 0
            build_dots()
            page.update()

        async def finish_tutorial(e=None):
            await prefs.set("tutorial_seen", True)
            await check_name()

        async def go_next(e):
            if slide_index["value"] < len(TUTORIAL_SLIDES) - 1:
                slide_index["value"] += 1
                render_slide()
            else:
                await finish_tutorial()

        async def go_back(e):
            if slide_index["value"] > 0:
                slide_index["value"] -= 1
                render_slide()

        async def skip_tutorial(e):
            await finish_tutorial()

        back_btn = ft.TextButton(
            content=ft.Row([ft.Icon(ft.Icons.ARROW_BACK_ROUNDED, color="white", size=16), ft.Text("Back", color="white")], spacing=4, tight=True),
            on_click=go_back,
            visible=False,
        )

        build_dots()

        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Container(height=20),
                        slide_icon,
                        ft.Container(height=10),
                        slide_title,
                        ft.Container(height=10),
                        ft.Container(content=slide_text, padding=ft.Padding(left=20, right=20, top=0, bottom=0)),
                        ft.Container(height=20),
                        dots_row,
                        ft.Container(height=30),
                        back_btn,
                        ft.ElevatedButton(
                            content=next_btn_text,
                            on_click=go_next,
                            style=ft.ButtonStyle(bgcolor="#FFD700"),
                            width=200,
                        ),
                        ft.TextButton(
                            content=ft.Text("Skip", color="white"),
                            on_click=skip_tutorial,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=4,
                ),
                padding=20,
                alignment=ft.Alignment(0, 0),
                expand=True,
            )
        )
        page.update()

    async def check_name():
        try:
            try:
                tutorial_seen = await prefs.get("tutorial_seen")
            except Exception:
                tutorial_seen = False

            if not tutorial_seen:
                show_tutorial_screen()
                return

            existing_name = await prefs.get("user_name")
            if not existing_name:
                open_name_dialog()
            await build_main_app()
        except Exception as ex:
            show_error_screen(ex)

    # ==================================================================
    # SHARED UI HELPER
    # ==================================================================
    def field_with_caption(caption_text, field, on_white=False):
        # Soft gold on the dark cards (the old red was hard to read); dark purple inside white pop-ups.
        return ft.Column(
            [
                ft.Text(caption_text, color=PURPLE_TEXT if on_white else CAPTION_GOLD, weight=ft.FontWeight.BOLD, size=12),
                field,
            ],
            spacing=2,
            tight=True,
        )

    # ==================================================================
    # MAIN APP (Housing Upfront tab + Salary Management tab)
    # ==================================================================
    build_gen = {"n": 0}

    async def build_main_app():
        # "Replay Tutorial" rebuilds the app. Stop the old animation loops and drop the old
        # sound players/sensors so they don't pile up and slow the phone down.
        build_gen["n"] += 1
        my_gen = build_gen["n"]
        try:
            page.services.clear()
            _SENSOR_GATE["on"] = False
        except Exception:
            pass
        dice_tick_sound = fta_audio.Audio(src="dice_tick.wav", autoplay=False, volume=1)
        reveal_ding_sound = fta_audio.Audio(src="reveal_ding.wav", autoplay=False, volume=1)
        fanfare_sound = fta_audio.Audio(src="fanfare.wav", autoplay=False, volume=1)
        page.services.append(dice_tick_sound)
        page.services.append(reveal_ding_sound)
        page.services.append(fanfare_sound)
        # Ajo draw "live show" sounds (original, generated for this app)
        draw_music = fta_audio.Audio(src="draw_music.wav", autoplay=False, volume=0.35,
                                     release_mode=fta_audio.ReleaseMode.LOOP)
        drumroll_sound = fta_audio.Audio(src="drumroll.wav", autoplay=False, volume=0.9)
        cheer_sound = fta_audio.Audio(src="crowd_cheer.wav", autoplay=False, volume=0.8)
        for _snd in (draw_music, drumroll_sound, cheer_sound):
            page.services.append(_snd)
        draw_sound = {"on": True, "music_playing": False}

        # ---- Settings from the Menu: "Motion effects" and "Vibrate on tap" (both On by default) ----
        async def _load_flag(key, default=True):
            try:
                val = await prefs.get(key)
            except Exception:
                return default
            if val is None or val == "":
                return default
            return str(val).lower() in ("1", "true", "on", "yes")

        # Off unless you switch it on: the moving background made buttons stop responding
        # on low-end phones.
        motion = {"on": await _load_flag("motion_effects", default=False)}
        haptic = {"on": await _load_flag("vibrate_on_tap")}
        haptics = ft.HapticFeedback()
        page.services.append(haptics)
        haptic_busy = {"value": False}

        async def _buzz():
            if haptic_busy["value"]:
                return
            haptic_busy["value"] = True
            try:
                if native_vibrate():
                    return
                await asyncio.wait_for(haptics.vibrate(), timeout=1.5)
            except Exception:
                pass
            finally:
                haptic_busy["value"] = False

        def _on_any_tap():
            if haptic["on"] and build_gen["n"] == my_gen:
                asyncio.create_task(_buzz())

        _TAP_HOOK["fn"] = _on_any_tap
        settings_actions = {}

        async def start_draw_music():
            if draw_sound["on"] and not draw_sound["music_playing"]:
                try:
                    await draw_music.play()
                    draw_sound["music_playing"] = True
                except Exception:
                    pass

        async def stop_draw_music():
            if draw_sound["music_playing"]:
                try:
                    await draw_music.pause()
                except Exception:
                    pass
                draw_sound["music_playing"] = False

        try:
            saved_theme = await prefs.get("theme_override")
        except Exception:
            saved_theme = None

        if saved_theme == "dark":
            is_dark_mode = True
        elif saved_theme == "light":
            is_dark_mode = False
        else:
            try:
                is_dark_mode = page.platform_brightness == ft.Brightness.DARK
            except Exception:
                is_dark_mode = False

        change_btn = ft.ElevatedButton(
            content=ft.Text("Change Name", weight=ft.FontWeight.BOLD, size=11, color="#4B0082"),
            on_click=open_name_dialog,
            style=ft.ButtonStyle(bgcolor="#FFD700", padding=ft.Padding(left=8, right=8, top=4, bottom=4)),
        )

        wave_hand = ft.Container(
            content=ft.Text("🥰", size=26),
            rotate=0,
            animate_rotation=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
        )

        # Background animations only run while the app is on screen. Before, they kept
        # redrawing the whole page several times a second even when the app was in the
        # background, draining battery and piling up redraws (a likely cause of the
        # blank screen after returning to the app).
        app_active = {"value": True}

        def _refresh(*controls):
            for c in controls:
                try:
                    c.update()
                except Exception:
                    pass

        async def animate_wave_loop():
            try:
                while build_gen["n"] == my_gen:
                    if not app_active["value"] or not motion["on"]:
                        await asyncio.sleep(1.0)  # resting while the app is in the background
                        continue
                    for angle, pause in ((0.35, 0.3), (-0.35, 0.3), (0.35, 0.3), (0, 1.5)):
                        wave_hand.rotate = angle
                        _refresh(wave_hand)
                        await asyncio.sleep(pause)
            except Exception:
                pass

        dark_mode_state = {"value": is_dark_mode}
        mode_badge_icon = ft.Icon(ft.Icons.DARK_MODE_ROUNDED if is_dark_mode else ft.Icons.LIGHT_MODE_ROUNDED, size=14, color="#FFD700")
        mode_badge_text = ft.Text("Dark Mode" if is_dark_mode else "Light Mode", size=11, weight=ft.FontWeight.BOLD, color="white")

        galaxy_stars_active = {"value": False}
        galaxy_current = {"anim": None}   # only the newest galaxy keeps animating

        GALAXY_W, GALAXY_H = 470, 980          # roughly the background area (screen plus tilt margin)
        STAR_DRIFT = (7.0, -15.0)              # stars float up-right, along the Milky Way band

        def build_galaxy_background():
            # A painted Milky Way (stars, nebula clouds and dust lanes) as one picture, which costs a
            # low-end phone almost nothing. With animations on it comes alive: the galaxy slowly turns
            # and breathes, stars drift along the band and twinkle, and now and then a star shoots past.
            anim = {"stars": [], "speeds": [], "sky": None, "shooter": None}
            sky = ft.Container(
                content=ft.Image(src="galaxy.jpg", fit=ft.BoxFit.COVER),
                left=0, top=0, right=0, bottom=0,
                scale=1.1, rotate=0,
                animate_scale=ft.Animation(26000, ft.AnimationCurve.EASE_IN_OUT),
                animate_rotation=ft.Animation(26000, ft.AnimationCurve.EASE_IN_OUT),
            )
            layers = [ft.Container(bgcolor="#07041A", left=0, top=0, right=0, bottom=0), sky]
            anim["sky"] = sky
            galaxy_current["anim"] = anim
            if motion["on"]:
                for _ in range(40):
                    dot_size = random.choice([2, 2, 2, 3, 3, 4])
                    star = ft.Container(
                        width=dot_size, height=dot_size,
                        border_radius=dot_size,
                        bgcolor=random.choice(["white", "white", "#CFE3FF", "#FFE4C4", "#FFC8E8"]),
                        left=random.uniform(0, GALAXY_W),
                        top=random.uniform(0, GALAXY_H),
                        opacity=random.uniform(0.35, 1.0),
                        animate_opacity=ft.Animation(random.randint(1200, 2400), ft.AnimationCurve.EASE_IN_OUT),
                        animate_position=ft.Animation(3000, ft.AnimationCurve.LINEAR),
                    )
                    anim["stars"].append(star)
                    anim["speeds"].append(random.uniform(0.5, 1.6))  # nearer stars move faster
                shooter = ft.Container(
                    width=120, height=2, border_radius=2, rotate=-0.5, opacity=0,
                    left=GALAXY_W, top=60,
                    gradient=ft.LinearGradient(begin=ft.Alignment(-1, 0), end=ft.Alignment(1, 0),
                                               colors=["#FFFFFF", ft.Colors.with_opacity(0.0, "#CFE3FF")]),
                    animate_position=ft.Animation(900, ft.AnimationCurve.EASE_IN),
                    animate_opacity=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
                )
                anim["shooter"] = shooter
                layers += anim["stars"] + [shooter]
            return anim, ft.Stack(controls=layers, expand=True)

        async def shooting_star(shooter):
            # Jump (invisibly) to a start point in the upper half, then streak down-left and fade.
            shooter.opacity = 0
            shooter.left = random.uniform(GALAXY_W * 0.45, GALAXY_W)
            shooter.top = random.uniform(20, GALAXY_H * 0.45)
            _refresh(background_layer)
            await asyncio.sleep(1.0)
            if not galaxy_stars_active["value"]:
                return
            shooter.opacity = 1
            shooter.left -= 300
            shooter.top += 165
            _refresh(background_layer)
            await asyncio.sleep(0.6)
            shooter.opacity = 0
            _refresh(background_layer)

        async def twinkle_galaxy(anim):
            stars, speeds, sky, shooter = anim["stars"], anim["speeds"], anim["sky"], anim["shooter"]
            tick, next_turn, next_shot = 0, 0, random.randint(3, 6)
            try:
                while galaxy_stars_active["value"] and build_gen["n"] == my_gen and galaxy_current["anim"] is anim:
                    if not app_active["value"] or not motion["on"] or not stars:
                        await asyncio.sleep(1.0)
                        continue
                    for s, k in zip(stars, speeds):
                        # A star that floats off the top/right edge fades out, jumps (unseen) back to
                        # the bottom/left edge, then fades in again: three quiet steps.
                        if s.data == "hiding":
                            s.data = "wrap"
                            if random.random() < 0.5:
                                s.left, s.top = random.uniform(-5, GALAXY_W * 0.6), GALAXY_H + random.uniform(0, 20)
                            else:
                                s.left, s.top = -random.uniform(0, 20), random.uniform(GALAXY_H * 0.3, GALAXY_H)
                            continue
                        if s.data == "wrap":
                            s.data = None
                            s.opacity = random.uniform(0.35, 1.0)
                            continue
                        if s.left > GALAXY_W or s.top < -5:
                            s.data = "hiding"
                            s.opacity = 0
                            continue
                        s.left += STAR_DRIFT[0] * k
                        s.top += STAR_DRIFT[1] * k
                        s.opacity = random.uniform(0.3, 1.0)
                    if tick >= next_turn:              # the whole galaxy slowly turns and breathes
                        sky.scale = 1.1 if sky.scale > 1.12 else 1.16
                        sky.rotate = -0.035 if (sky.rotate or 0) >= 0 else 0.035
                        next_turn = tick + 9           # 9 ticks x 3 s ~ the 26 s animation
                    _refresh(background_layer)
                    if shooter is not None and tick >= next_shot:
                        asyncio.create_task(shooting_star(shooter))
                        next_shot = tick + random.randint(3, 6)
                    tick += 1
                    await asyncio.sleep(3.0)
            except Exception:
                pass

        def restart_galaxy():
            """Rebuild the dark background (e.g. after animations are switched on or off)."""
            if not dark_mode_state["value"]:
                return
            galaxy_stars_active["value"] = False
            anim, stack = build_galaxy_background()
            background_layer.content = stack
            galaxy_stars_active["value"] = True
            asyncio.create_task(twinkle_galaxy(anim))

        def build_light_background():
            # The big "h" stays bright behind the header and fades into deep purple lower down,
            # so it no longer cuts through the cards and text.
            return ft.Stack(
                controls=[
                    ft.Image(src="background.png", fit=ft.BoxFit.COVER, left=0, top=0, right=0, bottom=0),
                    ft.Container(
                        left=0, top=0, right=0, bottom=0,
                        gradient=ft.LinearGradient(
                            begin=ft.Alignment(0, -1), end=ft.Alignment(0, 1),
                            colors=[ft.Colors.with_opacity(0.0, "#2A0845"), ft.Colors.with_opacity(0.78, "#2A0845"),
                                    ft.Colors.with_opacity(0.90, "#2A0845")],
                            stops=[0.10, 0.34, 1.0],
                        ),
                    ),
                ],
            )

        async def toggle_dark_mode(e):
            dark_mode_state["value"] = not dark_mode_state["value"]
            if dark_mode_state["value"]:
                galaxy_stars, galaxy_stack = build_galaxy_background()
                background_layer.content = galaxy_stack
                background_layer.bgcolor = None
                galaxy_stars_active["value"] = True
                asyncio.create_task(twinkle_galaxy(galaxy_stars))
                mode_badge_icon.icon = ft.Icons.DARK_MODE_ROUNDED
                mode_badge_text.value = "Dark Mode"
                logo_image.src = "logo_bw.png"
                logo_backing_square.bgcolor = "#FFFFFF"
            else:
                galaxy_stars_active["value"] = False
                background_layer.content = build_light_background()
                background_layer.bgcolor = None
                mode_badge_icon.icon = ft.Icons.LIGHT_MODE_ROUNDED
                mode_badge_text.value = "Light Mode"
                logo_image.src = "background.png"
                logo_backing_square.bgcolor = "#FFD54F"
            await prefs.set("theme_override", "dark" if dark_mode_state["value"] else "light")
            page.update()

        mode_badge = ft.Container(
            content=ft.Row([mode_badge_icon, mode_badge_text], spacing=4, tight=True),
            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.WHITE),
            border_radius=20,
            padding=ft.Padding(left=10, right=10, top=4, bottom=4),
            on_click=toggle_dark_mode,
            ink=True,
        )

        greeting_row = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        controls=[change_btn, mode_badge],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        controls=[ft.Text("Welcome back,", size=20, color="white"), greeting_name, wave_hand],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                        wrap=True,
                    ),
                ],
                spacing=10,
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
        )

        # The purple "h" (same picture as the app icon), cropped to a rounded square.
        # In dark mode the logo turns black and white, on a white backing square instead of gold.
        logo_image = ft.Image(src="logo_bw.png" if is_dark_mode else "background.png",
                              width=90, height=90, fit=ft.BoxFit.COVER, border_radius=20)
        logo_container = ft.Container(
            content=logo_image,
            scale=1.0,
            rotate=0,
            animate_scale=ft.Animation(3300, ft.AnimationCurve.EASE_IN_OUT),
            animate_rotation=ft.Animation(18000, ft.AnimationCurve.LINEAR),
        )

        logo_backing_square = ft.Container(
            width=90,
            height=90,
            bgcolor="#FFFFFF" if is_dark_mode else "#FFD54F",
            border_radius=20,
            rotate=0,
            animate_rotation=ft.Animation(18000, ft.AnimationCurve.LINEAR),
        )

        logo_stack = ft.Stack(
            controls=[logo_backing_square, logo_container],
            width=90,
            height=90,
        )

        logo_wrapper = ft.Container(
            content=logo_stack,
            offset=ft.Offset(0, 0),
            animate_offset=ft.Animation(80, ft.AnimationCurve.EASE_OUT),
        )

        async def animate_logo_pulse_loop():
            try:
                while build_gen["n"] == my_gen:
                    if not app_active["value"] or not motion["on"]:
                        await asyncio.sleep(1.0)
                        continue
                    logo_container.scale = 1.08
                    _refresh(logo_container)
                    await asyncio.sleep(3.3)
                    logo_container.scale = 1.0
                    _refresh(logo_container)
                    await asyncio.sleep(3.3)
            except Exception:
                pass

        async def animate_logo_spin_loop():
            angle = 0.0
            square_angle = 0.0
            full_turn = 6.28318530718
            try:
                while build_gen["n"] == my_gen:
                    if not app_active["value"] or not motion["on"]:
                        await asyncio.sleep(1.0)
                        continue
                    angle += full_turn
                    square_angle -= full_turn
                    logo_container.rotate = angle
                    logo_backing_square.rotate = square_angle
                    _refresh(logo_container, logo_backing_square)
                    await asyncio.sleep(18.0)
            except Exception:
                pass

        header_text = ft.Container(
            content=ft.Text(
                "Naira Finance Hub", size=22, weight=ft.FontWeight.BOLD, color="white",
                text_align=ft.TextAlign.CENTER
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=16, right=16, top=8, bottom=8),
        )

        header_container = ft.Container(
            content=ft.Column(
                controls=[logo_wrapper, header_text],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8
            ),
            padding=20,
            width=None,
        )

        try:
            saved_name = await prefs.get("user_name")
            if saved_name:
                greeting_name.value = f"{saved_name}!"
        except Exception:
            pass

        async def load_saved(key, default=""):
            try:
                val = await prefs.get(key)
                return val if val else default
            except Exception:
                return default

        # -------------------- HOUSING UPFRONT TAB --------------------
        last_org = await load_saved("last_org", "")
        last_salary = await load_saved("last_salary", "")
        last_increment_label = await load_saved("last_increment_label", "Salary Increment")
        last_increment_pct = await load_saved("last_increment_pct", "0")
        last_rate_pct = await load_saved("last_rate_pct", "40")

        async def on_org_change(e):
            await prefs.set("last_org", org_input.value)

        async def on_salary_change(e):
            await prefs.set("last_salary", salary_input.value)

        async def on_increment_label_change(e):
            await prefs.set("last_increment_label", increment_label_input.value)

        async def on_increment_change(e):
            await prefs.set("last_increment_pct", increment_input.value)

        async def on_rate_change(e):
            await prefs.set("last_rate_pct", rate_input.value)

        org_input = NFTextField(
            value=last_org, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            capitalization=ft.TextCapitalization.WORDS, max_length=40,
        )
        org_input.on_change = with_length_warning(org_input, 40, on_org_change)
        salary_input = NFTextField(
            value=last_salary, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT, color=PURPLE_TEXT, max_length=15,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        )
        salary_input.on_change = with_length_warning(salary_input, 15, on_salary_change)
        increment_label_input = NFTextField(
            value=last_increment_label, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            capitalization=ft.TextCapitalization.WORDS, max_length=30,
        )
        increment_label_input.on_change = with_length_warning(increment_label_input, 30, on_increment_label_change)
        increment_input = NFTextField(
            value=last_increment_pct, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT, color=PURPLE_TEXT, max_length=6,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        )
        increment_input.on_change = with_length_warning(increment_input, 6, on_increment_change)
        rate_input = NFTextField(
            value=last_rate_pct, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT, color=PURPLE_TEXT, max_length=6,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        )
        rate_input.on_change = with_length_warning(rate_input, 6, on_rate_change)

        result_upfront = ft.Text(spans=[ft.TextSpan("Upfront: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=18)
        result_monthly_allowance = ft.Text(spans=[ft.TextSpan("Monthly Housing Allowance: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=14)
        result_basic = ft.Text(spans=[ft.TextSpan("New Basic: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=14)
        result_increment = ft.Text(spans=[ft.TextSpan("Increment Addition: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=14)
        result_total = ft.Text(spans=[ft.TextSpan("Annual Salary: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=14)

        async def on_calculate_click(e):
            try:
                salary = to_number(salary_input.value, required=True)
                increment_pct = to_number(increment_input.value)
                rate_pct = to_number(rate_input.value, required=True)
                increment_name = increment_label_input.value.strip() or "Increment"

                increment_amount = salary * (increment_pct / 100.0)
                new_basic = salary + increment_amount
                annual_salary = new_basic * 12.0
                upfront_amount = annual_salary * (rate_pct / 100.0)
                monthly_allowance = upfront_amount / 12.0

                result_upfront.spans[1].text = f"₦{upfront_amount:,.2f}"
                result_monthly_allowance.spans[1].text = f"₦{monthly_allowance:,.2f}"
                result_basic.spans[1].text = f"₦{new_basic:,.2f}"
                result_increment.spans[0].text = f"{increment_name} Addition: "
                result_increment.spans[1].text = f"₦{increment_amount:,.2f}"
                result_total.spans[1].text = f"₦{annual_salary:,.2f}"

                housing_results.scale = 0.92
                page.update()
                await asyncio.sleep(0.08)
                housing_results.scale = 1
                page.update()
            except ValueError:
                result_upfront.spans[1].text = "Invalid Input"
                page.update()

        calc_btn = ft.ElevatedButton("Calculate Upfront", on_click=on_calculate_click, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))

        housing_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Company / Organization Name (optional)", org_input),
                    field_with_caption("Basic Salary (₦)", salary_input),
                    field_with_caption("Increment Name (e.g. NJIC)", increment_label_input),
                    field_with_caption("Increment (%)", increment_input),
                    field_with_caption("Housing Upfront Rate (%)", rate_input),
                    calc_btn
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=30, tight=True
            ),
            padding=20, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK))
        )

        housing_results = ft.Container(
            content=ft.Column([result_upfront, result_monthly_allowance, ft.Divider(height=1, color="#4B0082"), result_basic, result_increment, result_total], spacing=8, tight=True),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK)),
            scale=1,
            animate_scale=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

        housing_tab_content = ft.Column(
            controls=[housing_form, ft.Container(height=10), housing_results],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # -------------------- SALARY MANAGEMENT TAB --------------------
        sm_last_basic = await load_saved("sm_basic", "")
        sm_last_housing = await load_saved("sm_housing", "")
        sm_last_transport = await load_saved("sm_transport", "")
        sm_last_other = await load_saved("sm_other", "")
        sm_last_rent = await load_saved("sm_rent", "")

        async def sm_on_basic_change(e):
            await prefs.set("sm_basic", sm_basic_input.value)

        async def sm_on_housing_change(e):
            await prefs.set("sm_housing", sm_housing_input.value)

        async def sm_on_transport_change(e):
            await prefs.set("sm_transport", sm_transport_input.value)

        async def sm_on_other_change(e):
            await prefs.set("sm_other", sm_other_input.value)

        async def sm_on_rent_change(e):
            await prefs.set("sm_rent", sm_rent_input.value)

        sm_basic_input = NFTextField(value=sm_last_basic, keyboard_type=ft.KeyboardType.NUMBER, max_length=15, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        sm_basic_input.on_change = with_length_warning(sm_basic_input, 15, sm_on_basic_change)
        sm_housing_input = NFTextField(value=sm_last_housing, keyboard_type=ft.KeyboardType.NUMBER, max_length=15, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        sm_housing_input.on_change = with_length_warning(sm_housing_input, 15, sm_on_housing_change)
        sm_transport_input = NFTextField(value=sm_last_transport, keyboard_type=ft.KeyboardType.NUMBER, max_length=15, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        sm_transport_input.on_change = with_length_warning(sm_transport_input, 15, sm_on_transport_change)
        sm_other_input = NFTextField(value=sm_last_other, keyboard_type=ft.KeyboardType.NUMBER, max_length=15, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        sm_other_input.on_change = with_length_warning(sm_other_input, 15, sm_on_other_change)
        sm_rent_input = NFTextField(value=sm_last_rent, keyboard_type=ft.KeyboardType.NUMBER, max_length=15, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        sm_rent_input.on_change = with_length_warning(sm_rent_input, 15, sm_on_rent_change)

        sm_result_gross = ft.Text(spans=[ft.TextSpan("Gross Pay (Monthly): ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=16)
        sm_result_pension = ft.Text(spans=[ft.TextSpan("Pension (8%): ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_RED, weight=ft.FontWeight.BOLD))], size=14)
        sm_result_nhf = ft.Text(spans=[ft.TextSpan("NHF (2.5%): ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_RED, weight=ft.FontWeight.BOLD))], size=14)
        sm_result_paye = ft.Text(spans=[ft.TextSpan("PAYE Tax: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_RED, weight=ft.FontWeight.BOLD))], size=14)
        sm_result_net = ft.Text(spans=[ft.TextSpan("Net Pay (Monthly): ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=18)
        sm_status_text = ft.Text("", color="white", size=12, text_align=ft.TextAlign.CENTER)

        last_sm_result = {}

        async def sm_on_calculate_click(e):
            try:
                basic = to_number(sm_basic_input.value)
                housing = to_number(sm_housing_input.value)
                transport = to_number(sm_transport_input.value)
                other = to_number(sm_other_input.value)
                annual_rent = to_number(sm_rent_input.value)

                gross_monthly = basic + housing + transport + other
                gross_annual = gross_monthly * 12.0

                pension_basis_annual = (basic + housing + transport) * 12.0
                pension_annual = pension_basis_annual * 0.08
                nhf_annual = (basic * 12.0) * 0.025
                rent_relief = min(annual_rent * 0.20, 500_000.0) if annual_rent > 0 else 0.0

                taxable_annual = max(gross_annual - pension_annual - nhf_annual - rent_relief, 0.0)
                paye_annual = compute_paye_annual(taxable_annual)
                paye_monthly = paye_annual / 12.0

                total_deductions_monthly = (pension_annual / 12.0) + (nhf_annual / 12.0) + paye_monthly
                net_monthly = gross_monthly - total_deductions_monthly

                sm_result_gross.spans[1].text = f"₦{gross_monthly:,.2f}"
                sm_result_pension.spans[1].text = f"₦{pension_annual/12.0:,.2f}"
                sm_result_nhf.spans[1].text = f"₦{nhf_annual/12.0:,.2f}"
                sm_result_paye.spans[1].text = f"₦{paye_monthly:,.2f}"
                sm_result_net.spans[1].text = fmt_money(net_monthly)

                last_sm_result.clear()
                last_sm_result.update({
                    "basic": basic, "housing": housing, "transport": transport, "other": other,
                    "gross_monthly": gross_monthly, "pension_monthly": pension_annual/12.0,
                    "nhf_monthly": nhf_annual/12.0, "paye_monthly": paye_monthly, "net_monthly": net_monthly,
                })
                sm_status_text.value = ""
                sm_results.scale = 0.92
                page.update()
                await asyncio.sleep(0.08)
                sm_results.scale = 1
                page.update()
            except ValueError:
                last_sm_result.clear()  # never Save/Share an old result after a bad entry
                for _r in (sm_result_gross, sm_result_pension, sm_result_nhf, sm_result_paye, sm_result_net):
                    _r.spans[1].text = "—"
                sm_result_gross.spans[1].text = "Invalid Input"
                page.update()

        async def sm_on_save_click(e):
            if not last_sm_result:
                sm_status_text.value = "Please calculate first before saving."
                page.update()
                return
            entry = dict(last_sm_result)
            entry["date"] = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
            try:
                raw = await prefs.get("salary_history")
                history = json.loads(raw) if raw else []
            except Exception:
                history = []
            history.insert(0, entry)
            history = history[:20]
            await prefs.set("salary_history", json.dumps(history))
            sm_status_text.value = "Saved to history."
            page.update()

        async def sm_on_share_click(e):
            if not last_sm_result:
                sm_status_text.value = "Please calculate first before sharing."
                page.update()
                return
            r = last_sm_result
            summary = (
                "Salary Breakdown\n"
                f"Basic Salary: ₦{r['basic']:,.2f}\n"
                f"Housing Allowance: ₦{r['housing']:,.2f}\n"
                f"Transport Allowance: ₦{r['transport']:,.2f}\n"
                f"Other Allowances: ₦{r['other']:,.2f}\n"
                f"Gross Pay (Monthly): ₦{r['gross_monthly']:,.2f}\n"
                f"Pension (8%): ₦{r['pension_monthly']:,.2f}\n"
                f"NHF (2.5%): ₦{r['nhf_monthly']:,.2f}\n"
                f"PAYE Tax: ₦{r['paye_monthly']:,.2f}\n"
                f"Net Pay (Monthly): ₦{r['net_monthly']:,.2f}"
            )
            sm_status_text.value = ""
            page.update()
            share_payslip(dict(r), summary)

        async def sm_show_history(e):
            try:
                raw = await prefs.get("salary_history")
                history = json.loads(raw) if raw else []
            except Exception:
                history = []

            if not history:
                rows = [ft.Text("No saved calculations yet.", color=DARK_TEXT)]
            else:
                rows = []
                for item in history:
                    rows.append(
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text(item.get("date", ""), size=12, color="#666666"),
                                    ft.Text(f"Net Pay: ₦{item.get('net_monthly', 0):,.2f}", weight=ft.FontWeight.BOLD, color=PURPLE_TEXT),
                                    ft.Text(f"Gross: ₦{item.get('gross_monthly', 0):,.2f}  |  PAYE: ₦{item.get('paye_monthly', 0):,.2f}", size=12, color=DARK_TEXT),
                                ],
                                spacing=2,
                            ),
                            padding=10,
                            border=ft.Border(ft.BorderSide(1, "#DDDDDD"), ft.BorderSide(1, "#DDDDDD"), ft.BorderSide(1, "#DDDDDD"), ft.BorderSide(1, "#DDDDDD")),
                            border_radius=8,
                        )
                    )

            async def clear_history(e):
                await prefs.set("salary_history", json.dumps([]))
                page.pop_dialog()

            history_dialog = ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Saved Calculations", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.ListView(controls=rows, spacing=10),
                    width=320,
                    height=350,
                ),
                actions=[
                    ft.TextButton("Clear History", on_click=clear_history, style=ft.ButtonStyle(color="#C62828")),
                    ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(history_dialog)

        sm_calc_btn = ft.ElevatedButton("Calculate Payslip", on_click=sm_on_calculate_click, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))
        sm_save_btn = ft.OutlinedButton(content=ft.Text("Save", color="white", weight=ft.FontWeight.BOLD), on_click=sm_on_save_click, style=ft.ButtonStyle(side=ft.BorderSide(1, "white")))
        sm_history_btn = ft.OutlinedButton(content=ft.Text("History", color="white", weight=ft.FontWeight.BOLD), on_click=sm_show_history, style=ft.ButtonStyle(side=ft.BorderSide(1, "white")))
        sm_share_btn = ft.OutlinedButton(content=ft.Text("Share", color="white", weight=ft.FontWeight.BOLD), on_click=sm_on_share_click, style=ft.ButtonStyle(side=ft.BorderSide(1, "white")))

        sm_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Basic Salary (₦, monthly)", sm_basic_input),
                    field_with_caption("Housing Allowance (₦, monthly)", sm_housing_input),
                    field_with_caption("Transport Allowance (₦, monthly)", sm_transport_input),
                    field_with_caption("Other Allowances (₦, monthly)", sm_other_input),
                    field_with_caption("Annual Rent Paid (₦, optional - for rent relief)", sm_rent_input),
                    sm_calc_btn,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=30, tight=True
            ),
            padding=20, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK))
        )

        sm_results = ft.Container(
            content=ft.Column(
                [
                    sm_result_gross, ft.Divider(height=1, color="#4B0082"),
                    sm_result_pension, sm_result_nhf, sm_result_paye,
                    ft.Divider(height=1, color="#4B0082"),
                    sm_result_net,
                    ft.Row([sm_save_btn, sm_history_btn, sm_share_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=8, wrap=True),
                    sm_status_text,
                ],
                spacing=8, tight=True
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK))
        )

        sm_note = ft.Text(
            "Based on Nigeria Tax Act 2025 (effective Jan 2026): first ₦800k/year tax-free, Pension 8% of Basic+Housing+Transport, NHF 2.5% of Basic. For guidance only — confirm with your HR/tax professional.",
            size=11, color="white", text_align=ft.TextAlign.CENTER, italic=True
        )

        def _source_line(label, url):
            return ft.Text(spans=[
                ft.TextSpan(f"{label}: ", ft.TextStyle(color="white", size=11)),
                ft.TextSpan(url.replace("https://", ""), ft.TextStyle(color="#FFD54F", size=11, weight=ft.FontWeight.BOLD,
                                                                   decoration=ft.TextDecoration.UNDERLINE), url=url),
            ], text_align=ft.TextAlign.CENTER)

        # Google Play requires the official source of any government information (tax/pension/NHF
        # rules) and a clear statement that the app is not a government app.
        sm_sources = ft.Container(
            content=ft.Column([
                ft.Text("Official sources (tap to open)", size=12, color="#FFD700", weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER),
                _source_line("PAYE tax bands – Nigeria Tax Act 2025 (Nigeria Revenue Service)", "https://www.nrs.gov.ng/"),
                _source_line("Pension 8% – Pension Reform Act 2014 (PenCom)", "https://www.pencom.gov.ng/"),
                _source_line("NHF 2.5% – National Housing Fund (FMBN)", "https://www.fmbn.gov.ng/"),
                ft.Text("Naira Finance Hub is an independent app. It is not affiliated with, endorsed by, "
                        "or representing the Nigerian government or any government agency.",
                        size=10, color="white", italic=True, text_align=ft.TextAlign.CENTER),
            ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            padding=10, border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        salary_tab_content = ft.Column(
            controls=[sm_form, ft.Container(height=10), sm_results, sm_note, sm_sources],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # -------------------- MONEY TRACKER TAB --------------------
        CATEGORY_OPTIONS = ["Food", "Transport", "Housing", "Utilities", "Health", "Entertainment", "Salary", "Business", "Miscellaneous", "Fee", "Borrowed", "Other"]
        CATEGORY_ICONS = {
            "Food": ft.Icons.RESTAURANT_ROUNDED,
            "Transport": ft.Icons.DIRECTIONS_CAR_ROUNDED,
            "Housing": ft.Icons.HOME_ROUNDED,
            "Utilities": ft.Icons.BOLT_ROUNDED,
            "Health": ft.Icons.LOCAL_HOSPITAL_ROUNDED,
            "Entertainment": ft.Icons.MOVIE_ROUNDED,
            "Salary": ft.Icons.PAYMENTS_ROUNDED,
            "Business": ft.Icons.BUSINESS_CENTER_ROUNDED,
            "Miscellaneous": ft.Icons.CATEGORY_ROUNDED,
            "Fee": ft.Icons.RECEIPT_LONG_ROUNDED,
            "Borrowed": ft.Icons.HANDSHAKE_ROUNDED,
            "Other": ft.Icons.LABEL_ROUNDED,
        }

        ICON_PALETTE = {
            "Shopping Bag": ft.Icons.SHOPPING_BAG_ROUNDED,
            "Gift": ft.Icons.CARD_GIFTCARD_ROUNDED,
            "Pets": ft.Icons.PETS_ROUNDED,
            "Flight": ft.Icons.FLIGHT_ROUNDED,
            "School": ft.Icons.SCHOOL_ROUNDED,
            "Sports": ft.Icons.SPORTS_BASKETBALL_ROUNDED,
            "Subscription": ft.Icons.SUBSCRIPTIONS_ROUNDED,
            "Phone": ft.Icons.PHONE_ANDROID_ROUNDED,
            "Savings": ft.Icons.SAVINGS_ROUNDED,
            "Fitness": ft.Icons.FITNESS_CENTER_ROUNDED,
            "Coffee": ft.Icons.LOCAL_CAFE_ROUNDED,
            "Car Repair": ft.Icons.CAR_REPAIR_ROUNDED,
            "Beauty": ft.Icons.SPA_ROUNDED,
            "Book": ft.Icons.MENU_BOOK_ROUNDED,
            "Child": ft.Icons.CHILD_CARE_ROUNDED,
            "Church": ft.Icons.CHURCH_ROUNDED,
            "Wifi": ft.Icons.WIFI_ROUNDED,
            "Insurance": ft.Icons.SECURITY_ROUNDED,
            "Tools": ft.Icons.BUILD_ROUNDED,
            "Music": ft.Icons.MUSIC_NOTE_ROUNDED,
            "Party": ft.Icons.CELEBRATION_ROUNDED,
            "Home Repair": ft.Icons.HANDYMAN_ROUNDED,
            "Wallet": ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED,
            "Star": ft.Icons.STAR_ROUNDED,
        }

        async def load_category_changes():
            try:
                raw = await prefs.get("category_changes")
                return json.loads(raw) if raw else {"added": {}, "removed": []}
            except Exception:
                return {"added": {}, "removed": []}

        async def save_category_changes(changes):
            await prefs.set("category_changes", json.dumps(changes))

        async def apply_saved_category_changes():
            changes = await load_category_changes()
            for removed_name in changes.get("removed", []):
                if removed_name != "Other" and removed_name in CATEGORY_OPTIONS:
                    CATEGORY_OPTIONS.remove(removed_name)
                CATEGORY_ICONS.pop(removed_name, None)
            for name, icon_key in changes.get("added", {}).items():
                if name not in CATEGORY_OPTIONS:
                    CATEGORY_OPTIONS.append(name)
                CATEGORY_ICONS[name] = ICON_PALETTE.get(icon_key, ft.Icons.LABEL_ROUNDED)

        await apply_saved_category_changes()

        def category_icon(cat):
            return CATEGORY_ICONS.get(cat, ft.Icons.LABEL_ROUNDED)


        def category_dropdown_options():
            return [
                ft.dropdown.Option(key=c, text=c)
                for c in CATEGORY_OPTIONS
            ]

        # -------------------- PROFILES --------------------
        PROFILE_COUNT = 3
        active_profile_state = {"value": 1}
        profile_names_state = {}

        async def load_active_profile():
            try:
                raw = await prefs.get("active_profile")
                return int(raw) if raw else 1
            except Exception:
                return 1

        async def save_active_profile(profile_num):
            await prefs.set("active_profile", str(profile_num))

        async def load_profile_names():
            try:
                raw = await prefs.get("profile_names")
                names = json.loads(raw) if raw else {}
            except Exception:
                names = {}
            for i in range(1, PROFILE_COUNT + 1):
                if str(i) not in names:
                    names[str(i)] = f"Profile {i}"
            return names

        async def save_profile_names(names):
            await prefs.set("profile_names", json.dumps(names))

        def profile_key(base_key):
            return f"{base_key}_{active_profile_state['value']}"

        async def load_transactions():
            try:
                raw = await prefs.get(profile_key("money_transactions"))
                return json.loads(raw) if raw else []
            except Exception:
                return []

        async def save_transactions(transactions):
            await prefs.set(profile_key("money_transactions"), json.dumps(transactions))

        # -------------------- AUTOMATED CAPTURE (banking SMS/app notifications, personal build only) --------------------
        NOTIF_DATA_DIR = f"/storage/emulated/0/Android/data/{current_package_name()}/files"
        NOTIF_INBOX_FILE = f"{NOTIF_DATA_DIR}/notification_inbox.jsonl"
        NOTIF_SEEN_PACKAGES_FILE = f"{NOTIF_DATA_DIR}/seen_packages.json"
        NOTIF_ALLOWLIST_FILE = f"{NOTIF_DATA_DIR}/allowed_packages.txt"
        NOTIF_RECENT_FILE = f"{NOTIF_DATA_DIR}/recent_captures.json"
        NOTIF_PROCESSED_FILE = f"{NOTIF_DATA_DIR}/processed_hashes.json"
        CHAT_APP_HINTS = ("whatsapp", "facebook", "instagram", "telegram", "snapchat", "twitter",
                          "tiktok", "musically", "orca", "barcelona", "discord", "imo")
        notif_sync_state = {"added": 0, "skipped": 0, "dupes": 0, "last_run": "never"}

        # The old tick-box allow-list could silently block SMS; it's retired.
        try:
            if os.path.exists(NOTIF_ALLOWLIST_FILE):
                os.remove(NOTIF_ALLOWLIST_FILE)
        except Exception:
            pass

        def _read_json(path, default):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return default

        def _write_json(path, data):
            try:
                os.makedirs(NOTIF_DATA_DIR, exist_ok=True)
                with open(path, "w") as f:
                    json.dump(data, f)
            except Exception:
                pass

        def _load_seen_packages():
            return _read_json(NOTIF_SEEN_PACKAGES_FILE, {})

        def _pick_category(hints):
            for c in hints or ():
                if c in CATEGORY_OPTIONS:
                    return c
            return "Other"

        def _is_chat_app(pkg):
            p = (pkg or "").lower()
            return any(h in p for h in CHAT_APP_HINTS)

        def _is_sms_app(pkg):
            p = (pkg or "").lower()
            return "messag" in p or "sms" in p or "mms" in p

        # -------- Your own "alert text -> category" rules (set from the app, no coding) --------
        # Stored as [{"keyword": "MOB TOPUP", "category": "Airtime"}, ...]. A rule matches when
        # every word of its keyword appears somewhere in the alert, in any order or case.
        ALERT_RULES_KEY = "alert_category_rules"

        async def load_alert_rules():
            try:
                raw = await prefs.get(ALERT_RULES_KEY)
                rules = json.loads(raw) if raw else []
                return [r for r in rules if r.get("keyword") and r.get("category")]
            except Exception:
                return []

        async def save_alert_rules(rules):
            await prefs.set(ALERT_RULES_KEY, json.dumps(rules))

        def _rule_words(keyword):
            return [w for w in re.split(r"[\s|]+", (keyword or "").upper()) if w]

        def rule_category_for(text, rules):
            upper = (text or "").upper()
            best, best_len = None, 0
            for r in rules:
                words = _rule_words(r.get("keyword"))
                if words and all(w in upper for w in words) and r.get("category") in CATEGORY_OPTIONS:
                    length = sum(len(w) for w in words)  # the most specific rule wins
                    if length > best_len:
                        best, best_len = r["category"], length
            return best

        def suggest_alert_keyword(text):
            # "Auto: MOB TOPUP 08031234567" -> "MOB TOPUP" (drops numbers / references).
            t = re.sub(r"^\s*Auto:\s*", "", text or "", flags=re.IGNORECASE)
            words = [w for w in re.split(r"[\s|/@,:]+", t)
                     if len(w) >= 3 and not any(ch.isdigit() for ch in w)]
            return " ".join(words[:2]).upper()[:30]

        async def add_alert_rule(keyword, category):
            """Saves the rule and re-files matching auto-added transactions. Returns how many moved."""
            keyword = " ".join(_rule_words(keyword))
            if not keyword or category not in CATEGORY_OPTIONS:
                return 0
            rules = [r for r in await load_alert_rules() if " ".join(_rule_words(r["keyword"])) != keyword]
            rules.append({"keyword": keyword, "category": category})
            await save_alert_rules(rules)
            transactions = await load_transactions()
            moved = 0
            for t in transactions:
                note = t.get("note", "") or ""
                if note.startswith("Auto:") and t.get("category") != category \
                        and rule_category_for(note, [{"keyword": keyword, "category": category}]):
                    t["category"] = category
                    moved += 1
            if moved:
                await save_transactions(transactions)
            return moved

        async def open_alert_rules_dialog(e=None):
            rules_col = ft.Column([], spacing=4, tight=True)
            kw_tf = NFTextField(label="Alert contains (e.g. MOB TOPUP)", dense=True, text_size=13,
                                 color=PURPLE_TEXT, capitalization=ft.TextCapitalization.CHARACTERS, max_length=30)
            cat_dd = ft.Dropdown(label="Put it in category", value="Other", options=category_dropdown_options(),
                                 dense=True, text_size=13, color=PURPLE_TEXT)
            msg = ft.Text("", size=11, color="#2E7D32")

            async def render_rules():
                rules = await load_alert_rules()
                rows = []
                for r in rules:
                    def make_del(kw):
                        async def _del(ev):
                            await save_alert_rules([x for x in await load_alert_rules() if x["keyword"] != kw])
                            msg.value = f"Removed rule for “{kw}”."
                            await render_rules()
                            page.update()
                        return _del
                    rows.append(ft.Row([
                        ft.Text(f"“{r['keyword']}”  →  {r['category']}", size=12, color=PURPLE_TEXT,
                                weight=ft.FontWeight.BOLD, expand=True),
                        ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_del(r["keyword"])),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER))
                rules_col.controls = rows or [ft.Text("No rules yet.", size=12, color="#757575")]

            async def add_rule(ev):
                if not (kw_tf.value or "").strip():
                    msg.color = "#C62828"
                    msg.value = "Type a word from the alert first."
                    page.update()
                    return
                moved = await add_alert_rule(kw_tf.value, cat_dd.value or "Other")
                msg.color = "#2E7D32"
                msg.value = f"Saved. {moved} earlier auto-added item(s) moved to {cat_dd.value}." if moved else "Saved."
                kw_tf.value = ""
                await render_rules()
                await refresh_money_ui()
                page.update()

            await render_rules()
            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Alert Category Rules", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(content=ft.Column([
                    ft.Text("When a bank alert contains these words, it goes into the chosen category. "
                            "Example: “MOB TOPUP” → Airtime.", size=12, color="#555555"),
                    kw_tf, cat_dd, msg,
                    ft.Divider(height=1, color="#DDDDDD"),
                    ft.Text("Your rules", size=13, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    rules_col,
                ], spacing=8, tight=True), width=300),
                actions=[
                    ft.TextButton("Close", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.ElevatedButton("Add Rule", on_click=add_rule, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        ingest_lock = asyncio.Lock()

        async def ingest_pending_notifications():
            # One run at a time: two overlapping runs could each load the transactions list
            # and the second save would wipe what the first one added.
            if ingest_lock.locked():
                return
            async with ingest_lock:
                await _ingest_pending_notifications()

        def _read_inbox_tail(path, max_bytes=8_000_000):
            """Reads the inbox (at most its last 8 MB). Bank/SMS lines are all kept (up to 800);
            chat-app lines, which are only shown in the "All apps" log, are cut to the newest 60."""
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - max_bytes))
                data = f.read()
            text = data.decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if size > max_bytes and lines:
                lines = lines[1:]  # first line may be cut in half
            def _pkg_of(ln):
                m = re.search(r'"package"\s*:\s*"([^"]*)"', ln[:200])
                return m.group(1) if m else ""
            chat_idx = [i for i, ln in enumerate(lines) if _is_chat_app(_pkg_of(ln))]
            keep_chat = set(chat_idx[-60:])
            chat_set = set(chat_idx)
            other_idx = [i for i in range(len(lines)) if i not in chat_set][-800:]
            keep = sorted(set(other_idx) | keep_chat)
            return [lines[i] for i in keep]

        def _process_inbox_sync(alert_rules):
            """All the slow work (file reading, parsing, regexes, saving the log files).
            Runs in a background thread so the screen never freezes while alerts are read.
            Returns (new_transactions, added, skipped, dupes) or None if there was nothing to do."""
            if not (os.path.exists(NOTIF_INBOX_FILE) or os.path.exists(NOTIF_INBOX_FILE + ".processing")):
                return None
            # Move the inbox aside first: the listener then starts a fresh file, so an alert
            # that arrives while we are reading can't be wiped by the clean-up.
            processing = NOTIF_INBOX_FILE + ".processing"
            try:
                if not os.path.exists(processing):
                    os.replace(NOTIF_INBOX_FILE, processing)
                lines = _read_inbox_tail(processing)
            except Exception:
                lines = []
            try:
                os.remove(processing)  # always clear it, so a bad file can't block every future check
            except Exception:
                pass
            if not lines:
                return None

            seen = _load_seen_packages()
            recent = _read_json(NOTIF_RECENT_FILE, [])
            processed = _read_json(NOTIF_PROCESSED_FILE, [])
            processed_set = set(processed)
            new_txns = []
            added = skipped = dupes = 0
            latest = 0

            for line in lines:
                try:
                    raw = json.loads(line)
                except Exception:
                    continue  # a half-written line must never lose the rest of the batch
                pkg = raw.get("package", "") or ""
                title = (raw.get("title", "") or "")[:200]
                text = (raw.get("text", "") or "")[:1500]  # bank alerts are short; cap huge chat texts
                try:
                    posted_at = int(raw.get("posted_at", 0) or 0)
                except Exception:
                    posted_at = 0
                latest = max(latest, posted_at)

                info = seen.get(pkg, {"count": 0, "sample": ""})
                info["count"] = info.get("count", 0) + 1
                info["sample"] = (title or text)[:60]
                seen[pkg] = info

                # Messaging apps re-post the same notification when a conversation updates.
                legacy_key = f"{pkg}|{title}|{text}"
                key = hashlib.md5(legacy_key.encode("utf-8", "ignore")).hexdigest()[:16]
                if key in processed_set or legacy_key in processed_set:
                    dupes += 1
                    continue
                processed_set.add(key)
                processed.append(key)

                # Chat apps never carry bank alerts: log them for "All apps" but skip the parser.
                if _is_chat_app(pkg):
                    recent.insert(0, {
                        "id": key + str(posted_at),
                        "time": (datetime.datetime.fromtimestamp(posted_at / 1000) if posted_at else datetime.datetime.now()).strftime("%d %b %H:%M"),
                        "package": pkg, "title": title[:40], "text": text[:220],
                        "date": datetime.date.today().isoformat(), "direction": "unknown", "amount": None,
                        "category": "Other", "note": (title or pkg)[:60], "status": "ignored",
                    })
                    skipped += 1
                    continue

                try:
                    when = datetime.datetime.fromtimestamp(posted_at / 1000) if posted_at else datetime.datetime.now()
                except Exception:
                    when = datetime.datetime.now()
                entry_date = when.date().isoformat()
                entry_time = when.strftime("%H:%M")

                try:
                    txn = parse_bank_notification(package=pkg, title=title, text=text, posted_at=posted_at)
                except Exception:
                    txn = None

                rec = {
                    "id": key + str(posted_at),
                    "time": when.strftime("%d %b %H:%M"),
                    "hm": entry_time,
                    "package": pkg, "title": title[:40], "text": text[:220],
                    "date": entry_date,
                    "direction": getattr(txn, "direction", "unknown") if txn else "unknown",
                    "amount": getattr(txn, "amount", None) if txn else None,
                    "category": _pick_category(getattr(txn, "category_hints", ())) if txn else "Other",
                    "note": ((getattr(txn, "counterparty", None) if txn else None) or title or pkg)[:60],
                    "status": "ignored",
                }
                ruled = rule_category_for(f"{title} {text}", alert_rules)
                if ruled:
                    rec["category"] = ruled  # your own rule beats the built-in guess

                if (txn is not None and getattr(txn, "strict", False) and txn.amount is not None
                        and txn.direction in ("credit", "debit")):
                    base_amt, fee_amt = (split_transfer_fee(txn.amount, f"{title} {text}")
                                         if txn.direction == "debit" else (txn.amount, 0.0))
                    new_txns.append({
                        "type": "income" if txn.direction == "credit" else "expense",
                        "category": rec["category"],
                        "amount": base_amt,
                        "charge": fee_amt,
                        "note": f"Auto: {rec['note']}",
                        "date": entry_date,
                        "time": entry_time,
                    })
                    rec["status"] = "added"
                    added += 1
                else:
                    if _is_sms_app(pkg) and "hidden" in text.lower() and len(text) < 80:
                        rec["status"] = "hidden"
                    elif rec["amount"] is not None:
                        rec["status"] = "possible"
                    skipped += 1

                recent.insert(0, rec)

            if latest:
                seen["_last_capture_ms"] = max(latest, seen.get("_last_capture_ms", 0))
            _write_json(NOTIF_SEEN_PACKAGES_FILE, seen)
            _write_json(NOTIF_RECENT_FILE, recent[:40])
            _write_json(NOTIF_PROCESSED_FILE, processed[-1500:])
            return new_txns, added, skipped, dupes

        async def _ingest_pending_notifications():
            if parse_bank_notification is None:
                return
            if not (os.path.exists(NOTIF_INBOX_FILE) or os.path.exists(NOTIF_INBOX_FILE + ".processing")):
                return
            alert_rules = await load_alert_rules()
            try:
                result = await asyncio.to_thread(_process_inbox_sync, alert_rules)
            except Exception:
                return
            if not result:
                return
            new_txns, added, skipped, dupes = result
            notif_sync_state.update(added=added, skipped=skipped, dupes=dupes,
                                    last_run=datetime.datetime.now().strftime("%H:%M:%S"))
            if new_txns:
                # Load the list only now, right before saving, so nothing typed meanwhile is lost.
                transactions = await load_transactions()
                for t in new_txns:  # newest alert ends up on top
                    transactions.insert(0, t)
                await save_transactions(transactions[:10000])

        async def open_notification_sync_dialog(e):
            status_text = ft.Text("", size=12, color=DARK_TEXT, weight=ft.FontWeight.BOLD)
            health_col = ft.Column([], spacing=2, tight=True)

            def render_health():
                rows = []
                if parse_bank_notification is None:
                    rows.append(ft.Text("✗ Bank-alert reader not loaded — bank_notification_parser.py is missing from "
                                        f"the app or has an error ({PARSER_LOAD_ERROR}). Nothing can be added until it's fixed.",
                                        size=11, color="#C62828", weight=ft.FontWeight.BOLD, selectable=True))
                else:
                    rows.append(ft.Text("✓ Bank-alert reader loaded", size=11, color="#2E7D32"))
                newest = 0
                for f in (NOTIF_INBOX_FILE, NOTIF_INBOX_FILE + ".processing"):
                    try:
                        newest = max(newest, os.path.getmtime(f) * 1000)
                    except OSError:
                        pass
                newest = max(newest, _load_seen_packages().get("_last_capture_ms", 0))
                if newest:
                    when = datetime.datetime.fromtimestamp(newest / 1000)
                    hours = (datetime.datetime.now() - when).total_seconds() / 3600
                    ago = f"{int(hours * 60)} min ago" if hours < 1 else f"{hours:.0f} h ago"
                    ok = hours < 2
                    rows.append(ft.Text(f"{'✓' if ok else '✗'} Listener's last capture: {when.strftime('%d %b %H:%M')} ({ago})",
                                        size=11, color="#2E7D32" if ok else "#C62828", weight=ft.FontWeight.BOLD))
                    if not ok:
                        rows.append(ft.Text("No alert captured for a while. If you did receive bank SMS in that time, the phone "
                                            "put the listener to sleep. Close this app fully and open it again (it reconnects "
                                            "itself on start). If that doesn't help: Settings → Notification access → turn "
                                            "Naira Finance Hub OFF, then ON. To stop it happening: Settings → Battery → "
                                            "App launch → Naira Finance Hub → Manage manually, with all 3 switches ON.",
                                            size=11, color="#C62828"))
                else:
                    rows.append(ft.Text("✗ The listener hasn't captured anything yet. Check Notification access is ON, "
                                        "then turn it OFF and ON again.", size=11, color="#C62828"))
                health_col.controls = rows
            error_text = ft.Text("", size=11, color="#C62828", selectable=True)
            log_view = ft.ListView(spacing=6)
            show_all = {"value": False}
            editing = {"id": None}

            def _mark_added(rec_id):
                recent = _read_json(NOTIF_RECENT_FILE, [])
                for r in recent:
                    if r.get("id") == rec_id:
                        r["status"] = "added_manual"
                _write_json(NOTIF_RECENT_FILE, recent)

            def build_add_form(r):
                type_dd = ft.Dropdown(
                    label="Type", value="income" if r.get("direction") == "credit" else "expense",
                    options=[ft.dropdown.Option(key="income", text="Income"), ft.dropdown.Option(key="expense", text="Expense")],
                    dense=True, text_size=13, color=PURPLE_TEXT,
                )
                amt = r.get("amount")
                amount_tf = NFTextField(label="Amount (₦)", value=(f"{amt:.2f}" if amt is not None else ""),
                                         keyboard_type=ft.KeyboardType.NUMBER, dense=True, text_size=13, color=PURPLE_TEXT)
                cat = r.get("category") if r.get("category") in CATEGORY_OPTIONS else "Other"
                cat_dd = ft.Dropdown(label="Category", value=cat, options=category_dropdown_options(),
                                     dense=True, text_size=13, color=PURPLE_TEXT)
                note_tf = NFTextField(label="Note", value=r.get("note", ""), dense=True, text_size=13, color=PURPLE_TEXT)
                form_err = ft.Text("", size=11, color="#C62828")
                remember_cb = ft.Checkbox(label="Always use this category for alerts containing:", value=False,
                                          label_style=ft.TextStyle(size=12, color=PURPLE_TEXT))
                remember_tf = NFTextField(value=suggest_alert_keyword(r.get("note", "") or r.get("text", "")),
                                           dense=True, text_size=13, color=PURPLE_TEXT,
                                           capitalization=ft.TextCapitalization.CHARACTERS, max_length=30)

                async def save(ev):
                    try:
                        amount = float((amount_tf.value or "").replace(",", "").strip())
                    except ValueError:
                        form_err.value = "Enter a valid amount."
                        page.update()
                        return
                    transactions = await load_transactions()
                    transactions.insert(0, {
                        "type": type_dd.value or "expense",
                        "category": cat_dd.value or "Other",
                        "amount": amount,
                        "charge": 0.0,
                        "note": (note_tf.value or "").strip()[:100],
                        "date": r.get("date") or datetime.date.today().isoformat(),
                        **({"time": r["hm"]} if r.get("hm") else {}),
                    })
                    await save_transactions(transactions[:10000])
                    if remember_cb.value and (remember_tf.value or "").strip():
                        await add_alert_rule(remember_tf.value, cat_dd.value or "Other")
                    _mark_added(r.get("id"))
                    editing["id"] = None
                    await refresh_money_ui()
                    render()
                    page.update()

                def cancel(ev):
                    editing["id"] = None
                    render()
                    page.update()

                return ft.Column([
                    type_dd, amount_tf, cat_dd, note_tf, remember_cb, remember_tf, form_err,
                    ft.Row([
                        ft.TextButton("Cancel", on_click=cancel, style=ft.ButtonStyle(color="#757575")),
                        ft.ElevatedButton("Save to Money Tracker", on_click=save,
                                          style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                    ], alignment=ft.MainAxisAlignment.END, wrap=True),
                ], spacing=6, tight=True)

            def render():
                s = notif_sync_state
                status_text.value = (f"Last check {s['last_run']}: {s['added']} added, "
                                     f"{s['skipped']} not added, {s['dupes']} repeats")
                recent = _read_json(NOTIF_RECENT_FILE, [])
                if not show_all["value"]:
                    recent = [r for r in recent if r.get("status") in ("added", "added_manual", "possible", "hidden")
                              or _is_sms_app(r.get("package", ""))]
                labels = {
                    "added": ("Added automatically", "#2E7D32"),
                    "added_manual": ("Added by you", "#2E7D32"),
                    "possible": ("Possible transaction — tap + Add if correct", "#E65100"),
                    "hidden": ("Text hidden by Android", "#C62828"),
                    "ignored": ("Not added", "#757575"),
                }
                rows = []
                for r in recent[:30]:
                    st = r.get("status", "ignored")
                    label, color = labels.get(st, labels["ignored"])
                    if st in ("added", "added_manual") and r.get("amount") is not None:
                        kind = "income" if r.get("direction") == "credit" else "expense"
                        label = f"{label}: {kind} ₦{r['amount']:,.2f} · {r.get('category', 'Other')}"

                    parts = [
                        ft.Text(f"{r.get('time','')}  ·  {r.get('title','') or r.get('package','')}", size=12, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        ft.Text(r.get("text", ""), size=11, color=DARK_TEXT, selectable=True),
                    ]
                    if editing["id"] == r.get("id"):
                        parts.append(build_add_form(r))
                    else:
                        status_row = [ft.Text(label, size=11, color=color, weight=ft.FontWeight.BOLD, expand=True)]
                        if st not in ("added", "added_manual"):
                            def make_open(rid):
                                def _open(ev):
                                    editing["id"] = rid
                                    render()
                                    page.update()
                                return _open
                            status_row.append(ft.TextButton("+ Add", on_click=make_open(r.get("id")),
                                                            style=ft.ButtonStyle(color="#2E8B57")))
                        parts.append(ft.Row(status_row, vertical_alignment=ft.CrossAxisAlignment.CENTER))
                    rows.append(ft.Container(content=ft.Column(parts, spacing=2, tight=True),
                                             padding=8, border_radius=8, bgcolor="#F3EEF8"))
                if not rows:
                    rows = [ft.Text(
                        "Nothing captured from SMS yet. Wait for a bank alert, then tap Check now.\n\n"
                        "If this stays empty: Settings → Notification access → Naira Finance Hub must be ON.",
                        size=12, color="#555555")]
                log_view.controls = rows
                render_health()
                toggle_btn.content = "SMS/bank only" if show_all["value"] else "All apps"

            async def check_now(ev):
                try:
                    await ingest_pending_notifications()
                    await refresh_money_ui()
                    error_text.value = ""
                except Exception as ex:
                    error_text.value = f"Error: {ex}"
                render()
                page.update()

            def toggle_all(ev):
                show_all["value"] = not show_all["value"]
                render()
                page.update()

            def clear_log(ev):
                _write_json(NOTIF_RECENT_FILE, [])
                render()
                page.update()

            small = dict(padding=ft.Padding(left=8, right=8, top=0, bottom=0))
            toggle_btn = ft.TextButton("All apps", on_click=toggle_all, style=ft.ButtonStyle(color="#1E88E5", **small))

            try:
                await ingest_pending_notifications()
                await refresh_money_ui()
            except Exception as ex:
                error_text.value = f"Error: {ex}"
            render()

            page.show_dialog(ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Notification Sync", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=20),
                content=ft.Container(
                    content=ft.Column([
                        ft.Text("UBA/FCMB alerts are added automatically. Anything else: tap + Add.",
                                size=12, color="#555555"),
                        health_col,
                        status_text,
                        error_text,
                        ft.Row([
                            ft.TextButton("Check now", on_click=check_now, style=ft.ButtonStyle(color="#2E8B57", **small)),
                            toggle_btn,
                            ft.TextButton("Clear log", on_click=clear_log, style=ft.ButtonStyle(color="#C62828", **small)),
                            ft.TextButton("Category rules", on_click=open_alert_rules_dialog,
                                          style=ft.ButtonStyle(color=PURPLE_TEXT, **small)),
                        ], wrap=True, spacing=0),
                        ft.Divider(height=1, color="#DDDDDD"),
                        ft.Container(content=log_view, height=360),
                    ], spacing=6, tight=True),
                    width=310,
                ),
                actions=[ft.TextButton("Close", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        # -------------------- CATEGORY BUDGETS (per profile; category list itself is shared) --------------------
        async def load_budgets():
            try:
                raw = await prefs.get(profile_key("category_budgets"))
                return json.loads(raw) if raw else {}
            except Exception:
                return {}

        async def save_budgets(budgets):
            await prefs.set(profile_key("category_budgets"), json.dumps(budgets))

        # -------------------- REPEATING ENTRIES (per profile) --------------------
        # e.g. rent, salary, subscriptions: added by the app itself every month on the chosen day.
        async def load_recurring(profile_num=None):
            try:
                raw = await prefs.get(f"recurring_rules_{profile_num or active_profile_state['value']}")
                rules = json.loads(raw) if raw else []
                return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []
            except Exception:
                return []

        async def save_recurring(rules, profile_num=None):
            await prefs.set(f"recurring_rules_{profile_num or active_profile_state['value']}", json.dumps(rules))

        async def apply_recurring_all():
            """Adds every repeating entry that has fallen due, in all profiles. Returns how many were added."""
            added = 0
            today_d = datetime.date.today()
            for i in range(1, PROFILE_COUNT + 1):
                rules = await load_recurring(i)
                if not rules:
                    continue
                new_entries = []
                for r in rules:
                    for due in recurring_due_dates(r, today_d):
                        r["last_added"] = f"{due.year:04d}-{due.month:02d}"
                        try:
                            amount = float(r.get("amount", 0) or 0)
                        except (TypeError, ValueError):
                            amount = 0.0
                        if amount <= 0:
                            continue
                        new_entries.append({
                            "type": "income" if r.get("type") == "income" else "expense",
                            "category": r.get("category", "Other") or "Other",
                            "amount": amount,
                            "charge": 0.0,
                            "note": (r.get("note") or "").strip() or "Repeating entry",
                            "date": due.isoformat(),
                            "repeat": True,
                        })
                if not new_entries:
                    continue
                key = f"money_transactions_{i}"
                try:
                    raw = await prefs.get(key)
                    full = json.loads(raw) if raw else []
                except Exception:
                    full = None  # couldn't read the list: don't risk overwriting it
                if full is None or not isinstance(full, list):
                    continue
                new_entries.sort(key=lambda t: t["date"], reverse=True)
                await prefs.set(key, json.dumps((new_entries + full)[:10000]))
                await save_recurring(rules, i)
                added += len(new_entries)
            return added

        # -------------------- QUICK ADD SHORTCUTS (per profile) --------------------
        async def load_quick_add():
            try:
                raw = await prefs.get(profile_key("quick_add_shortcuts"))
                return json.loads(raw) if raw else []
            except Exception:
                return []

        async def save_quick_add(shortcuts):
            await prefs.set(profile_key("quick_add_shortcuts"), json.dumps(shortcuts))

        def open_budget_dialog():
            budget_category_picker, budget_category_state = build_category_picker("Food")
            budget_amount_input = NFTextField(
                keyboard_type=ft.KeyboardType.NUMBER, max_length=15,
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                hint_text="e.g. 50000",
            )
            budget_amount_input.on_change = with_length_warning(budget_amount_input, 15)
            budget_error_text = ft.Text("", color="red", size=12)

            async def save_budget(e):
                try:
                    amount = to_number(budget_amount_input.value, required=True)
                except (ValueError, TypeError):
                    budget_error_text.value = "Enter a valid amount."
                    page.update()
                    return
                budgets = await load_budgets()
                budgets[budget_category_state["value"]] = amount
                await save_budgets(budgets)
                page.pop_dialog()
                await refresh_money_ui()

            async def remove_budget(e):
                budgets = await load_budgets()
                budgets.pop(budget_category_state["value"], None)
                await save_budgets(budgets)
                page.pop_dialog()
                await refresh_money_ui()

            dlg = ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Set Monthly Budget", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Set a monthly spending limit for a category. You'll get a visual warning as you approach or exceed it.", color=DARK_TEXT, size=12),
                            field_with_caption("Category", budget_category_picker, on_white=True),
                            field_with_caption("Monthly Limit (₦)", budget_amount_input, on_white=True),
                            budget_error_text,
                        ],
                        tight=True, spacing=15,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Remove Budget", on_click=remove_budget, style=ft.ButtonStyle(color="#C62828")),
                    ft.TextButton("Save", on_click=save_budget, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        def find_txn_index(full, idx, entry):
            """Where `entry` is now in the saved list — or -1 if it's gone. Never trusts the old
            position alone, so a double tap or an alert arriving meanwhile can't hit the wrong row."""
            if 0 <= idx < len(full) and full[idx] == entry:
                return idx
            for i, t in enumerate(full):
                if t == entry:
                    return i
            return -1

        txn_busy = {"value": False}

        def show_undo_snackbar(deleted_entry, original_pos=0):
            undo_state = {"handled": False}
            deleted_from_key = profile_key("money_transactions")  # Undo puts it back in the SAME profile

            async def handle_undo(e):
                if undo_state["handled"]:
                    return
                undo_state["handled"] = True
                try:
                    raw = await prefs.get(deleted_from_key)
                    full = json.loads(raw) if raw else []
                except Exception:
                    full = []
                if deleted_entry in full:
                    return  # already back (e.g. restored from a backup in the meantime)
                full.insert(max(0, min(original_pos, len(full))), deleted_entry)
                await prefs.set(deleted_from_key, json.dumps(full))
                await refresh_money_ui()
                page.update()

            try:
                snack = ft.SnackBar(
                    ft.Text("Transaction deleted", color="white"),
                    action=ft.SnackBarAction(label="Undo", text_color="#FFD54F", on_click=handle_undo),
                    on_action=handle_undo,  # (only one of the two runs: handle_undo ignores a second call)
                    # Newer Android versions keep a message with a button on screen forever unless told
                    # otherwise; this makes it go away after 3 seconds like other messages.
                    persist=False,
                    duration=ft.Duration(seconds=3),
                    bgcolor=PURPLE_TEXT,
                    behavior=ft.SnackBarBehavior.FLOATING,
                    margin=ft.Margin.only(bottom=300, left=10, right=10),
                )
                page.show_dialog(snack)
            except Exception:
                mt_status_text.value = "Transaction deleted."
                page.update()

        # -------------------- PDF LOG BOOK EXPORT --------------------
        def build_transactions_pdf_bytes(title, txn_list):
            pdf, PF = make_pdf()
            pdf.add_page()
            pdf.set_font(PF, "B", 16)
            pdf.cell(0, 10, "Naira Finance Hub", ln=True, align="C")
            pdf.set_font(PF, "", 12)
            pdf.cell(0, 8, pdf_text(title, PF), ln=True, align="C")
            pdf.ln(4)

            total_income = sum(t["amount"] for t in txn_list if t["type"] == "income")
            total_expense = sum(t["amount"] for t in txn_list if t["type"] == "expense")
            total_charges = sum(t.get("charge", 0.0) or 0.0 for t in txn_list)
            net = total_income - total_expense - total_charges

            pdf.set_font(PF, "B", 11)
            pdf.cell(0, 7, f"Total Income: NGN {total_income:,.2f}", ln=True)
            pdf.cell(0, 7, f"Total Expense: NGN {total_expense:,.2f}", ln=True)
            pdf.cell(0, 7, f"Total Bank Charges: NGN {total_charges:,.2f}", ln=True)
            pdf.cell(0, 7, f"Net: NGN {net:,.2f}", ln=True)
            pdf.ln(6)

            pdf.set_font(PF, "B", 10)
            pdf.set_fill_color(230, 230, 230)
            pdf.cell(25, 8, "Date", border=1, fill=True)
            pdf.cell(20, 8, "Type", border=1, fill=True)
            pdf.cell(35, 8, "Category", border=1, fill=True)
            pdf.cell(65, 8, "Note", border=1, fill=True)
            pdf.cell(35, 8, "Amount", border=1, fill=True, ln=True)

            pdf.set_font(PF, "", 9)
            sorted_txns = sorted(txn_list, key=lambda t: t.get("date", ""))
            for t in sorted_txns:
                sign = "+" if t["type"] == "income" else "-"
                note = pdf_text((t.get("note", "") or "-"), PF)[:35]
                pdf.cell(25, 7, pdf_text(t.get("date", ""), PF), border=1)
                pdf.cell(20, 7, t["type"].capitalize(), border=1)
                pdf.cell(35, 7, pdf_text(t.get("category", "Other"), PF)[:20], border=1)
                pdf.cell(65, 7, note, border=1)
                pdf.cell(35, 7, f"{sign}NGN {t['amount']:,.2f}", border=1, ln=True)

            return bytes(pdf.output())

        pdf_file_picker = ft.FilePicker()
        # While you are away in the phone's file chooser or share sheet, the app lock (PIN) must
        # not treat it as "left the app" and cover the screen the moment you come back.
        external_busy = {"n": 0, "until": 0.0}

        async def picker_save_file(**kwargs):
            external_busy["n"] += 1
            try:
                return await pdf_file_picker.save_file(**kwargs)
            finally:
                external_busy["n"] -= 1
                external_busy["until"] = time.time() + 5

        async def picker_pick_files(**kwargs):
            external_busy["n"] += 1
            try:
                return await pdf_file_picker.pick_files(**kwargs)
            finally:
                external_busy["n"] -= 1
                external_busy["until"] = time.time() + 5
        page.services.append(pdf_file_picker)

        async def export_month_pdf(e):
            transactions = await load_transactions()
            view_year = current_view_date["year"]
            view_month = current_view_date["month"]
            month_txns = []
            for t in transactions:
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year and d.month == view_month:
                    month_txns.append(t)

            month_name = datetime.date(view_year, view_month, 1).strftime("%B %Y")
            active_name = profile_names_state.get(str(active_profile_state["value"]), f"Profile {active_profile_state['value']}")
            try:
                pdf_bytes = build_transactions_pdf_bytes(f"Monthly Log - {active_name} - {month_name}", month_txns)
            except Exception as ex:
                mt_status_text.value = f"Couldn't create the PDF ({type(ex).__name__}). Please try again."
                page.update()
                return
            file_path = await picker_save_file(
                dialog_title="Save Monthly Log",
                file_name=f"NairaFinanceHub_{safe_filename(active_name)}_{safe_filename(month_name)}.pdf",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["pdf"],
                src_bytes=pdf_bytes,
            )
            mt_status_text.value = "Monthly log saved!" if file_path else "Save cancelled."
            page.update()

        async def export_year_pdf(e):
            transactions = await load_transactions()
            view_year = current_view_date["year"]
            year_txns = []
            for t in transactions:
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year:
                    year_txns.append(t)

            active_name = profile_names_state.get(str(active_profile_state["value"]), f"Profile {active_profile_state['value']}")
            try:
                pdf_bytes = build_transactions_pdf_bytes(f"Annual Log - {active_name} - {view_year}", year_txns)
            except Exception as ex:
                mt_status_text.value = f"Couldn't create the PDF ({type(ex).__name__}). Please try again."
                page.update()
                return
            file_path = await picker_save_file(
                dialog_title="Save Annual Log",
                file_name=f"NairaFinanceHub_{safe_filename(active_name)}_{view_year}_Annual.pdf",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["pdf"],
                src_bytes=pdf_bytes,
            )
            mt_status_text.value = "Annual log saved!" if file_path else "Save cancelled."
            page.update()

        # -------------------- BACKUP & RESTORE (acts on the currently active profile) --------------------
        async def backup_data(e):
            try:
                saved_username = await prefs.get("user_name")
            except Exception:
                saved_username = ""

            profiles_data = {}
            for i in range(1, PROFILE_COUNT + 1):
                try:
                    raw_txn = await prefs.get(f"money_transactions_{i}")
                    txns = json.loads(raw_txn) if raw_txn else []
                except Exception:
                    txns = []
                try:
                    raw_budget = await prefs.get(f"category_budgets_{i}")
                    budgets = json.loads(raw_budget) if raw_budget else {}
                except Exception:
                    budgets = {}
                try:
                    raw_qa = await prefs.get(f"quick_add_shortcuts_{i}")
                    quick = json.loads(raw_qa) if raw_qa else []
                except Exception:
                    quick = []
                profiles_data[str(i)] = {"transactions": txns, "budgets": budgets, "quick_add": quick,
                                         "recurring": await load_recurring(i)}

            # Everything else you'd hate to lose on a new phone: Ajo groups, your custom
            # categories, alert rules and saved salary calculations.
            extras = {}
            for key in BACKUP_EXTRA_KEYS:
                try:
                    val = await prefs.get(key)
                    if val:
                        extras[key] = val
                except Exception:
                    pass

            backup_obj = {
                "app": "Naira Finance Hub",
                "backup_version": 3,
                "extras": extras,
                "created": datetime.datetime.now().isoformat(),
                "user_name": saved_username or "",
                "profile_names": profile_names_state,
                "profiles": profiles_data,
            }
            backup_bytes, ext = make_branded_file("backup_card.png", json.dumps(backup_obj).encode("utf-8"))

            file_path = await picker_save_file(
                dialog_title="Save Backup File",
                file_name=f"NairaFinanceHub_Backup_{datetime.date.today().isoformat()}.{ext}",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=[ext],
                src_bytes=backup_bytes,
            )
            page.show_dialog(ft.SnackBar(ft.Text("Backup saved for all 3 profiles! Keep this file somewhere safe." if file_path else "Backup cancelled.", color="white"), bgcolor=PURPLE_TEXT, duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
            page.update()

        async def restore_data(e):
            result = await picker_pick_files(
                dialog_title="Select Backup File to Restore",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["png", "json"],
                allow_multiple=False,
                with_data=True,
            )
            files = getattr(result, "files", result)
            if not files:
                page.show_dialog(ft.SnackBar(ft.Text("Restore cancelled.", color="white"), bgcolor=PURPLE_TEXT, duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()
                return

            picked = files[0]
            if not getattr(picked, "bytes", None):
                page.show_dialog(ft.SnackBar(ft.Text("Could not read that file. Please try again.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()
                return

            try:
                try:
                    backup_obj = json.loads(read_branded_file(bytes(picked.bytes)).decode("utf-8"))
                except ValueError as ve:
                    if str(ve) == "photo":
                        page.show_dialog(ft.SnackBar(ft.Text(PHOTO_STRIPPED_MSG, color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=7), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return
                    raise

                if not isinstance(backup_obj, dict) or not ("profiles" in backup_obj or "money_transactions" in backup_obj):
                    msg = ("That's an Ajo group file, not a backup. Import it from the Ajo tab instead."
                           if isinstance(backup_obj, dict) and "members" in backup_obj
                           else "That doesn't look like a valid backup file.")
                    page.show_dialog(ft.SnackBar(ft.Text(msg, color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=5), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                    return

                created = str(backup_obj.get("created", ""))[:10]

                async def do_restore(ev):
                    page.pop_dialog()
                    try:
                        await apply_backup(backup_obj)
                    except Exception:
                        page.show_dialog(ft.SnackBar(ft.Text("Restore failed — your current data was not changed by the failed step. Please try again.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=4), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()

                page.show_dialog(ft.AlertDialog(
                    scrollable=True, modal=True, bgcolor="#FFFFFF",
                    title=ft.Text("Restore this backup?", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Text(
                        (f"Backup made on {created}.\n\n" if created else "") +
                        "Your Money Tracker transactions, budgets, Quick Add shortcuts and repeating entries on this "
                        "phone will be REPLACED by the ones in the backup. Ajo groups, categories, alert rules and "
                        "savings goals from the backup are added to what you already have.",
                        color=DARK_TEXT, size=13),
                    actions=[
                        ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                        ft.ElevatedButton("Restore", on_click=do_restore, style=ft.ButtonStyle(bgcolor="#C62828", color="white")),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                ))
                page.update()
            except Exception:
                page.show_dialog(ft.SnackBar(ft.Text("That doesn't look like a valid backup file.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()

        async def apply_backup(backup_obj):
            if "profiles" in backup_obj:
                # New-format backup: restore all 3 profiles, each into its own correct slot
                for i in range(1, PROFILE_COUNT + 1):
                    profile_data = backup_obj["profiles"].get(str(i), {"transactions": [], "budgets": {}})
                    await prefs.set(f"money_transactions_{i}", json.dumps(profile_data.get("transactions", [])))
                    await prefs.set(f"category_budgets_{i}", json.dumps(profile_data.get("budgets", {})))
                    if "quick_add" in profile_data:
                        await prefs.set(f"quick_add_shortcuts_{i}", json.dumps(profile_data.get("quick_add", [])))
                    if isinstance(profile_data.get("recurring"), list):
                        await save_recurring(profile_data["recurring"], i)
                restored_names = backup_obj.get("profile_names", {})
                if restored_names:
                    profile_names_state.clear()
                    profile_names_state.update(restored_names)
                    await save_profile_names(profile_names_state)
                    profile_label_text.value = profile_names_state.get(str(active_profile_state["value"]), f"Profile {active_profile_state['value']}")
                restore_msg = "Backup restored! All 3 profiles are back."
            else:
                # Older backup format: only had one profile's data, restore into the currently active profile
                await save_transactions(backup_obj.get("money_transactions", []))
                restore_msg = "Backup restored into the current profile (older backup format)."

            await merge_backup_extras(backup_obj.get("extras", {}) or {})

            if backup_obj.get("user_name"):
                await prefs.set("user_name", backup_obj["user_name"])

            page.show_dialog(ft.SnackBar(ft.Text(restore_msg, color="white"), bgcolor="#2E8B57", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
            await refresh_money_ui()
            try:
                await refresh_quick_add_row()
                await refresh_ajo_ui()
                await refresh_home_ui()
            except Exception:
                pass
            page.update()

        async def merge_backup_extras(extras):
            """Adds the backup's extras to what's on the phone without throwing anything away."""
            async def get_json(key, default):
                try:
                    raw = await prefs.get(key)
                    return json.loads(raw) if raw else default
                except Exception:
                    return default
            def parse(key, default):
                try:
                    return json.loads(extras[key]) if key in extras else default
                except Exception:
                    return default

            # Ajo groups: add the ones this phone doesn't have yet (same group = keep the phone's copy).
            b_groups = [g for g in parse("ajo_groups", []) if is_valid_ajo_group(g)]
            if b_groups:
                cur = await load_ajo_groups()
                have = {g["id"] for g in cur}
                cur.extend(g for g in b_groups if g["id"] not in have)
                await save_ajo_groups(cur)
                if not await prefs.get("active_ajo_group_id") and cur:
                    await save_active_ajo_id(cur[0]["id"])

            # Custom categories
            b_cats = parse("category_changes", None)
            if isinstance(b_cats, dict):
                cur = await load_category_changes()
                added = dict(b_cats.get("added", {}))
                added.update(cur.get("added", {}))
                removed = sorted((set(b_cats.get("removed", [])) | set(cur.get("removed", []))) - set(added))
                await save_category_changes({"added": added, "removed": removed})
                await apply_saved_category_changes()

            # Alert category rules
            b_rules = parse(ALERT_RULES_KEY, [])
            if b_rules:
                cur = await load_alert_rules()
                have = {r.get("keyword") for r in cur}
                cur.extend(r for r in b_rules if isinstance(r, dict) and r.get("keyword") not in have)
                await save_alert_rules(cur)

            # Savings goals: add the ones this phone doesn't have yet.
            b_goals = [g for g in parse("savings_goals", []) if isinstance(g, dict) and g.get("id")]
            if b_goals:
                cur = await get_json("savings_goals", [])
                cur = cur if isinstance(cur, list) else []
                have = {g.get("id") for g in cur if isinstance(g, dict)}
                cur.extend(g for g in b_goals if g["id"] not in have)
                await prefs.set("savings_goals", json.dumps(cur))

            # Month-end to-do items: add the ones this phone doesn't have yet.
            b_todos = [t for t in parse("month_todos", []) if isinstance(t, dict) and t.get("id")]
            if b_todos:
                cur = await get_json("month_todos", [])
                cur = cur if isinstance(cur, list) else []
                have = {t.get("id") for t in cur if isinstance(t, dict)}
                cur.extend(t for t in b_todos if t["id"] not in have)
                await prefs.set("month_todos", json.dumps(cur))

            # Saved salary calculations: only fill in if this phone has none.
            if "salary_history" in extras and not await get_json("salary_history", []):
                await prefs.set("salary_history", extras["salary_history"])

        def show_backup_help(e):
            dlg = ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Backup & Restore — How It Works", color="#C62828", weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "This app has no login or account — everything lives only on this phone. Backup & Restore lets you keep a safe copy so nothing is lost.",
                                color=DARK_TEXT, size=13
                            ),
                            ft.Text("📤 Backup", weight=ft.FontWeight.BOLD, color="#C62828", size=13),
                            ft.Text(
                                "Tap 'Backup Data' to save everything into one file: all 3 profiles (transactions, budgets, Quick Add shortcuts, repeating entries and profile names), your Ajo groups, savings goals, custom categories, alert rules and saved salary calculations. Your App Lock PIN is not included. Choose where to save it — Downloads, Google Drive, or email it to yourself.",
                                color=DARK_TEXT, size=12
                            ),
                            ft.Text("📥 Restore", weight=ft.FontWeight.BOLD, color="#C62828", size=13),
                            ft.Text(
                                "On a new phone, or after reinstalling the app, tap 'Restore Data' and select your saved backup file. Your transactions will load right back in.",
                                color=DARK_TEXT, size=12
                            ),
                            ft.Text("🖼 How to spot your backup", weight=ft.FontWeight.BOLD, color="#C62828", size=13),
                            ft.Text(
                                "Your backup is saved as a picture with the Naira Finance Hub logo and the word BACKUP on it "
                                "(e.g. NairaFinanceHub_Backup_2026-10-04.png). Your data is safely stored inside that picture. "
                                "Older .json backups can still be restored.",
                                color=DARK_TEXT, size=12
                            ),
                            ft.Text("💬 Sharing on WhatsApp", weight=ft.FontWeight.BOLD, color="#C62828", size=13),
                            ft.Text(
                                "Always send the backup (or a shared Ajo group file) as a DOCUMENT: tap 📎 → Document, then pick the file. "
                                "Do NOT send it as a photo or from the Gallery — WhatsApp shrinks photos and the data inside is lost. "
                                "The same applies to Telegram and email: attach it as a file, not as an image.",
                                color=DARK_TEXT, size=12, weight=ft.FontWeight.BOLD
                            ),
                            ft.Text(
                                "⚠ Back up regularly, and keep the file somewhere safe. If the file is lost, the data inside it cannot be recovered.",
                                color="#C62828", size=12, weight=ft.FontWeight.BOLD
                            ),
                        ],
                        spacing=10, tight=True,
                    ),
                    width=300,
                ),
                actions=[ft.TextButton("Got it", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        today = datetime.date.today()
        current_view_date = {"year": today.year, "month": today.month}

        active_profile_state["value"] = await load_active_profile()
        profile_names_state.update(await load_profile_names())

        def build_type_toggle(initial_value, on_white=False):
            state = {"value": initial_value}
            idle_bg = "#9E9E9E" if on_white else ft.Colors.with_opacity(0.3, ft.Colors.WHITE)
            income_btn = ft.ElevatedButton(
                content=ft.Text("Income", weight=ft.FontWeight.BOLD, size=13, color="white"),
                style=ft.ButtonStyle(bgcolor="#2E8B57" if initial_value == "income" else idle_bg),
            )
            expense_btn = ft.ElevatedButton(
                content=ft.Text("Expense", weight=ft.FontWeight.BOLD, size=13, color="white"),
                style=ft.ButtonStyle(bgcolor="#C62828" if initial_value == "expense" else idle_bg),
            )

            def select(val):
                def handler(e):
                    state["value"] = val
                    income_btn.style = ft.ButtonStyle(bgcolor="#2E8B57" if val == "income" else idle_bg)
                    expense_btn.style = ft.ButtonStyle(bgcolor="#C62828" if val == "expense" else idle_bg)
                    page.update()
                return handler

            income_btn.on_click = select("income")
            expense_btn.on_click = select("expense")
            row = ft.Row([income_btn, expense_btn], spacing=8, alignment=ft.MainAxisAlignment.CENTER)
            return row, state

        def build_category_picker(initial_value):
            state = {"value": initial_value}
            label_text = ft.Text(initial_value, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14)
            label_icon = ft.Icon(category_icon(initial_value), color=PURPLE_TEXT, size=18)

            def open_picker(e):
                def pick(cat):
                    def handler(e):
                        state["value"] = cat
                        label_text.value = cat
                        label_icon.icon = category_icon(cat)
                        page.pop_dialog()
                        page.update()
                    return handler

                rows = [
                    ft.TextButton(
                        content=ft.Container(
                            content=ft.Row(
                                [ft.Icon(category_icon(c), color=PURPLE_TEXT, size=18), ft.Text(c, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)],
                                spacing=10,
                            ),
                            width=220,
                        ),
                        on_click=pick(c),
                    )
                    for c in CATEGORY_OPTIONS
                ]
                dlg = ft.AlertDialog(scrollable=True, 
                    modal=True,
                    bgcolor="#FFFFFF",
                    title=ft.Text("Select Category", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Container(content=ft.ListView(controls=rows, spacing=2), width=260, height=350),
                    actions=[ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                page.show_dialog(dlg)

            picker_btn = ft.ElevatedButton(
                content=ft.Row(
                    [ft.Row([label_icon, label_text], spacing=8), ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=PURPLE_TEXT)],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                on_click=open_picker,
                style=ft.ButtonStyle(bgcolor="#FFFFFF", side=ft.BorderSide(1, PURPLE_TEXT)),
                width=280,
            )
            return picker_btn, state

        profile_label_text = ft.Text(
            profile_names_state.get(str(active_profile_state["value"]), f"Profile {active_profile_state['value']}"),
            color="white", weight=ft.FontWeight.BOLD, size=14,
        )

        async def switch_to_profile(profile_num):
            active_profile_state["value"] = profile_num
            await save_active_profile(profile_num)
            profile_label_text.value = profile_names_state.get(str(profile_num), f"Profile {profile_num}")
            current_view_date["year"] = datetime.date.today().year
            current_view_date["month"] = datetime.date.today().month
            page.pop_dialog()
            await refresh_money_ui()
            page.update()

        def open_rename_dialog(profile_num):
            name_field = NFTextField(
                value=profile_names_state.get(str(profile_num), f"Profile {profile_num}"),
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                autofocus=True,
                capitalization=ft.TextCapitalization.WORDS,
                max_length=30,
            )
            name_field.on_change = with_length_warning(name_field, 30)

            async def save_rename(e):
                new_name = (name_field.value or "").strip() or f"Profile {profile_num}"
                profile_names_state[str(profile_num)] = new_name
                await save_profile_names(profile_names_state)
                if profile_num == active_profile_state["value"]:
                    profile_label_text.value = new_name
                page.pop_dialog()
                page.pop_dialog()
                page.update()

            rename_dlg = ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Rename Profile", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(content=name_field, width=260),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.TextButton("Save", on_click=save_rename, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(rename_dlg)

        def open_profile_picker(e):
            rows = []
            for i in range(1, PROFILE_COUNT + 1):
                name = profile_names_state.get(str(i), f"Profile {i}")
                is_active = i == active_profile_state["value"]

                def make_switch(profile_num):
                    async def handler(e):
                        await switch_to_profile(profile_num)
                    return handler

                def make_rename(profile_num):
                    def handler(e):
                        open_rename_dialog(profile_num)
                    return handler

                rows.append(
                    ft.Row(
                        [
                            ft.TextButton(
                                content=ft.Row(
                                    [
                                        ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED if is_active else ft.Icons.CIRCLE_OUTLINED, color="#2E8B57" if is_active else PURPLE_TEXT, size=18),
                                        ft.Text(name, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14),
                                    ],
                                    spacing=8,
                                ),
                                on_click=make_switch(i),
                            ),
                            ft.IconButton(icon=ft.Icons.EDIT_ROUNDED, icon_color=PURPLE_TEXT, icon_size=16, on_click=make_rename(i)),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                )

            dlg = ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Switch Profile", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(content=ft.Column(rows, spacing=6, tight=True), width=270),
                actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        profile_switcher_btn = ft.ElevatedButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.SWITCH_ACCOUNT_ROUNDED, size=16, color="white"), profile_label_text, ft.Icon(ft.Icons.ARROW_DROP_DOWN, color="white")],
                spacing=6, tight=True,
            ),
            on_click=open_profile_picker,
            style=ft.ButtonStyle(bgcolor="#1E88E5"),
        )

        mt_type_row, mt_type_state = build_type_toggle("income")
        mt_category_picker, mt_category_state = build_category_picker("Other")
        mt_amount_input = NFTextField(keyboard_type=ft.KeyboardType.NUMBER, max_length=15, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        mt_amount_input.on_change = with_length_warning(mt_amount_input, 15)
        mt_charge_input = NFTextField(keyboard_type=ft.KeyboardType.NUMBER, max_length=15, hint_text="e.g. bank/POS fee", bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        mt_charge_input.on_change = with_length_warning(mt_charge_input, 15)
        mt_note_input = NFTextField(bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), capitalization=ft.TextCapitalization.WORDS, max_length=100)
        mt_note_input.on_change = with_length_warning(mt_note_input, 100)
        mt_status_text = ft.Text("", color="white", size=12, text_align=ft.TextAlign.CENTER)

        mt_selected_date = {"value": None}
        mt_date_button_text = ft.Text("Transaction Date (Optional)", color="#4B0082", size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

        def mt_on_date_picked(e):
            picked = e.control.value
            if picked:
                picked_date = picked_to_date(picked)
                if picked_date > datetime.date.today():
                    mt_status_text.value = "You can't select a future date. Please pick today or an earlier date."
                    page.update()
                    return
                mt_selected_date["value"] = picked_date
                mt_date_button_text.value = picked_date.strftime("%d %b %Y")
                mt_status_text.value = ""
                page.update()

        mt_date_picker = ft.DatePicker(
            first_date=datetime.datetime(2020, 1, 1),
            last_date=datetime.datetime.now(),
            current_date=datetime.datetime.now(),
            on_change=mt_on_date_picked,
        )

        mt_date_button = ft.ElevatedButton(
            content=ft.Container(content=mt_date_button_text, width=190),
            on_click=lambda e: (setattr(mt_date_picker, "last_date", datetime.datetime.now()), page.show_dialog(mt_date_picker)),
            style=ft.ButtonStyle(bgcolor="#FFD700"),
        )

        mt_month_label = ft.Text("", size=16, weight=ft.FontWeight.BOLD, color="white")

        mt_summary_income = ft.Text(spans=[ft.TextSpan("Income: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=14)
        mt_summary_expense = ft.Text(spans=[ft.TextSpan("Expense: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_RED, weight=ft.FontWeight.BOLD))], size=14)
        mt_summary_charges = ft.Text(spans=[ft.TextSpan("Bank Charges: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_RED, weight=ft.FontWeight.BOLD))], size=14)
        mt_summary_net = ft.Text(spans=[ft.TextSpan("Net: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=18)

        mt_annual_label = ft.Text("", size=15, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER)
        mt_annual_income = ft.Text(spans=[ft.TextSpan("Total Income: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=14)
        mt_annual_expense = ft.Text(spans=[ft.TextSpan("Total Expense: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_RED, weight=ft.FontWeight.BOLD))], size=14)
        mt_annual_charges = ft.Text(spans=[ft.TextSpan("Total Bank Charges: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_RED, weight=ft.FontWeight.BOLD))], size=14)
        mt_annual_net = ft.Text(spans=[ft.TextSpan("Annual Net: ", ft.TextStyle(color="white", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color=MONEY_GREEN, weight=ft.FontWeight.BOLD))], size=18)
        mt_annual_category_list_view = ft.Column([], spacing=6)

        mt_chart_container = ft.Container(padding=10, alignment=ft.Alignment(0, 0))
        mt_category_list_view = ft.Column([], spacing=6)
        mt_breakdown_container = ft.Container()
        mt_transactions_list_view = ft.ListView(controls=[], spacing=8, height=260)
        mt_search_query = {"value": ""}

        async def on_search_change(e):
            mt_search_query["value"] = (mt_search_input.value or "").strip().lower()
            await refresh_money_ui()

        mt_search_input = NFTextField(
            hint_text="Search transactions",
            bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            max_length=50,
        )
        mt_search_input.on_change = with_length_warning(mt_search_input, 50, on_search_change)


        def open_edit_dialog(actual_idx, entry):
            edit_type_row, edit_type_state = build_type_toggle(entry.get("type", "expense"), on_white=True)
            edit_category_picker, edit_category_state = build_category_picker(entry.get("category", "Other"))
            edit_amount_input = NFTextField(
                value=str(entry.get("amount", "")), keyboard_type=ft.KeyboardType.NUMBER, max_length=15,
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            )
            edit_amount_input.on_change = with_length_warning(edit_amount_input, 15)
            edit_charge_input = NFTextField(
                value=str(entry.get("charge", "")) if entry.get("charge") else "",
                keyboard_type=ft.KeyboardType.NUMBER, max_length=15,
                hint_text="e.g. bank/POS fee",
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            )
            edit_charge_input.on_change = with_length_warning(edit_charge_input, 15)
            edit_note_input = NFTextField(
                value=entry.get("note", ""),
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                capitalization=ft.TextCapitalization.WORDS,
                max_length=100,
            )
            edit_note_input.on_change = with_length_warning(edit_note_input, 100)
            edit_error_text = ft.Text("", color="red", size=12)
            is_auto_alert = (entry.get("note", "") or "").startswith("Auto:")
            edit_remember_cb = ft.Checkbox(label="Always use this category for bank alerts containing:", value=False,
                                           label_style=ft.TextStyle(size=12, color=PURPLE_TEXT))
            edit_remember_tf = NFTextField(value=suggest_alert_keyword(entry.get("note", "")), dense=True,
                                            bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                                            capitalization=ft.TextCapitalization.CHARACTERS, max_length=30)
            remember_box = ft.Column([edit_remember_cb, edit_remember_tf], spacing=4, tight=True, visible=is_auto_alert)

            try:
                existing_date = datetime.date.fromisoformat(entry.get("date", ""))
            except Exception:
                existing_date = datetime.date.today()
            edit_selected_date = {"value": existing_date}
            edit_date_button_text = ft.Text(existing_date.strftime("%d %b %Y"), color=PURPLE_TEXT, size=13, weight=ft.FontWeight.BOLD)

            def edit_on_date_picked(e):
                picked = e.control.value
                if picked:
                    picked_date = picked_to_date(picked)
                    if picked_date > datetime.date.today():
                        edit_error_text.value = "You can't select a future date. Please pick today or an earlier date."
                        page.update()
                        return
                    edit_selected_date["value"] = picked_date
                    edit_date_button_text.value = picked_date.strftime("%d %b %Y")
                    edit_error_text.value = ""
                    page.update()

            edit_date_picker = ft.DatePicker(
                first_date=datetime.datetime(2020, 1, 1),
                last_date=datetime.datetime.now(),
                current_date=datetime.datetime(existing_date.year, existing_date.month, existing_date.day),
                on_change=edit_on_date_picked,
            )
            edit_date_button = ft.ElevatedButton(
                content=ft.Container(content=edit_date_button_text, width=200),
                on_click=lambda e: (setattr(edit_date_picker, "last_date", datetime.datetime.now()), page.show_dialog(edit_date_picker)),
                style=ft.ButtonStyle(bgcolor="#FFD700"),
            )

            async def save_edit(e):
                try:
                    new_amount = to_number(edit_amount_input.value, required=True)
                except (ValueError, TypeError):
                    edit_error_text.value = "Enter a valid amount."
                    page.update()
                    return

                charge_raw = (edit_charge_input.value or "").strip()
                try:
                    new_charge = to_number(charge_raw)
                except ValueError:
                    edit_error_text.value = "Transaction charge must be a number."
                    page.update()
                    return

                full = await load_transactions()
                pos = find_txn_index(full, actual_idx, entry)
                if pos >= 0:
                    full[pos]["type"] = edit_type_state["value"]
                    full[pos]["category"] = edit_category_state["value"]
                    full[pos]["amount"] = new_amount
                    full[pos]["charge"] = new_charge
                    full[pos]["note"] = (edit_note_input.value or "").strip()
                    new_date = edit_selected_date["value"].isoformat()
                    if new_date != full[pos].get("date"):
                        full[pos].pop("time", None)  # a moved date makes the old time meaningless
                    full[pos]["date"] = new_date
                    await save_transactions(full)
                moved = 0
                if is_auto_alert and edit_remember_cb.value and (edit_remember_tf.value or "").strip():
                    moved = await add_alert_rule(edit_remember_tf.value, edit_category_state["value"])
                page.pop_dialog()
                await refresh_money_ui()
                if edit_remember_cb.value and is_auto_alert:
                    page.show_dialog(ft.SnackBar(ft.Text(
                        f"Rule saved: future alerts with “{' '.join(_rule_words(edit_remember_tf.value))}” go to "
                        f"{edit_category_state['value']}." + (f" {moved} other item(s) moved too." if moved else ""),
                        color="white"), bgcolor="#2E8B57", duration=ft.Duration(seconds=4),
                        behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))

            async def delete_from_edit(e):
                full = await load_transactions()
                deleted_entry = None
                pos = find_txn_index(full, actual_idx, entry)
                if pos >= 0:
                    deleted_entry = full.pop(pos)
                    await save_transactions(full)
                page.pop_dialog()
                await refresh_money_ui()
                if deleted_entry:
                    show_undo_snackbar(deleted_entry, pos)

            edit_dialog = ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Edit Transaction", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            field_with_caption("Type", edit_type_row, on_white=True),
                            field_with_caption("Category", edit_category_picker, on_white=True),
                            field_with_caption("Amount (₦)", edit_amount_input, on_white=True),
                            field_with_caption("Bank Charges (₦, optional)", edit_charge_input, on_white=True),
                            field_with_caption("Note", edit_note_input, on_white=True),
                            field_with_caption("Date", edit_date_button, on_white=True),
                            remember_box,
                            edit_error_text,
                        ],
                        tight=True, spacing=15,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color="#666666")),
                    ft.TextButton("Delete", on_click=delete_from_edit, style=ft.ButtonStyle(color="#C62828")),
                    ft.TextButton("Save", on_click=save_edit, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(edit_dialog)

        last_auto_ingest = {"t": 0.0}

        async def refresh_money_ui():
            # Reading captured alerts used to run on EVERY screen refresh (each add, edit, delete,
            # month change). Now it runs at most once every 20 s; "Check now" still runs it at once.
            if time.monotonic() - last_auto_ingest["t"] > 20:
                last_auto_ingest["t"] = time.monotonic()
                await ingest_pending_notifications()
            mt_month_label.value = datetime.date(current_view_date["year"], current_view_date["month"], 1).strftime("%B %Y")

            def bouncy_icon(cat, size=16, color="white"):
                # Plain icon: the old bounce-in animation forced a second full-page redraw on
                # every refresh, which made the app feel frozen once there were many entries.
                return ft.Icon(category_icon(cat), size=size, color=color)

            transactions = await load_transactions()
            view_year = current_view_date["year"]
            view_month = current_view_date["month"]

            month_income = 0.0
            month_expense = 0.0
            month_charges = 0.0
            category_totals = {}
            filtered = []

            for idx, t in enumerate(transactions):
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year and d.month == view_month:
                    filtered.append((idx, t))
                    cat = t.get("category", "Other")
                    entry = category_totals.setdefault(cat, {"income": 0.0, "expense": 0.0})
                    if t["type"] == "income":
                        month_income += t["amount"]
                        entry["income"] += t["amount"]
                    else:
                        month_expense += t["amount"]
                        entry["expense"] += t["amount"]
                    month_charges += t.get("charge", 0.0) or 0.0

            net = month_income - month_expense - month_charges
            mt_summary_income.spans[1].text = f"₦{month_income:,.2f}"
            mt_summary_expense.spans[1].text = f"₦{month_expense:,.2f}"
            mt_summary_charges.spans[1].text = f"₦{month_charges:,.2f}"
            mt_summary_net.spans[1].text = fmt_money(net)
            mt_summary_net.spans[1].style = ft.TextStyle(color=MONEY_GREEN if net >= 0 else MONEY_RED, weight=ft.FontWeight.BOLD)

            # Annual accumulation across every month of the currently-viewed year
            annual_income = 0.0
            annual_expense = 0.0
            annual_charges = 0.0
            annual_category_totals = {}
            for t in transactions:
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year:
                    cat = t.get("category", "Other")
                    cat_entry = annual_category_totals.setdefault(cat, {"income": 0.0, "expense": 0.0})
                    if t["type"] == "income":
                        annual_income += t["amount"]
                        cat_entry["income"] += t["amount"]
                    else:
                        annual_expense += t["amount"]
                        cat_entry["expense"] += t["amount"]
                    annual_charges += t.get("charge", 0.0) or 0.0
            annual_net = annual_income - annual_expense - annual_charges

            mt_annual_label.value = f"Annual Summary ({view_year})"
            mt_annual_income.spans[1].text = f"₦{annual_income:,.2f}"
            mt_annual_expense.spans[1].text = f"₦{annual_expense:,.2f}"
            mt_annual_charges.spans[1].text = f"₦{annual_charges:,.2f}"
            mt_annual_net.spans[1].text = fmt_money(annual_net)
            mt_annual_net.spans[1].style = ft.TextStyle(color=MONEY_GREEN if annual_net >= 0 else MONEY_RED, weight=ft.FontWeight.BOLD)

            if annual_category_totals:
                annual_entries = []
                for cat, v in annual_category_totals.items():
                    if v["income"] > 0:
                        annual_entries.append((cat, "income", v["income"]))
                    if v["expense"] > 0:
                        annual_entries.append((cat, "expense", v["expense"]))
                sorted_annual_cats = sorted(annual_entries, key=lambda x: x[2], reverse=True)
                mt_annual_category_list_view.controls = [
                    ft.Row(
                        [
                            ft.Row([bouncy_icon(cat), ft.Text(f"{cat} ({'Income' if kind == 'income' else 'Expense'})", color="white", size=13)], spacing=6),
                            ft.Text(f"{'+' if kind == 'income' else '-'}₦{amt:,.2f}", color="#5DE88C" if kind == "income" else "#FF6B6B", size=13, weight=ft.FontWeight.BOLD),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                    for cat, kind, amt in sorted_annual_cats
                ]
            else:
                mt_annual_category_list_view.controls = [ft.Text("No transactions this year yet.", color="white", size=12)]

            # Build a per-category bar so the user can see where money actually goes.
            # Income and expense on the SAME category are shown as separate bars,
            # not netted together, so both flows stay visible.
            category_entries = []
            for cat, v in category_totals.items():
                if v["income"] > 0:
                    category_entries.append((cat, "income", v["income"]))
                if v["expense"] > 0:
                    category_entries.append((cat, "expense", v["expense"]))
            sorted_categories = sorted(category_entries, key=lambda x: x[2], reverse=True)[:10]

            if sorted_categories:
                max_bar_height = 150
                max_abs = max((amt for _, _, amt in sorted_categories), default=1.0) or 1.0

                category_units = []
                for cat, kind, amt in sorted_categories:
                    bar_height = max(10, (amt / max_abs) * max_bar_height)
                    bar_color = "#2E8B57" if kind == "income" else "#C62828"
                    tag = "In" if kind == "income" else "Out"
                    category_units.append(
                        ft.Column(
                            [
                                ft.Container(
                                    content=ft.Container(height=bar_height, width=44, bgcolor=bar_color, border_radius=6),
                                    height=max_bar_height,
                                    alignment=ft.Alignment(0, 1),
                                ),
                                ft.Text(f"₦{amt:,.0f}", size=10, color="white"),
                                ft.Text(f"{cat} ({tag})", size=10, color="white", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                            width=72,
                        )
                    )

                mt_chart_container.content = ft.Row(
                    category_units,
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                )
            else:
                mt_chart_container.content = ft.Text("No transactions this month yet.", color="white", size=13, text_align=ft.TextAlign.CENTER)

            # ---- "Where your money went": a ring by category, and this month against last month
            try:
                exp_items = sorted(((c, v["expense"]) for c, v in category_totals.items() if v["expense"] > 0),
                                   key=lambda x: x[1], reverse=True)
                exp_total = sum(a for _, a in exp_items)
                real_today = datetime.date.today()
                viewing_now = (view_year, view_month) == (real_today.year, real_today.month)
                p_year, p_month = prev_month(view_year, view_month)
                this_spent = month_expense + month_charges
                last_stats = month_stats(transactions, p_year, p_month, up_to_day=real_today.day if viewing_now else 31)
                last_spent = last_stats["spent"]
                this_name = datetime.date(view_year, view_month, 1).strftime("%b")
                last_name = datetime.date(p_year, p_month, 1).strftime("%b")
                breakdown = [ft.Text("Where your money went", color="white", weight=ft.FontWeight.BOLD, size=14)]
                if exp_total > 0:
                    top = exp_items[:5]
                    others = sum(a for _, a in exp_items[5:])
                    if others > 0:
                        top.append(("Others", others))
                    arcs, legend = [], []
                    angle = -math.pi / 2
                    gap = 0.06 if len(top) > 1 else 0.0
                    for i, (cat, amt) in enumerate(top):
                        frac = amt / exp_total
                        sweep = (2 * math.pi - 0.001) if len(top) == 1 else max(frac * 2 * math.pi - gap, 0.02)
                        ring_color = RING_COLORS[i % len(RING_COLORS)]
                        arcs.append(cv.Arc(x=14, y=14, width=112, height=112, start_angle=angle, sweep_angle=sweep,
                                           paint=ft.Paint(style=ft.PaintingStyle.STROKE, stroke_width=24, color=ring_color)))
                        angle += frac * 2 * math.pi
                        legend.append(ft.Row(
                            [
                                ft.Container(width=10, height=10, border_radius=5, bgcolor=ring_color),
                                ft.Text(cat, color="white", size=12, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(f"{frac * 100:.0f}%", color="white", size=12, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=6,
                        ))
                    ring = ft.Stack(
                        [
                            cv.Canvas(arcs, width=140, height=140),
                            ft.Container(
                                content=ft.Column(
                                    [ft.Text("Spent", size=10, color="#DDDDDD"),
                                     ft.Text(fmt_compact(exp_total), size=14, weight=ft.FontWeight.BOLD, color="white")],
                                    spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                width=140, height=140, alignment=ft.Alignment(0, 0),
                            ),
                        ],
                        width=140, height=140,
                    )
                    breakdown.append(ft.Row([ring, ft.Column(legend, spacing=6, expand=True, tight=True)], spacing=12,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER))
                else:
                    breakdown.append(ft.Text("No spending recorded this month yet.", color="white", size=12))

                if this_spent > 0 or last_spent > 0:
                    biggest = max(this_spent, last_spent, 1.0)
                    this_label = f"{this_name} so far" if viewing_now else this_name
                    last_label = f"{last_name} by day {real_today.day}" if viewing_now else last_name

                    def compare_row(label, amount, bar_color):
                        return ft.Column(
                            [
                                ft.Row([ft.Text(label, color="white", size=12), ft.Text(fmt_money(amount, 0), color="white", size=12, weight=ft.FontWeight.BOLD)],
                                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ui_progress_bar(amount / biggest * 100.0, bar_color, height=8),
                            ],
                            spacing=3, tight=True,
                        )

                    breakdown.append(ft.Divider(height=1, color="#4B0082"))
                    breakdown.append(ft.Text("This month vs last month" if viewing_now else f"{this_name} vs {last_name}",
                                             color="white", weight=ft.FontWeight.BOLD, size=13))
                    breakdown.append(compare_row(this_label, this_spent, "#FF6B6B"))
                    breakdown.append(compare_row(last_label, last_spent, "#64B5F6"))
                    if last_spent > 0:
                        diff = (this_spent - last_spent) / last_spent * 100.0
                        versus = "at this point last month" if viewing_now else "the month before"
                        if abs(diff) < 1:
                            verdict, verdict_color = f"About the same as {versus}.", "white"
                        elif diff < 0:
                            verdict, verdict_color = f"{abs(diff):.0f}% less than {versus}. Well done!", MONEY_GREEN
                        else:
                            verdict, verdict_color = f"{diff:.0f}% more than {versus}.", MONEY_RED
                        breakdown.append(ft.Text(verdict, color=verdict_color, size=12, weight=ft.FontWeight.BOLD))
                mt_breakdown_container.content = ft.Column(breakdown, spacing=8, tight=True)
            except Exception:
                mt_breakdown_container.content = None  # never let the chart stop the page loading

            if category_totals:
                list_entries = []
                for cat, v in category_totals.items():
                    if v["income"] > 0:
                        list_entries.append((cat, "income", v["income"]))
                    if v["expense"] > 0:
                        list_entries.append((cat, "expense", v["expense"]))
                sorted_cats_full = sorted(list_entries, key=lambda x: x[2], reverse=True)
                category_rows = [
                    ft.Row(
                        [
                            ft.Row([bouncy_icon(cat), ft.Text(f"{cat} ({'Income' if kind == 'income' else 'Expense'})", color="white", size=13)], spacing=6),
                            ft.Text(f"{'+' if kind == 'income' else '-'}₦{amt:,.2f}", color="#5DE88C" if kind == "income" else "#FF6B6B", size=13, weight=ft.FontWeight.BOLD),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                    for cat, kind, amt in sorted_cats_full
                ]

                budgets = await load_budgets()
                if budgets:
                    budget_rows = []
                    for cat, limit in budgets.items():
                        spent = category_totals.get(cat, {}).get("expense", 0.0)
                        pct = (spent / limit * 100.0) if limit > 0 else 0.0
                        if pct >= 100:
                            status_color = "#C62828"
                            status_text = f"Over budget! ₦{spent:,.0f} of ₦{limit:,.0f}"
                        elif pct >= 80:
                            status_color = "#FF8C00"
                            status_text = f"{pct:.0f}% used — ₦{spent:,.0f} of ₦{limit:,.0f}"
                        else:
                            status_color = "#2E8B57"
                            status_text = f"{pct:.0f}% used — ₦{spent:,.0f} of ₦{limit:,.0f}"
                        budget_rows.append(
                            ft.Column(
                                [
                                    ft.Row([bouncy_icon(cat), ft.Text(f"{cat} Budget", color="white", size=12, weight=ft.FontWeight.BOLD)], spacing=6),
                                    ft.Container(
                                        content=ft.Container(
                                            width=min(pct, 100) * 2.2,
                                            height=8,
                                            bgcolor=status_color,
                                            border_radius=4,
                                        ),
                                        width=220, height=8, bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.WHITE), border_radius=4,
                                        alignment=ft.Alignment(-1, 0),
                                    ),
                                    ft.Text(status_text, color=status_color, size=11, weight=ft.FontWeight.BOLD),
                                ],
                                spacing=4,
                            )
                        )
                    category_rows.append(ft.Divider(height=1, color="#4B0082"))
                    category_rows.append(ft.Text("Budgets", color="white", weight=ft.FontWeight.BOLD, size=13))
                    category_rows.extend(budget_rows)

                mt_category_list_view.controls = category_rows
            else:
                mt_category_list_view.controls = [ft.Text("No transactions this month yet.", color="white", size=12)]

            def make_delete(actual_idx, entry):
                async def _delete(e):
                    if txn_busy["value"]:
                        return  # ignore a second tap while the first delete is still saving
                    txn_busy["value"] = True
                    try:
                        full = await load_transactions()
                        deleted_entry = None
                        pos = find_txn_index(full, actual_idx, entry)
                        if pos >= 0:
                            deleted_entry = full.pop(pos)
                            await save_transactions(full)
                        await refresh_money_ui()
                    finally:
                        txn_busy["value"] = False
                    page.update()
                    if deleted_entry:
                        show_undo_snackbar(deleted_entry, pos)
                return _delete

            def make_repeat(source_entry):
                async def _repeat(e):
                    new_entry = {
                        "type": source_entry.get("type", "expense"),
                        "category": source_entry.get("category", "Other"),
                        "amount": source_entry.get("amount", 0),
                        "charge": source_entry.get("charge", 0.0),
                        "note": source_entry.get("note", ""),
                        "date": datetime.date.today().isoformat(),
                        "time": datetime.datetime.now().strftime("%H:%M"),
                    }
                    full = await load_transactions()
                    full.insert(0, new_entry)
                    full = full[:10000]
                    await save_transactions(full)
                    current_view_date["year"] = datetime.date.today().year
                    current_view_date["month"] = datetime.date.today().month
                    await refresh_money_ui()
                    page.show_dialog(ft.SnackBar(ft.Text("Repeated — tap it to edit if anything changed.", color="white"), bgcolor="#2E8B57", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                return _repeat

            def make_row_click(actual_idx, entry):
                def _click(e):
                    open_edit_dialog(actual_idx, entry)
                return _click

            search_q = mt_search_query["value"]
            if search_q:
                display_filtered = [
                    (idx, t) for idx, t in filtered
                    if search_q in (t.get("note", "") or "").lower() or search_q in (t.get("category", "") or "").lower()
                ]
            else:
                display_filtered = filtered

            rows = []
            for actual_idx, t in display_filtered[:30]:
                color = "#5DE88C" if t["type"] == "income" else "#FF6B6B"  # brighter so it reads on the dark card
                sign = "+" if t["type"] == "income" else "-"
                note = (t.get("note", "") or "").strip()
                is_auto = note.startswith("Auto:")
                if is_auto:
                    note = note[5:].strip()
                title = note or t["type"].capitalize()
                sub = ("⚡ " if is_auto else "") + ("🔁 " if t.get("repeat") else "") + f"{t.get('category', 'Other')} • {fmt_txn_when(t)}"
                rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                bouncy_icon(t.get("category", "Other"), size=20),
                                ft.Column(
                                    [
                                        ft.Text(title, weight=ft.FontWeight.BOLD, color="white", size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                        ft.Text(sub, size=11, color="#FFD54F", weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ],
                                    spacing=1, expand=True,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(f"{sign}₦{t['amount']:,.2f}", color=color, weight=ft.FontWeight.BOLD, size=13),
                                        ft.Row(
                                            [
                                                ft.Container(content=ft.Icon(ft.Icons.REPLAY_ROUNDED, color="#64B5F6", size=18), padding=4, border_radius=12, ink=True, on_click=make_repeat(t)),
                                                ft.Container(content=ft.Icon(ft.Icons.CLOSE, color="#EF5350", size=18), padding=4, border_radius=12, ink=True, on_click=make_delete(actual_idx, t)),
                                            ],
                                            spacing=6, tight=True,
                                        ),
                                    ],
                                    spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END, tight=True,
                                ),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        on_click=make_row_click(actual_idx, t),
                        padding=ft.Padding(top=6, bottom=6, left=6, right=6),
                        border_radius=6,
                        ink=True,
                    )
                )
            if rows:
                mt_transactions_list_view.controls = rows
            elif search_q:
                mt_transactions_list_view.controls = [ft.Text(f"No results for '{mt_search_input.value}'.", color=DARK_TEXT, size=12)]
            else:
                mt_transactions_list_view.controls = [ft.Text("No transactions this month. Tap a row to edit.", color=DARK_TEXT, size=12)]
            page.update()

        async def go_prev_month(e):
            m = current_view_date["month"] - 1
            y = current_view_date["year"]
            if m < 1:
                m, y = 12, y - 1
            current_view_date["month"], current_view_date["year"] = m, y
            await refresh_money_ui()

        async def go_next_month(e):
            m = current_view_date["month"] + 1
            y = current_view_date["year"]
            if m > 12:
                m, y = 1, y + 1
            real_today = datetime.date.today()
            if (y, m) > (real_today.year, real_today.month):
                return
            current_view_date["month"], current_view_date["year"] = m, y
            await refresh_money_ui()

        mt_month_nav = ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, icon_color="white", on_click=go_prev_month),
                    mt_month_label,
                    ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, icon_color="white", on_click=go_next_month),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=10, right=10, top=4, bottom=4),
        )

        async def mt_on_add_click(e):
            try:
                amount = to_number(mt_amount_input.value, required=True)
            except (ValueError, TypeError):
                mt_status_text.value = "Please enter a valid amount."
                page.update()
                return

            charge_raw = (mt_charge_input.value or "").strip()
            try:
                charge = to_number(charge_raw)
            except ValueError:
                mt_status_text.value = "Transaction charge must be a number."
                page.update()
                return

            chosen_date = mt_selected_date["value"] or datetime.date.today()
            entry = {
                "type": mt_type_state["value"] or "income",
                "category": mt_category_state["value"] or "Other",
                "amount": amount,
                "charge": charge,
                "note": (mt_note_input.value or "").strip(),
                "date": chosen_date.isoformat(),
            }
            if not mt_selected_date["value"]:
                entry["time"] = datetime.datetime.now().strftime("%H:%M")  # logged now -> keep the time
            transactions = await load_transactions()
            transactions.insert(0, entry)
            transactions = transactions[:10000]
            await save_transactions(transactions)
            mt_amount_input.value = ""
            mt_charge_input.value = ""
            mt_note_input.value = ""
            mt_selected_date["value"] = None
            mt_date_button_text.value = "Transaction Date (Optional)"
            mt_status_text.value = "Transaction added."
            current_view_date["year"] = datetime.date.today().year
            current_view_date["month"] = datetime.date.today().month
            await refresh_money_ui()
            page.update()

        mt_add_btn = ft.ElevatedButton("Add Transaction", on_click=mt_on_add_click, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))

        # -------------------- QUICK ADD SHORTCUTS --------------------
        mt_quick_add_row = ft.Row([], spacing=8, scroll=ft.ScrollMode.AUTO, alignment=ft.MainAxisAlignment.CENTER)

        async def refresh_quick_add_row():
            shortcuts = await load_quick_add()

            def make_use_shortcut(shortcut):
                async def _use(e):
                    entry = {
                        "type": shortcut.get("type", "expense"),
                        "category": shortcut.get("category", "Other"),
                        "amount": shortcut.get("amount", 0),
                        "charge": 0.0,
                        "note": shortcut.get("note", ""),
                        "date": datetime.date.today().isoformat(),
                        "time": datetime.datetime.now().strftime("%H:%M"),
                    }
                    full = await load_transactions()
                    full.insert(0, entry)
                    full = full[:10000]
                    await save_transactions(full)
                    current_view_date["year"] = datetime.date.today().year
                    current_view_date["month"] = datetime.date.today().month
                    await refresh_money_ui()
                    page.show_dialog(ft.SnackBar(ft.Text(f"Added: {shortcut.get('label', 'Quick add')}", color="white"), bgcolor="#2E8B57", duration=ft.Duration(seconds=2), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                return _use

            chips = []
            for s in shortcuts:
                chip_color = "#2E8B57" if s.get("type") == "income" else "#C62828"
                chips.append(
                    ft.ElevatedButton(
                        content=ft.Row(
                            [ft.Icon(category_icon(s.get("category", "Other")), size=14, color="white"), ft.Text(s.get("label", "Shortcut"), size=12, weight=ft.FontWeight.BOLD, color="white")],
                            spacing=4, tight=True,
                        ),
                        on_click=make_use_shortcut(s),
                        style=ft.ButtonStyle(bgcolor=chip_color),
                    )
                )
            mt_quick_add_row.controls = chips if chips else [ft.Text("No shortcuts yet. Add some with the Options button.", color="white", size=11, italic=True)]

        async def manage_categories_dialog(e):
            changes = await load_category_changes()

            list_col = ft.Column([], spacing=6)
            selected_icon_key = {"value": None}
            new_cat_field = NFTextField(label="New Category Name", bgcolor="#FFFFFF", color="black", text_style=ft.TextStyle(color="black"), capitalization=ft.TextCapitalization.WORDS, dense=True, max_length=25)
            new_cat_field.on_change = with_length_warning(new_cat_field, 25)
            add_error_text = ft.Text("", color="red", size=12)

            def build_list():
                rows = []
                for cat in CATEGORY_OPTIONS:
                    def make_remove(name):
                        async def _remove(e):
                            if name == "Other":
                                return
                            if name in CATEGORY_OPTIONS:
                                CATEGORY_OPTIONS.remove(name)
                            CATEGORY_ICONS.pop(name, None)
                            changes.setdefault("removed", [])
                            if name not in changes["removed"]:
                                changes["removed"].append(name)
                            changes.get("added", {}).pop(name, None)
                            await save_category_changes(changes)
                            build_list()
                            page.update()
                        return _remove

                    rows.append(
                        ft.Row(
                            [
                                ft.Row([ft.Icon(category_icon(cat), color=PURPLE_TEXT, size=18), ft.Text(cat, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13)], spacing=8),
                                ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_remove(cat)) if cat != "Other" else ft.Container(width=16),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        )
                    )
                list_col.controls = rows

            build_list()

            icon_buttons = {}

            def build_icon_grid():
                for key, btn in icon_buttons.items():
                    btn.bgcolor = "#FFD700" if selected_icon_key["value"] == key else None
                page.update()

            def make_pick_icon(key):
                def _pick(e):
                    selected_icon_key["value"] = key
                    build_icon_grid()
                return _pick

            for key, icon_val in ICON_PALETTE.items():
                icon_buttons[key] = ft.IconButton(icon=icon_val, icon_color=PURPLE_TEXT, on_click=make_pick_icon(key), bgcolor=None)

            icon_grid = ft.Row(
                list(icon_buttons.values()),
                wrap=True, spacing=2,
            )

            async def add_category(e):
                name = (new_cat_field.value or "").strip()
                if not name:
                    add_error_text.value = "Enter a category name."
                    page.update()
                    return
                if name in CATEGORY_OPTIONS:
                    add_error_text.value = "That category already exists."
                    page.update()
                    return
                if not selected_icon_key["value"]:
                    add_error_text.value = "Pick an icon for it."
                    page.update()
                    return
                CATEGORY_OPTIONS.append(name)
                CATEGORY_ICONS[name] = ICON_PALETTE[selected_icon_key["value"]]
                changes.setdefault("added", {})[name] = selected_icon_key["value"]
                if name in changes.get("removed", []):
                    changes["removed"].remove(name)
                await save_category_changes(changes)
                new_cat_field.value = ""
                selected_icon_key["value"] = None
                add_error_text.value = ""
                build_list()
                build_icon_grid()
                page.update()

            dlg = ft.AlertDialog(scrollable=True, 
                modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Manage Categories", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                # No fixed height: the dialog itself scrolls and shrinks with the keyboard.
                # "Add Category" sits in the bottom button bar, so the keyboard can't hide it.
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Add New", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                            new_cat_field,
                            ft.Text("Pick an icon:", color=PURPLE_TEXT, size=12),
                            icon_grid,
                            add_error_text,
                            ft.Divider(height=1, color="#DDDDDD"),
                            ft.Text("Your Categories", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                            list_col,
                        ],
                        spacing=8, tight=True,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.ElevatedButton("Add Category", on_click=add_category, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        async def manage_quick_add_dialog(e):
            shortcuts = await load_quick_add()

            new_label = NFTextField(label="Label", bgcolor="#FFFFFF", color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), dense=True, capitalization=ft.TextCapitalization.WORDS, max_length=30)
            new_label.on_change = with_length_warning(new_label, 30)
            new_type_row, new_type_state = build_type_toggle("expense", on_white=True)
            new_category_picker, new_category_state = build_category_picker("Other")
            new_amount = NFTextField(label="Amount (₦)", keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), dense=True, max_length=15)
            new_amount.on_change = with_length_warning(new_amount, 15)
            error_text = ft.Text("", color="red", size=12)

            list_col = ft.Column([], spacing=6)

            def build_list():
                rows = []
                for i, s in enumerate(shortcuts):
                    def make_remove(idx):
                        async def _remove(e):
                            del shortcuts[idx]
                            await save_quick_add(shortcuts)
                            build_list()
                            await refresh_quick_add_row()
                            page.update()
                        return _remove
                    rows.append(
                        ft.Row(
                            [
                                ft.Text(f"{s.get('label')} (₦{s.get('amount', 0):,.0f})", color=PURPLE_TEXT, size=13, weight=ft.FontWeight.BOLD),
                                ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_remove(i)),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        )
                    )
                list_col.controls = rows if rows else [ft.Text("No shortcuts yet.", color=DARK_TEXT, size=12)]

            build_list()

            async def add_shortcut(e):
                label = (new_label.value or "").strip()
                try:
                    amount = to_number(new_amount.value, required=True)
                except (ValueError, TypeError):
                    error_text.value = "Enter a valid amount."
                    page.update()
                    return
                if not label:
                    error_text.value = "Enter a label."
                    page.update()
                    return
                shortcuts.append({
                    "label": label,
                    "type": new_type_state["value"],
                    "category": new_category_state["value"],
                    "amount": amount,
                    "note": "",
                })
                await save_quick_add(shortcuts)
                new_label.value = ""
                new_amount.value = ""
                error_text.value = ""
                build_list()
                await refresh_quick_add_row()
                page.update()

            async def close_manager(e):
                page.pop_dialog()
                await refresh_quick_add_row()
                page.update()

            dlg = ft.AlertDialog(scrollable=True, 
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Manage Quick Add Shortcuts", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Add New", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                            new_label,
                            new_type_row,
                            new_category_picker,
                            new_amount,
                            error_text,
                            ft.Divider(height=1, color="#DDDDDD"),
                            ft.Text("Your Shortcuts", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                            list_col,
                        ],
                        spacing=10, tight=True,
                    ),
                    width=280,
                ),
                actions=[
                    ft.TextButton("Done", on_click=close_manager, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.ElevatedButton("Save Shortcut", on_click=add_shortcut, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        mt_quick_add_card = ft.Container(
            content=ft.Column(
                [ft.Text("Quick Add", color="white", weight=ft.FontWeight.BOLD, size=13, text_align=ft.TextAlign.CENTER), mt_quick_add_row],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        mt_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Type", mt_type_row),
                    field_with_caption("Category", mt_category_picker),
                    field_with_caption("Amount (₦)", mt_amount_input),
                    field_with_caption("Bank Charges (₦, optional)", mt_charge_input),
                    field_with_caption("Note (optional)", mt_note_input),
                    field_with_caption("Date", mt_date_button),
                    mt_add_btn,
                    mt_status_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20, tight=True
            ),
            padding=20, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK))
        )

        mt_summary_container = ft.Container(
            content=ft.Column([mt_summary_income, mt_summary_expense, mt_summary_charges, ft.Divider(height=1, color="#4B0082"), mt_summary_net], spacing=8, tight=True),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK)),
            scale=1,
            animate_scale=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

        mt_annual_container = ft.Container(
            content=ft.Column(
                [
                    mt_annual_label, ft.Divider(height=1, color="#4B0082"),
                    mt_annual_income, mt_annual_expense, mt_annual_charges, mt_annual_net,
                    ft.Divider(height=1, color="#4B0082"),
                    ft.Text("By Category (Full Year)", color="white", weight=ft.FontWeight.BOLD, size=13),
                    mt_annual_category_list_view,
                ],
                spacing=8, tight=True,
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#1E88E5"), ft.BorderSide(2, "#1E88E5"), ft.BorderSide(2, "#1E88E5"), ft.BorderSide(2, "#1E88E5")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK)),
        )

        # -------------------- MENUS --------------------
        # Main menu: just the four pages (+ Settings). Money Tracker tools live in their own
        # sub-menu, opened from the arrow beside "Money Tracker" or the Options button on that page.
        def _menu_row_content(icon, label, color, trailing=None):
            items = [ft.Icon(icon, color=color, size=20),
                     ft.Text(label, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14, expand=True)]
            if trailing is not None:
                items.append(trailing)
            return ft.Container(content=ft.Row(items, spacing=12), width=240)

        def make_option_row(icon, label, color, action, trailing=None):
            async def run_after_close(e):
                page.pop_dialog()
                await action(e)
            return ft.TextButton(content=_menu_row_content(icon, label, color, trailing), on_click=run_after_close)

        def make_sync_option_row(icon, label, color, action):
            def handler(e):
                page.pop_dialog()
                action(e)
            return ft.TextButton(content=_menu_row_content(icon, label, color), on_click=handler)

        def make_switch_row(icon, label, color, value, on_toggle):
            async def changed(e):
                await on_toggle(e.control.value)
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, color=color, size=20),
                        ft.Text(label, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14, expand=True),
                        ft.Switch(value=value, on_change=changed, active_color="#4B0082"),
                    ],
                    spacing=12,
                ),
                width=240,
                padding=ft.Padding(left=12, right=0, top=0, bottom=0),
            )

        def show_menu_dialog(title, rows, height, back_to=None):
            actions = []
            if back_to is not None:
                def go_back(e):
                    page.pop_dialog()
                    back_to(e)
                actions.append(ft.TextButton("Back", on_click=go_back, style=ft.ButtonStyle(color=PURPLE_TEXT)))
            actions.append(ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)))
            dlg = ft.AlertDialog(scrollable=True,
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text(title, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.ListView(controls=rows, spacing=4),
                    width=270, height=height,
                ),
                actions=actions,
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        def open_money_options_menu(e, from_main_menu=False):
            rows = [
                make_option_row(ft.Icons.PICTURE_AS_PDF_ROUNDED, "Export Month (PDF)", "#C62828", export_month_pdf),
                make_option_row(ft.Icons.PICTURE_AS_PDF_ROUNDED, "Export Year (PDF)", "#C62828", export_year_pdf),
                make_option_row(ft.Icons.BACKUP_ROUNDED, "Backup Data", "#1E88E5", backup_data),
                make_option_row(ft.Icons.RESTORE_ROUNDED, "Restore Data", "#1E88E5", restore_data),
                make_sync_option_row(ft.Icons.HELP_OUTLINE_ROUNDED, "Backup & Restore Help", "#1E88E5", show_backup_help),
                make_option_row(ft.Icons.REPEAT_ROUNDED, "Repeating Entries", "#2E8B57", manage_recurring_dialog),
                make_option_row(ft.Icons.FLASH_ON_ROUNDED, "Quick Add Shortcuts", "#2E8B57", manage_quick_add_dialog),
                make_option_row(ft.Icons.CATEGORY_ROUNDED, "Manage Categories", "#2E8B57", manage_categories_dialog),
            ]
            # Show the button once the listener has captured anything at all (these files are
            # only ever created by the personal build's notification listener).
            if any(os.path.exists(f) for f in (NOTIF_INBOX_FILE, NOTIF_INBOX_FILE + ".processing",
                                               NOTIF_SEEN_PACKAGES_FILE, NOTIF_RECENT_FILE)):
                rows.append(make_option_row(ft.Icons.SYNC_ROUNDED, "Notification Sync", "#2E8B57", open_notification_sync_dialog))
            show_menu_dialog("Money Tracker Options", rows, min(520, 54 * len(rows) + 8),
                             back_to=open_more_options_menu if from_main_menu else None)

        def open_settings_menu(e):
            async def toggle_haptic(on):
                haptic["on"] = bool(on)
                try:
                    await prefs.set("vibrate_on_tap", "on" if on else "off")
                except Exception:
                    pass
                if on:
                    await _buzz()

            async def toggle_motion(on):
                fn = settings_actions.get("motion")
                if fn:
                    await fn(on)

            rows = [
                make_switch_row(ft.Icons.VIBRATION_ROUNDED, "Vibrate on tap", "#8E24AA", haptic["on"], toggle_haptic),
                make_switch_row(ft.Icons.AUTO_AWESOME_ROUNDED, "Motion effects", "#FF8C00", motion["on"], toggle_motion),
                ft.Text("Turn Motion effects off if the app feels slow on your phone.", color="#888888", size=11),
                ft.Divider(height=1, color="#DDDDDD"),
                make_sync_option_row(ft.Icons.LOCK_ROUNDED, f"App lock (PIN): {'On' if pin_state['hash'] else 'Off'}", "#C62828", open_pin_settings),
                make_sync_option_row(ft.Icons.SCHOOL_ROUNDED, "Replay Tutorial", "#FFD700", lambda e: show_tutorial_screen()),
            ]
            show_menu_dialog("Settings", rows, 270, back_to=open_more_options_menu)

        def open_more_options_menu(e):
            def money_options_from_menu(e):
                page.pop_dialog()
                open_money_options_menu(e, from_main_menu=True)

            rows = []
            for i in range(len(tab_labels)):
                if tab_labels[i] == "Money Tracker":
                    trailing = ft.IconButton(
                        icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, icon_color=PURPLE_TEXT,
                        tooltip="Money Tracker options", on_click=money_options_from_menu,
                    )
                else:
                    trailing = None
                rows.append(make_option_row(tab_icons[i], tab_labels[i], tab_icon_colors[i], select_tab(i), trailing))

            def settings_from_menu(e):
                page.pop_dialog()
                open_settings_menu(e)

            rows += [
                ft.Divider(height=1, color="#DDDDDD"),
                ft.TextButton(content=_menu_row_content(ft.Icons.SETTINGS_ROUNDED, "Settings", "#607D8B"),
                              on_click=settings_from_menu),
                ft.Text("Tip: tap the arrow beside Money Tracker for Backup, Restore, PDF export and more.",
                        color="#888888", size=11),
            ]
            show_menu_dialog("Menu", rows, 360)

        money_options_btn = ft.ElevatedButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.TUNE_ROUNDED, size=16, color="white"),
                 ft.Text("Options", color="white", weight=ft.FontWeight.BOLD)],
                spacing=6, tight=True,
            ),
            on_click=lambda e: open_money_options_menu(e),
            style=ft.ButtonStyle(bgcolor="#2E8B57"),
        )

        hamburger_menu_btn = ft.Container(
            content=ft.IconButton(
                icon=ft.Icons.MENU_ROUNDED,
                icon_color="white",
                icon_size=26,
                on_click=open_more_options_menu,
                tooltip="Menu",
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=30,
        )

        mt_chart_card = ft.Container(
            content=mt_chart_container,
            padding=10, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        mt_breakdown_card = ft.Container(
            content=mt_breakdown_container,
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        mt_category_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("By Category (Net)", color="white", weight=ft.FontWeight.BOLD, size=14),
                            ft.TextButton(
                                content=ft.Text("Set Budget", color="#FFD700", weight=ft.FontWeight.BOLD, size=12),
                                on_click=lambda e: open_budget_dialog(),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    mt_category_list_view,
                ],
                spacing=8,
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        mt_list_card = ft.Container(
            content=ft.Column(
                [ft.Text("Transactions (tap to edit)", color="white", weight=ft.FontWeight.BOLD, size=14), mt_search_input, mt_transactions_list_view],
                spacing=8,
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        # Don't read captured bank alerts while the app is opening; that runs a few
        # seconds after the first screen is up (see "after_first_screen" below).
        last_auto_ingest["t"] = time.monotonic()
        try:
            await apply_recurring_all()  # add rent/salary etc. that fell due while the app was closed
        except Exception:
            pass
        await refresh_money_ui()
        await refresh_quick_add_row()

        money_tab_content = ft.Column(
            controls=[
                ft.Row([profile_switcher_btn, money_options_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=10, wrap=True), ft.Container(height=10),
                mt_quick_add_card, ft.Container(height=10),
                mt_form, ft.Container(height=10),
                mt_month_nav, ft.Container(height=5),
                mt_summary_container, ft.Container(height=10),
                mt_annual_container, ft.Container(height=10),
                mt_chart_card, ft.Container(height=10),
                mt_breakdown_card, ft.Container(height=10),
                mt_category_card, ft.Container(height=10),
                mt_list_card,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # ==================================================================
        # AJO (ROTATING SAVINGS GROUP) TAB
        # ==================================================================
        def is_valid_ajo_group(g):
            return (isinstance(g, dict) and isinstance(g.get("id"), str) and g.get("id")
                    and isinstance(g.get("name"), str) and isinstance(g.get("members", []), list))

        async def load_ajo_groups():
            try:
                raw = await prefs.get("ajo_groups")
                groups = json.loads(raw) if raw else []
                # Skip anything that isn't a real group, so one bad entry can never stop the app opening.
                return [g for g in groups if is_valid_ajo_group(g)] if isinstance(groups, list) else []
            except Exception:
                return []

        async def save_ajo_groups(groups):
            # Stamp the time on any group YOU run (admin) whose content changed, so members can
            # tell which shared file is the newest.
            try:
                old_raw = await prefs.get("ajo_groups")
                old = {g.get("id"): g for g in (json.loads(old_raw) if old_raw else []) if isinstance(g, dict)}
            except Exception:
                old = {}
            now_iso = datetime.datetime.now().isoformat(timespec="seconds")
            for g in groups:
                if not isinstance(g, dict) or not g.get("is_admin", True):
                    continue
                prev = old.get(g.get("id"))
                if prev is None or group_fingerprint(prev) != group_fingerprint(g) or not g.get("updated_at"):
                    g["updated_at"] = now_iso
            await prefs.set("ajo_groups", json.dumps(groups))

        async def send_group_file(group_id):
            """Admin: save the group as a file to send to members (WhatsApp → Document)."""
            groups_now = await load_ajo_groups()
            group = next((g for g in groups_now if g.get("id") == group_id), None)
            if not group:
                return
            if not group.get("updated_at"):
                group["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            shared_copy = dict(group)
            shared_copy["is_admin"] = False
            shared_copy.pop("last_shared_at", None)
            export_bytes, ext = make_branded_file("ajo_card.png", json.dumps(shared_copy).encode("utf-8"))
            file_path = await picker_save_file(
                dialog_title="Send Group File",
                file_name=f"NairaFinanceHub_Ajo_{safe_filename(group['name'])}_{datetime.datetime.now().strftime('%d%b_%H%M')}.{ext}",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=[ext],
                src_bytes=export_bytes,
            )
            file_path = file_path or (page.web and file_path is None)  # web: the browser downloads it and returns nothing
            if file_path:
                group["last_shared_at"] = group["updated_at"]
                await save_ajo_groups(groups_now)
                await refresh_ajo_ui()
            page.show_dialog(ft.SnackBar(
                ft.Text("Group file saved! On WhatsApp send it as a Document (📎 → Document), not as a photo. "
                        "Members open it with Import Group from File and their copy updates." if file_path else "Cancelled.", color="white"),
                bgcolor="#8E24AA", duration=ft.Duration(seconds=6), behavior=ft.SnackBarBehavior.FLOATING,
                margin=ft.Margin.only(bottom=300, left=10, right=10)))
            page.update()

        def group_sync_row(group, is_admin):
            """Admin: reminds you to send members the latest file. Member: shows how fresh your copy is."""
            if not is_admin:
                when = fmt_stamp(group.get("updated_at"))
                return ft.Text(
                    f"Admin's update from {when}. Ask the admin for a new file to see later payments." if when
                    else "Ask the admin for a new group file to see the latest payments.",
                    color="#DDDDDD", size=11, italic=True, text_align=ft.TextAlign.CENTER)
            shared = group.get("last_shared_at")
            if shared and shared >= (group.get("updated_at") or ""):
                return ft.Text(f"✓ Members have your latest changes (sent {fmt_stamp(shared)})",
                               color="#5DE88C", size=11, text_align=ft.TextAlign.CENTER)

            async def send(e):
                await send_group_file(group["id"])

            label = ("You have changes your members haven't received." if shared
                     else "Members with the app can follow this group on their phone.")
            return ft.Container(
                content=ft.Row(
                    [ft.Icon(ft.Icons.SYNC_ROUNDED, color="#FFB74D", size=18),
                     ft.Text(label, color="white", size=12, expand=True),
                     ft.TextButton(content=ft.Text("Send update" if shared else "Send file", color="#FFD54F", weight=ft.FontWeight.BOLD, size=12),
                                   on_click=send)],
                    spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding(left=10, right=4, top=2, bottom=2), border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE),
            )

        async def load_active_ajo_id():
            try:
                return await prefs.get("active_ajo_group_id")
            except Exception:
                return None

        async def save_active_ajo_id(gid):
            await prefs.set("active_ajo_group_id", gid or "")

        def new_ajo_id():
            return str(int(datetime.datetime.now().timestamp() * 1000))

        ajo_group_name_text = ft.Text("No Group Selected", color="white", weight=ft.FontWeight.BOLD, size=14)
        ajo_switcher_btn = ft.ElevatedButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.GROUPS_ROUNDED, size=16, color="white"), ajo_group_name_text, ft.Icon(ft.Icons.ARROW_DROP_DOWN, color="white")],
                spacing=6, tight=True,
            ),
            style=ft.ButtonStyle(bgcolor="#1E88E5"),
        )
        ajo_content_area = ft.Container(content=ft.Text("Loading...", color="white"))

        def sanitize_for_pdf(text):
            if not text:
                return ""
            return str(text).encode("latin-1", errors="replace").decode("latin-1")

        def blend_countdown_color(days_left):
            green = (46, 139, 87)
            yellow = (255, 215, 0)
            red = (198, 40, 40)
            max_days = 30
            clamped = max(0, min(days_left, max_days))
            t = 1 - (clamped / max_days)
            if t <= 0.5:
                local_t = t / 0.5
                r = int(green[0] + (yellow[0] - green[0]) * local_t)
                g = int(green[1] + (yellow[1] - green[1]) * local_t)
                b = int(green[2] + (yellow[2] - green[2]) * local_t)
            else:
                local_t = (t - 0.5) / 0.5
                r = int(yellow[0] + (red[0] - yellow[0]) * local_t)
                g = int(yellow[1] + (red[1] - yellow[1]) * local_t)
                b = int(yellow[2] + (red[2] - yellow[2]) * local_t)
            return f"#{r:02x}{g:02x}{b:02x}"

        def build_ajo_pdf_bytes(group, note=""):
            pdf, PF = make_pdf()

            def _san(t):
                return pdf_text(t, PF)
            pdf.add_page()
            pdf.set_font(PF, "B", 16)
            pdf.cell(0, 10, "Naira Finance Hub - Ajo Progress Report", ln=True, align="C")
            pdf.set_font(PF, "", 12)
            pdf.cell(0, 8, _san(group.get("name", "Ajo Group")), ln=True, align="C")
            pdf.set_font(PF, "", 9)
            pdf.cell(0, 6, f"Generated: {datetime.date.today().isoformat()}", ln=True, align="C")
            pdf.ln(6)

            if note:
                pdf.set_font(PF, "B", 12)
                pdf.cell(0, 8, "Note from Admin", ln=True)
                pdf.set_font(PF, "I", 10)
                pdf.multi_cell(0, 6, _san(note))
                pdf.ln(4)

            rules = _san(group.get("rules", ""))
            pdf.set_font(PF, "B", 12)
            pdf.cell(0, 8, "Rules & Regulations", ln=True)
            pdf.set_font(PF, "", 10)
            pdf.multi_cell(0, 6, rules if rules else "No rules have been set.")
            pdf.ln(4)

            order = group.get("order", [])
            round_months = group.get("round_months", [])
            due_day = group.get("due_day", "")
            month_names_pdf = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

            if order:
                pdf.set_font(PF, "B", 12)
                pdf.cell(0, 8, "Full Payout Schedule", ln=True)
                pdf.set_font(PF, "", 10)
                for i, name in enumerate(order):
                    safe_name = _san(name)
                    month_str = ""
                    if i < len(round_months):
                        y_str, m_str = round_months[i].split("-")
                        month_str = f"{month_names_pdf[int(m_str) - 1]} {y_str}"
                    due_str = f" (due by the {due_day})" if due_day else ""
                    pdf.cell(0, 6, f"{i + 1}. {safe_name} - {month_str}{due_str}", ln=True)
                pdf.ln(4)

                current_round = group.get("current_round", 1)
                if current_round <= len(order):
                    raw_collector = order[current_round - 1]
                    collector = _san(raw_collector)
                    contribution = group.get("contribution_amount", 0)
                    payments = group.get("payments", {}).get(str(current_round), {})
                    paid_count_pdf = sum(1 for v in payments.values() if v)
                    total_pot = contribution * (1 + paid_count_pdf)
                    pdf.set_font(PF, "B", 12)
                    pdf.cell(0, 8, f"Current Status - Round {current_round} of {len(order)}", ln=True)
                    pdf.set_font(PF, "", 10)
                    pdf.cell(0, 6, f"Collector: {collector}", ln=True)
                    pdf.cell(0, 6, f"Amount So Far: NGN {total_pot:,.2f}", ln=True)
                    due_day_pdf = group.get("due_day", "")
                    if due_day_pdf and current_round - 1 < len(round_months):
                        try:
                            due_y_str, due_m_str = round_months[current_round - 1].split("-")
                            due_year_pdf, due_month_pdf = int(due_y_str), int(due_m_str)
                            last_day_pdf = calendar.monthrange(due_year_pdf, due_month_pdf)[1]
                            safe_due_day_pdf = min(due_day_pdf, last_day_pdf)
                            actual_due_date_pdf = datetime.date(due_year_pdf, due_month_pdf, safe_due_day_pdf)
                            days_left_pdf = (actual_due_date_pdf - datetime.date.today()).days
                            if days_left_pdf > 0:
                                pdf.cell(0, 6, f"Days Left: {days_left_pdf}", ln=True)
                            elif days_left_pdf == 0:
                                pdf.cell(0, 6, "Due Today", ln=True)
                            else:
                                pdf.cell(0, 6, f"Overdue by {abs(days_left_pdf)} day(s)", ln=True)

                            bar_color_hex = blend_countdown_color(days_left_pdf)
                            bar_r = int(bar_color_hex[1:3], 16)
                            bar_g = int(bar_color_hex[3:5], 16)
                            bar_b = int(bar_color_hex[5:7], 16)
                            bar_fill_ratio = max(0.05, min(1.0, days_left_pdf / 30))
                            bar_x = pdf.get_x()
                            bar_y = pdf.get_y() + 2
                            pdf.set_fill_color(220, 220, 220)
                            pdf.rect(bar_x, bar_y, 60, 4, style="F")
                            pdf.set_fill_color(bar_r, bar_g, bar_b)
                            pdf.rect(bar_x, bar_y, 60 * bar_fill_ratio, 4, style="F")
                            pdf.ln(8)
                        except Exception:
                            pass
                    pdf.ln(4)

                    contributing_members = [m for m in order if m != raw_collector]
                    paid_members = [m for m in contributing_members if payments.get(m, False)]
                    unpaid_members = [m for m in contributing_members if not payments.get(m, False)]
                    pdf.set_font(PF, "B", 12)
                    pdf.cell(0, 8, f"Paid This Round ({len(paid_members)})", ln=True)
                    pdf.set_font(PF, "", 10)
                    if paid_members:
                        for m in paid_members:
                            pdf.cell(0, 6, _san(m), ln=True)
                    else:
                        pdf.cell(0, 6, "No one has paid yet.", ln=True)
                    pdf.ln(2)
                    pdf.set_font(PF, "B", 12)
                    pdf.cell(0, 8, f"Not Yet Paid ({len(unpaid_members)})", ln=True)
                    pdf.set_font(PF, "", 10)
                    if unpaid_members:
                        for m in unpaid_members:
                            pdf.cell(0, 6, _san(m), ln=True)
                    else:
                        pdf.cell(0, 6, "Everyone has paid!", ln=True)
                    pdf.ln(4)
                else:
                    pdf.set_font(PF, "B", 12)
                    pdf.cell(0, 8, "This Ajo cycle is complete.", ln=True)
                    pdf.ln(4)

            history = group.get("history", [])
            if history:
                pdf.set_font(PF, "B", 12)
                pdf.cell(0, 8, "Already Collected (History)", ln=True)
                pdf.set_font(PF, "", 10)
                for h in history:
                    safe_collector = _san(h.get('collector', ''))
                    pdf.cell(0, 6, f"Round {h.get('round')}: {safe_collector} collected NGN {h.get('amount', 0):,.2f} on {h.get('date', '')}", ln=True)

            return bytes(pdf.output())

        async def refresh_ajo_ui():
            groups = await load_ajo_groups()
            active_id = await load_active_ajo_id()

            active_group = None
            for g in groups:
                if g["id"] == active_id:
                    active_group = g
                    break
            if not active_group and groups:
                active_group = groups[0]
                await save_active_ajo_id(active_group["id"])

            if not active_group:
                ajo_group_name_text.value = "No Group"
                ajo_content_area.content = ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("You're not in any Ajo group yet.", color="white", size=14, text_align=ft.TextAlign.CENTER),
                            ft.ElevatedButton("Create Your First Group", on_click=create_ajo_group_dialog, style=ft.ButtonStyle(bgcolor="#8E24AA", color="white")),
                            ft.Text("— or —", color="#888888", size=12),
                            ft.ElevatedButton(
                                content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, color="white", size=18), ft.Text("Import a Shared Group", color="white", weight=ft.FontWeight.BOLD)], spacing=8, tight=True),
                                on_click=import_ajo_group,
                                style=ft.ButtonStyle(bgcolor="#1E88E5"),
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15,
                    ),
                    padding=20, alignment=ft.Alignment(0, 0),
                )
                page.update()
                return

            ajo_group_name_text.value = active_group["name"]
            is_admin = active_group.get("is_admin", True)

            if not active_group.get("order"):
                members_col = ft.Column([], spacing=6)
                member_count_text = ft.Text("", color="#FFD700", weight=ft.FontWeight.BOLD, size=13)

                def update_member_count():
                    n = len(active_group.get("members", []))
                    amt = active_group.get("contribution_amount") or 0
                    pot = f"  ·  Pot per round: ₦{amt * n:,.0f}" if amt and n else ""
                    member_count_text.value = f"{n} member{'s' if n != 1 else ''}{pot}"

                update_member_count()

                # Defined once, before the loop: a brand-new group has no members, so a
                # definition inside the loop never ran and adding the first name crashed.
                def make_remove_member(idx):
                    async def _rm(e):
                        if 0 <= idx < len(active_group.get("members", [])):
                            active_group["members"].pop(idx)
                            await save_ajo_groups(groups)
                        await refresh_ajo_ui()
                    return _rm

                for i, m in enumerate(active_group.get("members", [])):
                    members_col.controls.append(
                        ft.Row(
                            [
                                ft.Text(f"{i + 1}. {m}", color="#FFD700", size=15, weight=ft.FontWeight.BOLD),
                                ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_remove_member(i)) if is_admin else ft.Container(width=16),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        )
                    )

                new_member_field = NFTextField(hint_text="Member name", bgcolor="#FFFFFF", color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), capitalization=ft.TextCapitalization.WORDS, dense=True, expand=True, disabled=not is_admin, max_length=30)
                new_member_field.on_change = with_length_warning(new_member_field, 30)

                async def add_member(e):
                    name = (new_member_field.value or "").strip()
                    if not name:
                        return
                    existing = active_group.setdefault("members", [])
                    # Same person holding a second "hand": label it so the draw and payment
                    # tracking can tell the two slots apart.
                    lower_existing = {m.lower() for m in existing}
                    if name.lower() in lower_existing:
                        n = 2
                        while f"{name} ({n})".lower() in lower_existing:
                            n += 1  # always a brand-new label, even after someone was removed
                        name = f"{name} ({n})"
                        page.show_dialog(ft.SnackBar(ft.Text(f"Added as \"{name}\" — a second hand for the same person.", color="white"), bgcolor=PURPLE_TEXT, duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    existing.append(name)
                    await save_ajo_groups(groups)
                    new_member_field.value = ""
                    new_idx = len(active_group["members"]) - 1
                    members_col.controls.append(
                        ft.Row(
                            [
                                ft.Text(f"{new_idx + 1}. {name}", color="#FFD700", size=15, weight=ft.FontWeight.BOLD),
                                ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_remove_member(new_idx)),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        )
                    )
                    update_member_count()
                    page.update()
                    try:
                        await new_member_field.focus()  # ready for the next name
                    except Exception:
                        pass

                new_member_field.on_submit = add_member  # keyboard ✓ adds the name too

                contribution_field = NFTextField(
                    label="Contribution per person (₦)", value=str(active_group.get("contribution_amount", "")) if active_group.get("contribution_amount") else "",
                    keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", color="black",
                    text_style=ft.TextStyle(color="black", weight=ft.FontWeight.BOLD),
                    disabled=not is_admin, max_length=15,
                )
                contribution_field.on_change = with_length_warning(contribution_field, 15)

                async def save_contribution(e):
                    try:
                        active_group["contribution_amount"] = to_number(contribution_field.value)
                        await save_ajo_groups(groups)
                        update_member_count()
                        page.update()
                    except (ValueError, TypeError):
                        pass

                contribution_field.on_blur = save_contribution

                existing_pending_date = None
                if active_group.get("pending_due_date"):
                    try:
                        existing_pending_date = datetime.date.fromisoformat(active_group["pending_due_date"])
                    except Exception:
                        existing_pending_date = None

                due_date_state = {"value": existing_pending_date}
                due_date_label = ft.Text(
                    f"First Due: {existing_pending_date.strftime('%d %b %Y')}" if existing_pending_date else "Pick First Payment Due Date",
                    color=PURPLE_TEXT, size=13, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER,
                )

                async def on_due_date_picked(e):
                    picked = e.control.value
                    if picked:
                        d = picked_to_date(picked)
                        due_date_state["value"] = d
                        due_date_label.value = f"First Due: {d.strftime('%d %b %Y')}"
                        active_group["pending_due_date"] = d.isoformat()
                        await save_ajo_groups(groups)
                        page.update()

                due_date_picker = ft.DatePicker(
                    first_date=datetime.datetime.now(),
                    last_date=datetime.datetime(datetime.date.today().year + 3, 12, 31),
                    current_date=datetime.datetime.now(),
                    on_change=on_due_date_picked,
                )
                due_date_btn = ft.ElevatedButton(
                    content=ft.Container(content=due_date_label, width=220),
                    on_click=lambda e: page.show_dialog(due_date_picker),
                    style=ft.ButtonStyle(bgcolor="#FFD700"),
                    disabled=not is_admin,
                )

                MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

                twinkle_active = {"value": False}

                def build_starry_background():
                    money_glyphs = ["💵", "💰", "🪙", "💸"]
                    sparkle_glyphs = ["✨", "⭐", "🌟"]

                    money_drops = []
                    for _ in range(14):
                        drop = ft.Container(
                            content=ft.Text(random.choice(money_glyphs), size=random.choice([18, 22, 26])),
                            left=random.randint(5, 340),
                            top=random.randint(-500, -20),
                            rotate=random.uniform(-0.4, 0.4),
                            animate_position=ft.Animation(random.randint(2500, 4500), ft.AnimationCurve.LINEAR),
                        )
                        money_drops.append(drop)

                    sparkles = []
                    for _ in range(10):
                        sparkle = ft.Container(
                            content=ft.Text(random.choice(sparkle_glyphs), size=random.choice([10, 14, 18])),
                            left=random.randint(5, 340),
                            top=random.randint(10, 780),
                            opacity=random.uniform(0.2, 1.0),
                            animate_opacity=ft.Animation(random.randint(700, 1600), ft.AnimationCurve.EASE_IN_OUT),
                        )
                        sparkles.append(sparkle)

                    return (money_drops, sparkles), ft.Stack(controls=money_drops + sparkles, expand=True)

                async def fall_one_drop(drop):
                    try:
                        while twinkle_active["value"]:
                            fall_ms = random.randint(2500, 4500)
                            drop.animate_position = ft.Animation(fall_ms, ft.AnimationCurve.LINEAR)
                            drop.top = random.randint(820, 900)
                            drop.update()  # only this coin, not the whole page
                            await asyncio.sleep(fall_ms / 1000)
                            if not twinkle_active["value"]:
                                break
                            drop.animate_position = ft.Animation(0, ft.AnimationCurve.LINEAR)
                            drop.top = random.randint(-500, -20)
                            drop.left = random.randint(5, 340)
                            drop.update()
                            await asyncio.sleep(0.05)
                    except Exception:
                        pass

                async def twinkle_stars(assets):
                    money_drops, sparkles = assets
                    try:
                        for drop in money_drops:
                            asyncio.create_task(fall_one_drop(drop))
                            await asyncio.sleep(0.15)
                        while twinkle_active["value"]:
                            for s in sparkles:
                                s.opacity = random.uniform(0.15, 1.0)
                                s.update()
                            await asyncio.sleep(1.2)
                    except Exception:
                        pass

                async def close_draw_overlay(e):
                    await stop_draw_music()
                    twinkle_active["value"] = False
                    ajo_draw_overlay_container.visible = False
                    ajo_draw_overlay_container.content = None
                    page.update()
                    await refresh_ajo_ui()

                async def manual_order_dialog(e):
                    members = list(active_group.get("members", []))
                    if len(members) < 2:
                        page.show_dialog(ft.SnackBar(ft.Text("Add at least 2 members first.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return
                    try:
                        typed_contribution = to_number(contribution_field.value)
                    except (ValueError, TypeError):
                        typed_contribution = 0
                    if typed_contribution > 0:
                        active_group["contribution_amount"] = typed_contribution
                        await save_ajo_groups(groups)
                    if not active_group.get("contribution_amount", 0):
                        page.show_dialog(ft.SnackBar(ft.Text("Enter the contribution amount per person first.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return
                    due_date = due_date_state.get("value")
                    if not due_date:
                        page.show_dialog(ft.SnackBar(ft.Text("Pick the first payment due date first.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return

                    selected_order = []
                    remaining = list(members)
                    order_display = ft.Column([], spacing=4)
                    remaining_display = ft.Column([], spacing=4)
                    manual_error_text = ft.Text("", color="red", size=12)

                    def refresh_manual_lists():
                        order_display.controls = [
                            ft.Text(f"{i + 1}. {m}", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14)
                            for i, m in enumerate(selected_order)
                        ]

                        def make_pick(name):
                            def _pick(e):
                                if name not in remaining:  # second tap before the list redrew
                                    return
                                selected_order.append(name)
                                remaining.remove(name)
                                refresh_manual_lists()
                                page.update()
                            return _pick

                        def make_undo(name):
                            def _undo(e):
                                if name not in selected_order:
                                    return
                                selected_order.remove(name)
                                remaining.append(name)
                                # back in its usual place, not at the bottom
                                remaining.sort(key=lambda m: members.index(m) if m in members else len(members))
                                refresh_manual_lists()
                                page.update()
                            return _undo

                        def make_delete_remaining(name):
                            def _ask(e):
                                if name not in remaining:
                                    return

                                async def _confirm(ev):
                                    page.pop_dialog()
                                    if name in remaining:
                                        remaining.remove(name)
                                    if name in members:
                                        members.remove(name)
                                    if name in active_group.get("members", []):
                                        active_group["members"].remove(name)
                                        await save_ajo_groups(groups)
                                    refresh_manual_lists()
                                    page.update()

                                page.show_dialog(ft.AlertDialog(
                                    modal=True, bgcolor="#FFFFFF",
                                    title=ft.Text(f"Remove {name}?", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                                    content=ft.Text(f"{name} will be taken out of this group, not just the order.", color=DARK_TEXT, size=13),
                                    actions=[
                                        ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                                        ft.ElevatedButton("Remove", on_click=_confirm, style=ft.ButtonStyle(bgcolor="#C62828", color="white")),
                                    ],
                                    actions_alignment=ft.MainAxisAlignment.END,
                                ))
                            return _ask

                        remaining_display.controls = [
                            ft.Row(
                                [
                                    ft.TextButton(content=ft.Text(f"+ {m}", color="#2E8B57", weight=ft.FontWeight.BOLD), on_click=make_pick(m)),
                                    ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_delete_remaining(m)),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            )
                            for m in remaining
                        ] + ([
                            ft.TextButton(content=ft.Text(f"Undo last: {selected_order[-1]}", color="#C62828", size=12), on_click=make_undo(selected_order[-1]))
                        ] if selected_order else [])

                    refresh_manual_lists()

                    async def confirm_manual_order(e):
                        if remaining or len(selected_order) < 2:
                            manual_error_text.value = "Tap every member above before confirming (at least 2 needed)."
                            page.update()
                            return
                        page.pop_dialog()
                        await reveal_manual_order(list(selected_order), due_date)

                    manual_dlg = ft.AlertDialog(scrollable=True, 
                        modal=True, bgcolor="#FFFFFF",
                        title=ft.Text("Set Order Manually", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        content=ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text("Tap members below in the order they should collect:", color=DARK_TEXT, size=12),
                                    ft.Text("Selected Order:", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                                    order_display,
                                    ft.Divider(height=1, color="#DDDDDD"),
                                    ft.Text("Remaining Members:", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                                    remaining_display,
                                    manual_error_text,
                                ],
                                spacing=8, scroll=ft.ScrollMode.AUTO, tight=True,
                            ),
                            width=280, height=380,
                        ),
                        actions=[
                            ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                            ft.TextButton("Confirm Order", on_click=confirm_manual_order, style=ft.ButtonStyle(color="#2E8B57")),
                        ],
                        actions_alignment=ft.MainAxisAlignment.END,
                    )
                    page.show_dialog(manual_dlg)

                async def draw_order(e):
                    members = list(active_group.get("members", []))
                    if len(members) < 2:
                        page.show_dialog(ft.SnackBar(ft.Text("Add at least 2 members first.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return
                    try:
                        typed_contribution = to_number(contribution_field.value)
                    except (ValueError, TypeError):
                        typed_contribution = 0
                    if typed_contribution > 0:
                        active_group["contribution_amount"] = typed_contribution
                        await save_ajo_groups(groups)
                    if not active_group.get("contribution_amount", 0):
                        page.show_dialog(ft.SnackBar(ft.Text("Enter the contribution amount per person first.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return
                    due_date = due_date_state.get("value")
                    if not due_date:
                        page.show_dialog(ft.SnackBar(ft.Text("Pick the first payment due date first.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return

                    async def show_recording_reminder():
                        async def start_after_reminder(e):
                            page.pop_dialog()
                            await run_the_draw(due_date)

                        reminder_dlg = ft.AlertDialog(scrollable=True, 
                            modal=True, bgcolor="#FFFFFF",
                            title=ft.Text("Ready to Draw?", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                            content=ft.Text(
                                "For a bias-free record you can share with the group, swipe down now and start your phone's built-in Screen Recorder before continuing.",
                                color=DARK_TEXT, size=13,
                            ),
                            actions=[
                                ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                                ft.TextButton("I'm Ready — Start Draw", on_click=start_after_reminder, style=ft.ButtonStyle(color="#2E8B57")),
                            ],
                            actions_alignment=ft.MainAxisAlignment.END,
                        )
                        page.show_dialog(reminder_dlg)

                    review_rows_col = ft.Column([], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)  # fills the box and scrolls inside it

                    def build_review_rows():
                        def make_delete_from_review(name):
                            async def _delete(e):
                                if name in active_group.get("members", []):
                                    active_group["members"].remove(name)
                                    await save_ajo_groups(groups)
                                members[:] = list(active_group.get("members", []))
                                build_review_rows()
                                review_dlg.title = ft.Text(f"Review Members ({len(members)})", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)
                                page.update()
                            return _delete

                        review_rows_col.controls = [
                            ft.Row(
                                [
                                    ft.Text(f"{i + 1}. {m}", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14),
                                    ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_delete_from_review(m)),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            )
                            for i, m in enumerate(members)
                        ]

                    build_review_rows()

                    async def proceed_to_reminder(e):
                        if len(members) < 2:
                            page.pop_dialog()
                            page.show_dialog(ft.SnackBar(ft.Text("Add at least 2 members first.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                            page.update()
                            return
                        page.pop_dialog()
                        await show_recording_reminder()

                    review_dlg = ft.AlertDialog(scrollable=True, 
                        modal=True, bgcolor="#FFFFFF",
                        title=ft.Text(f"Review Members ({len(members)})", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        content=ft.Container(
                            content=ft.Column(
                                [ft.Text("Check the list below for mistakes or missing names before drawing. Tap ✕ to remove someone.", color=DARK_TEXT, size=12), review_rows_col],
                                spacing=8, tight=True,
                            ),
                            width=280, height=320,
                        ),
                        actions=[
                            ft.TextButton("Go Back & Edit", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                            ft.TextButton("Looks Good, Continue", on_click=proceed_to_reminder, style=ft.ButtonStyle(color="#2E8B57")),
                        ],
                        actions_alignment=ft.MainAxisAlignment.END,
                    )
                    page.show_dialog(review_dlg)

                async def run_the_draw(due_date):
                    rng = random.SystemRandom()  # OS-level randomness: fair and unpredictable
                    pool = list(active_group.get("members", []))
                    total_n = len(pool)

                    round_months = []
                    for i in range(total_n):
                        total = (due_date.month - 1) + i
                        y = due_date.year + total // 12
                        m = total % 12 + 1
                        round_months.append(f"{y}-{m:02d}")
                    month_labels = [f"{MONTH_NAMES[int(rm.split('-')[1]) - 1]} {rm.split('-')[0]}" for rm in round_months]
                    draw_started = datetime.datetime.now()

                    slide_container = ft.Container(
                        content=None, opacity=1, scale=1,
                        animate_opacity=ft.Animation(350, ft.AnimationCurve.EASE_IN_OUT),
                        animate_scale=ft.Animation(350, ft.AnimationCurve.EASE_IN_OUT),
                        alignment=ft.Alignment(0, 0), expand=True, padding=20,
                    )
                    confetti_layer = ft.Stack([], expand=True)
                    animated_assets, starry_stack = build_starry_background()
                    ajo_draw_overlay_container.content = ft.Stack([starry_stack, slide_container, confetti_layer], expand=True)
                    ajo_draw_overlay_container.visible = True
                    twinkle_active["value"] = True
                    page.update()
                    asyncio.create_task(twinkle_stars(animated_assets))

                    def play(sound):
                        if not draw_sound["on"]:
                            return
                        try:
                            asyncio.create_task(sound.play())
                        except Exception:
                            pass

                    async def toggle_sound(e):
                        draw_sound["on"] = not draw_sound["on"]
                        sound_btn.icon = ft.Icons.VOLUME_UP_ROUNDED if draw_sound["on"] else ft.Icons.VOLUME_OFF_ROUNDED
                        if draw_sound["on"]:
                            await start_draw_music()
                        else:
                            await stop_draw_music()
                        sound_btn.update()

                    sound_btn = ft.IconButton(
                        icon=ft.Icons.VOLUME_UP_ROUNDED if draw_sound["on"] else ft.Icons.VOLUME_OFF_ROUNDED,
                        icon_color="#FFD700", tooltip="Sound on/off", on_click=toggle_sound,
                    )

                    async def confetti_burst():
                        pieces = []
                        for _ in range(18):
                            c = ft.Container(
                                content=ft.Text(rng.choice(["🎉", "🎊", "✨", "⭐", "💛", "💚"]), size=rng.choice([16, 20, 24])),
                                left=165, top=250, opacity=1,
                                animate_position=ft.Animation(rng.randint(700, 1100), ft.AnimationCurve.EASE_OUT),
                                animate_opacity=ft.Animation(1100, ft.AnimationCurve.EASE_IN),
                            )
                            pieces.append(c)
                        confetti_layer.controls = pieces
                        confetti_layer.update()
                        await asyncio.sleep(0.03)
                        for c in pieces:
                            c.left = rng.randint(0, 340)
                            c.top = rng.randint(60, 600)
                            c.opacity = 0
                        confetti_layer.update()

                    # ---- live draw screen ----
                    skip = {"value": False}

                    def on_skip(e):
                        skip["value"] = True

                    header_pos = ft.Text("", color="#FFD700", weight=ft.FontWeight.BOLD, size=18, text_align=ft.TextAlign.CENTER)
                    header_month = ft.Text("", color="#7CFC9A", weight=ft.FontWeight.BOLD, size=15, text_align=ft.TextAlign.CENTER)
                    reel_text = ft.Text("", color="white", weight=ft.FontWeight.BOLD, size=30, text_align=ft.TextAlign.CENTER, max_lines=1)
                    reel_box = ft.Container(
                        content=reel_text, width=300, height=100, alignment=ft.Alignment(0, 0),
                        bgcolor="#1B0B2E", border_radius=18,
                        border=ft.Border(ft.BorderSide(3, "#FFD700"), ft.BorderSide(3, "#FFD700"), ft.BorderSide(3, "#FFD700"), ft.BorderSide(3, "#FFD700")),
                        scale=1, animate_scale=ft.Animation(250, ft.AnimationCurve.EASE_OUT_BACK),
                        shadow=ft.BoxShadow(blur_radius=18, color=ft.Colors.with_opacity(0.5, "#FFD700")),
                    )
                    status_text = ft.Text("", color="white", size=14, text_align=ft.TextAlign.CENTER)
                    bowl_label = ft.Text("", color="#FFD700", size=12, weight=ft.FontWeight.BOLD)
                    bowl_row = ft.Row([], wrap=True, spacing=6, run_spacing=6, alignment=ft.MainAxisAlignment.CENTER)
                    drawn_col = ft.Column([], spacing=4, scroll=ft.ScrollMode.AUTO, auto_scroll=True)

                    def render_bowl():
                        bowl_label.value = f"Still in the bowl ({len(pool)})"
                        bowl_row.controls = [
                            ft.Container(content=ft.Text(n, color="white", size=11), padding=ft.Padding(left=8, right=8, top=3, bottom=3),
                                         border_radius=12, bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.WHITE))
                            for n in pool
                        ]

                    slide_container.content = ft.Column(
                        [
                            ft.Row([ft.Text("🎲 LIVE AJO DRAW", color="#FFD700", weight=ft.FontWeight.BOLD, size=22), sound_btn],
                                   alignment=ft.MainAxisAlignment.CENTER, spacing=4),
                            ft.Text(f"{active_group.get('name', '')}  ·  {total_n} members", color="white", size=12),
                            ft.Container(height=6),
                            header_pos, header_month, reel_box, status_text,
                            ft.Container(height=4),
                            bowl_label,
                            ft.Container(content=bowl_row, height=70),
                            ft.Text("Drawn so far", color="#FFD700", size=12, weight=ft.FontWeight.BOLD),
                            ft.Container(content=drawn_col, height=150, width=300),
                            ft.TextButton("Skip animation ▶▶", on_click=on_skip, style=ft.ButtonStyle(color="#BBBBBB")),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER,
                        spacing=6, expand=True, scroll=ft.ScrollMode.AUTO,
                    )
                    render_bowl()
                    page.update()
                    await start_draw_music()
                    await asyncio.sleep(0.8)  # let the groove kick in before the first spin

                    members = []
                    for i in range(total_n):
                        header_pos.value = f"Drawing position #{i + 1} of {total_n}"
                        header_month.value = f"Collects in {month_labels[i]}"

                        if len(pool) == 1:
                            winner = pool[0]
                            status_text.value = "Last name in the bowl"
                        else:
                            winner = rng.choice(pool)  # picked live, from whoever is left right now
                            if not skip["value"]:
                                status_text.value = "Shuffling..."
                                # spin fast, then slow down like a real reel
                                spins = 14 if total_n <= 12 else 9
                                # fast-then-slow timing, stretched to 2.3 s so the drum
                                # roll's cymbal crash lands exactly as the name appears
                                base = [0.06 + (k / spins) ** 2 * 0.35 for k in range(spins)]
                                scale = 2.3 / sum(base)
                                play(drumroll_sound)
                                for k in range(spins):
                                    if skip["value"]:
                                        break
                                    reel_text.value = rng.choice(pool)
                                    reel_text.update()
                                    status_text.update()
                                    if k % 2 == 0:
                                        play(dice_tick_sound)
                                    await asyncio.sleep(base[k] * scale)
                            status_text.value = "🎉 Picked!"

                        pool.remove(winner)
                        members.append(winner)
                        reel_text.value = winner
                        reel_box.scale = 1.15
                        drawn_col.controls.append(ft.Text(f"{i + 1}. {winner}  —  {month_labels[i]}", color="white", size=13, weight=ft.FontWeight.BOLD))
                        render_bowl()
                        page.update()
                        if not skip["value"]:
                            play(reveal_ding_sound)
                            play(cheer_sound)
                            await confetti_burst()
                            await asyncio.sleep(0.9)
                        reel_box.scale = 1
                        reel_box.update()

                    await asyncio.sleep(0.4 if not skip["value"] else 0.1)
                    confetti_layer.controls = []

                    active_group["order"] = members
                    active_group["round_months"] = round_months
                    active_group["due_day"] = due_date.day
                    active_group["current_round"] = 1
                    active_group["payments"] = {"1": {m: False for m in members if m != members[0]}}
                    active_group["history"] = []
                    active_group.pop("pending_due_date", None)
                    await save_ajo_groups(groups)

                    slide_container.opacity = 0
                    slide_container.scale = 0.9
                    page.update()
                    await asyncio.sleep(0.3)

                    summary_chips = [
                        ft.Container(
                            content=ft.Text(f"{i + 1}. {name}\n{month_labels[i]}", color="white", weight=ft.FontWeight.BOLD, size=13, text_align=ft.TextAlign.CENTER),
                            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.WHITE), border_radius=10, padding=10, width=150,
                        )
                        for i, name in enumerate(members)
                    ]

                    async def reshuffle(e):
                        await run_the_draw(due_date)

                    slide_container.content = ft.Column(
                        [
                            ft.Text("✅ Final Order", color="#FFD700", weight=ft.FontWeight.BOLD, size=24),
                            ft.Text(f"Drawn live on {draw_started.strftime('%d %b %Y, %I:%M %p')}", color="white", size=12),
                            ft.Container(
                                content=ft.Row(summary_chips, wrap=True, alignment=ft.MainAxisAlignment.CENTER, spacing=8, run_spacing=8, scroll=ft.ScrollMode.AUTO),
                                width=340, height=350,
                            ),
                            ft.Row(
                                [
                                    ft.ElevatedButton(
                                        content=ft.Row([ft.Icon(ft.Icons.REPLAY_ROUNDED, color="white", size=16), ft.Text("Reshuffle", color="white", weight=ft.FontWeight.BOLD)], spacing=4, tight=True),
                                        on_click=reshuffle,
                                        style=ft.ButtonStyle(bgcolor="#8E24AA"),
                                    ),
                                    ft.ElevatedButton("Continue", on_click=close_draw_overlay, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                                ],
                                alignment=ft.MainAxisAlignment.CENTER, spacing=10,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=18, expand=True,
                    )
                    slide_container.opacity = 1
                    slide_container.scale = 1
                    page.update()
                    await stop_draw_music()
                    if draw_sound["on"]:
                        try:
                            asyncio.create_task(fanfare_sound.play())
                            asyncio.create_task(cheer_sound.play())
                        except Exception:
                            pass

                async def reveal_manual_order(chosen_order, due_date):
                    round_months = []
                    for i in range(len(chosen_order)):
                        total = (due_date.month - 1) + i
                        y = due_date.year + total // 12
                        mth = total % 12 + 1
                        round_months.append(f"{y}-{mth:02d}")

                    slide_container = ft.Container(
                        content=None,
                        opacity=1,
                        scale=1,
                        animate_opacity=ft.Animation(350, ft.AnimationCurve.EASE_IN_OUT),
                        animate_scale=ft.Animation(350, ft.AnimationCurve.EASE_IN_OUT),
                        alignment=ft.Alignment(0, 0),
                        expand=True,
                        padding=30,
                    )
                    animated_assets, starry_stack = build_starry_background()
                    ajo_draw_overlay_container.content = ft.Stack([starry_stack, slide_container], expand=True)
                    ajo_draw_overlay_container.visible = True
                    twinkle_active["value"] = True
                    page.update()
                    asyncio.create_task(twinkle_stars(animated_assets))

                    await start_draw_music()
                    slide_container.content = ft.Column(
                        [ft.Text("📝 Confirming Your Arrangement", color="#FFD700", weight=ft.FontWeight.BOLD, size=22, text_align=ft.TextAlign.CENTER)],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, expand=True,
                    )
                    page.update()
                    await asyncio.sleep(1.2)

                    month_labels = []
                    for i in range(len(chosen_order)):
                        y_str, m_str = round_months[i].split("-")
                        month_labels.append(f"{MONTH_NAMES[int(m_str) - 1]} {y_str}")

                    for i, name in enumerate(chosen_order):
                        slide_container.opacity = 0
                        slide_container.scale = 0.9
                        page.update()
                        await asyncio.sleep(0.3)
                        slide_container.content = ft.Column(
                            [
                                ft.Text(f"#{i + 1} of {len(chosen_order)}", color="#FFD700", weight=ft.FontWeight.BOLD, size=20),
                                ft.Text(name, color="white", weight=ft.FontWeight.BOLD, size=40, text_align=ft.TextAlign.CENTER),
                                ft.Text(month_labels[i], color="#2E8B57", weight=ft.FontWeight.BOLD, size=20),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=14, expand=True,
                        )
                        slide_container.opacity = 1
                        slide_container.scale = 1
                        page.update()
                        try:
                            asyncio.create_task(dice_tick_sound.play())
                        except Exception:
                            pass
                        await asyncio.sleep(1.1)

                    active_group["order"] = chosen_order
                    active_group["round_months"] = round_months
                    active_group["due_day"] = due_date.day
                    active_group["current_round"] = 1
                    active_group["payments"] = {"1": {m: False for m in chosen_order if m != chosen_order[0]}}
                    active_group["history"] = []
                    active_group.pop("pending_due_date", None)
                    await save_ajo_groups(groups)

                    slide_container.opacity = 0
                    slide_container.scale = 0.9
                    page.update()
                    await asyncio.sleep(0.3)

                    summary_chips = [
                        ft.Container(
                            content=ft.Text(f"{i + 1}. {name}\n{month_labels[i]}", color="white", weight=ft.FontWeight.BOLD, size=13, text_align=ft.TextAlign.CENTER),
                            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.WHITE), border_radius=10, padding=10, width=150,
                        )
                        for i, name in enumerate(chosen_order)
                    ]

                    slide_container.content = ft.Column(
                        [
                            ft.Text("✅ Final Order", color="#FFD700", weight=ft.FontWeight.BOLD, size=24),
                            ft.Container(
                                content=ft.Row(summary_chips, wrap=True, alignment=ft.MainAxisAlignment.CENTER, spacing=8, run_spacing=8, scroll=ft.ScrollMode.AUTO),
                                width=340, height=350,
                            ),
                            ft.ElevatedButton("Continue", on_click=close_draw_overlay, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=18, expand=True,
                    )
                    slide_container.opacity = 1
                    slide_container.scale = 1
                    page.update()
                    await stop_draw_music()
                    if draw_sound["on"]:
                        try:
                            asyncio.create_task(fanfare_sound.play())
                            asyncio.create_task(cheer_sound.play())
                        except Exception:
                            pass

                async def discard_setup(e):
                    async def do_discard(ev):
                        page.pop_dialog()
                        active_group["members"] = []
                        active_group["contribution_amount"] = 0
                        active_group.pop("pending_due_date", None)
                        await save_ajo_groups(groups)
                        await refresh_ajo_ui()

                    page.show_dialog(ft.AlertDialog(
                        modal=True, bgcolor="#FFFFFF",
                        title=ft.Text("Discard the setup?", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        content=ft.Text("All members, the contribution amount and the due date you entered will be cleared.",
                                        color=DARK_TEXT, size=13),
                        actions=[
                            ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                            ft.ElevatedButton("Discard", on_click=do_discard, style=ft.ButtonStyle(bgcolor="#C62828", color="white")),
                        ],
                        actions_alignment=ft.MainAxisAlignment.END,
                    ))

                has_something_to_discard = bool(active_group.get("members")) or bool(active_group.get("contribution_amount"))

                ajo_content_area.content = ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("Set Up Your Group", color="white", weight=ft.FontWeight.BOLD, size=15),
                                    ft.TextButton(
                                        content=ft.Row([ft.Icon(ft.Icons.UNDO_ROUNDED, color="#C62828", size=14), ft.Text("Discard", color="#C62828", size=12)], spacing=4),
                                        on_click=discard_setup,
                                    ) if (is_admin and has_something_to_discard) else ft.Container(width=0),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Container(
                                content=ft.Text("👁 View Only — Only the Admin can edit this group", color="#FFD700", size=11, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                            ) if not is_admin else ft.Container(height=0),
                            group_sync_row(active_group, is_admin) if not is_admin else ft.Container(height=0),
                            contribution_field,
                            due_date_btn,
                            ft.Divider(height=1, color="#4B0082"),
                            ft.Row([ft.Text("Members", color="white", weight=ft.FontWeight.BOLD, size=13), member_count_text],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
                            members_col,
                            ft.Row([new_member_field, ft.IconButton(icon=ft.Icons.ADD_CIRCLE_ROUNDED, icon_color="#2E8B57", icon_size=28, on_click=add_member, disabled=not is_admin)]),
                            ft.Divider(height=1, color="#4B0082"),
                            ft.ElevatedButton(
                                content=ft.Row([ft.Icon(ft.Icons.CASINO_ROUNDED, color="white", size=18), ft.Text("Draw Order", color="white", weight=ft.FontWeight.BOLD)], spacing=6, tight=True),
                                on_click=draw_order,
                                style=ft.ButtonStyle(bgcolor="#8E24AA"),
                                disabled=not is_admin,
                            ),
                            ft.ElevatedButton(
                                content=ft.Row([ft.Icon(ft.Icons.EDIT_NOTE_ROUNDED, color="white", size=18), ft.Text("Set Order Manually", color="white", weight=ft.FontWeight.BOLD)], spacing=6, tight=True),
                                on_click=manual_order_dialog,
                                style=ft.ButtonStyle(bgcolor="#1E88E5"),
                                disabled=not is_admin,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=15, border_radius=15,
                    bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
                )
                page.update()
                try:
                    await new_member_field.focus()
                except Exception:
                    pass
                return

            # Group has an order set — show round tracker
            order = active_group["order"]
            current_round = active_group.get("current_round", 1)
            contribution = active_group.get("contribution_amount", 0)

            if current_round > len(order):
                history_rows = [
                    ft.Text(f"Round {h['round']}: {h['collector']} collected ₦{h['amount']:,.2f}", color="white", size=13)
                    for h in active_group.get("history", [])
                ]

                async def save_history(e):
                    active_group.setdefault("past_cycles", []).append({
                        "history": list(active_group.get("history", [])),
                        "order": list(active_group.get("order", [])),
                        "contribution_amount": active_group.get("contribution_amount", 0),
                    })
                    active_group["members"] = []
                    active_group["order"] = []
                    active_group["round_months"] = []
                    active_group["current_round"] = 1
                    active_group["payments"] = {}
                    active_group["history"] = []
                    active_group["contribution_amount"] = 0
                    active_group.pop("due_day", None)
                    active_group.pop("pending_due_date", None)
                    await save_ajo_groups(groups)
                    await refresh_ajo_ui()

                ajo_content_area.content = ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("🎉 This Ajo Cycle is Complete!", color="#FFD700", weight=ft.FontWeight.BOLD, size=17, text_align=ft.TextAlign.CENTER),
                            ft.Text("Everyone has collected their round.", color="white", size=13, text_align=ft.TextAlign.CENTER),
                            ft.Divider(height=1, color="#4B0082"),
                            ft.Text("History", color="white", weight=ft.FontWeight.BOLD, size=13),
                            ft.Column(history_rows, spacing=6),
                            ft.Divider(height=1, color="#4B0082"),
                            ft.Text(
                                "Tap 'Save History' to archive this cycle and get a fresh setup screen for your next cycle. To reuse this arrangement, go to the group switcher → 'Past Cycles' and tap 'Launch This Arrangement'.",
                                color="#FFD700", size=11, text_align=ft.TextAlign.CENTER,
                            ) if is_admin else ft.Container(height=0),
                            ft.ElevatedButton(
                                content=ft.Row([ft.Icon(ft.Icons.SAVE_ROUNDED, color="white", size=18), ft.Text("Save History", color="white", weight=ft.FontWeight.BOLD)], spacing=6, tight=True),
                                on_click=save_history,
                                style=ft.ButtonStyle(bgcolor="#8E24AA"),
                                disabled=not is_admin,
                            ) if is_admin else ft.Container(height=0),
                        ],
                        spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=15, border_radius=15,
                    bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
                )
                page.update()
                return

            collector = order[current_round - 1]
            payments = active_group.setdefault("payments", {}).setdefault(str(current_round), {m: False for m in order if m != collector})

            MONTH_NAMES_DISPLAY = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
            round_months = active_group.get("round_months", [])

            async def edit_order_dialog(e):
                if paid_count > 0:
                    page.show_dialog(ft.SnackBar(ft.Text("⚠️ Payment has already been done currently.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                    return
                already_collected = list(order[:current_round - 1])
                pending = list(order[current_round - 1:])
                edit_error_text = ft.Text("", color="red", size=12)
                edit_list_col = ft.Column([], spacing=6)

                def build_edit_list():
                    rows = []
                    for i, name in enumerate(pending):
                        def make_move_up(idx):
                            def _up(e):
                                if idx > 0:
                                    pending[idx - 1], pending[idx] = pending[idx], pending[idx - 1]
                                    build_edit_list()
                                    page.update()
                            return _up

                        def make_move_down(idx):
                            def _down(e):
                                if idx < len(pending) - 1:
                                    pending[idx + 1], pending[idx] = pending[idx], pending[idx + 1]
                                    build_edit_list()
                                    page.update()
                            return _down

                        def make_delete(idx):
                            def _del(e):
                                if len(pending) <= 1:
                                    edit_error_text.value = "At least one pending member must remain."
                                    page.update()
                                    return
                                pending.pop(idx)
                                edit_error_text.value = ""
                                build_edit_list()
                                page.update()
                            return _del

                        rows.append(
                            ft.Row(
                                [
                                    ft.Text(f"{current_round + i}. {name}", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                                    ft.Row(
                                        [
                                            ft.IconButton(icon=ft.Icons.ARROW_UPWARD_ROUNDED, icon_size=16, icon_color=PURPLE_TEXT, on_click=make_move_up(i), disabled=(i == 0)),
                                            ft.IconButton(icon=ft.Icons.ARROW_DOWNWARD_ROUNDED, icon_size=16, icon_color=PURPLE_TEXT, on_click=make_move_down(i), disabled=(i == len(pending) - 1)),
                                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_size=16, icon_color="#C62828", on_click=make_delete(i)),
                                        ],
                                        spacing=0,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            )
                        )
                    edit_list_col.controls = rows

                build_edit_list()

                async def save_edit_order(e):
                    if not pending:
                        edit_error_text.value = "At least one pending member must remain."
                        page.update()
                        return
                    deleted_members = set(order[current_round - 1:]) - set(pending)

                    new_full_order = already_collected + pending
                    new_round_months = list(round_months[:current_round - 1])
                    if round_months and current_round - 1 < len(round_months):
                        start_y, start_m = round_months[current_round - 1].split("-")
                        start_y, start_m = int(start_y), int(start_m)
                    else:
                        today_now = datetime.date.today()
                        start_y, start_m = today_now.year, today_now.month
                    for i in range(len(pending)):
                        total = (start_m - 1) + i
                        y = start_y + total // 12
                        mth = total % 12 + 1
                        new_round_months.append(f"{y}-{mth:02d}")

                    for deleted_name in deleted_members:
                        for round_key in list(active_group.get("payments", {}).keys()):
                            active_group["payments"][round_key].pop(deleted_name, None)

                    active_group["order"] = new_full_order
                    active_group["round_months"] = new_round_months
                    # Everyone except this round's collector pays — including members who already
                    # collected in earlier rounds. Keep any "paid" ticks already made this round.
                    old_round_pay = active_group.get("payments", {}).get(str(current_round), {})
                    active_group.setdefault("payments", {})[str(current_round)] = {
                        m: bool(old_round_pay.get(m, False)) for m in new_full_order if m != pending[0]}
                    await save_ajo_groups(groups)
                    page.pop_dialog()
                    await refresh_ajo_ui()

                edit_dlg = ft.AlertDialog(scrollable=True, 
                    modal=True, bgcolor="#FFFFFF",
                    title=ft.Text("Edit Order", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("Reposition or remove members from this round onward. Already-completed rounds are not affected.", color=DARK_TEXT, size=12),
                                edit_list_col,
                                edit_error_text,
                            ],
                            spacing=8, scroll=ft.ScrollMode.AUTO, tight=True,
                        ),
                        width=290, height=350,
                    ),
                    actions=[
                        ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                        ft.TextButton("Save Changes", on_click=save_edit_order, style=ft.ButtonStyle(color="#2E8B57")),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                page.show_dialog(edit_dlg)

            due_day = active_group.get("due_day", "")
            countdown_text = ""
            countdown_color = "#2E8B57"
            countdown_fill_ratio = 1.0
            if current_round - 1 < len(round_months):
                y_str, m_str = round_months[current_round - 1].split("-")
                round_month_display = f"{MONTH_NAMES_DISPLAY[int(m_str) - 1]} {y_str}"
                if due_day:
                    if due_day in (1, 21, 31):
                        suffix = "st"
                    elif due_day in (2, 22):
                        suffix = "nd"
                    elif due_day in (3, 23):
                        suffix = "rd"
                    else:
                        suffix = "th"
                    round_month_display += f" — Due by the {due_day}{suffix}"

                    try:
                        due_year, due_month = int(y_str), int(m_str)
                        last_day_of_month = calendar.monthrange(due_year, due_month)[1]
                        safe_due_day = min(due_day, last_day_of_month)
                        actual_due_date = datetime.date(due_year, due_month, safe_due_day)
                        days_left = (actual_due_date - datetime.date.today()).days
                        countdown_color = blend_countdown_color(days_left)
                        countdown_fill_ratio = max(0.05, min(1.0, days_left / 30))
                        if days_left > 1:
                            countdown_text = f"⏰ {days_left} days left"
                        elif days_left == 1:
                            countdown_text = "⏰ 1 day left"
                        elif days_left == 0:
                            countdown_text = "⏰ Due today!"
                        else:
                            countdown_text = f"⚠️ Overdue by {abs(days_left)} day{'s' if abs(days_left) != 1 else ''}"
                    except Exception:
                        pass
            else:
                round_month_display = ""

            def make_toggle_paid(member):
                async def _toggle(e):
                    if not is_admin:
                        return
                    payments[member] = not payments.get(member, False)
                    await save_ajo_groups(groups)
                    await refresh_ajo_ui()
                return _toggle

            def build_member_row(m, paid):
                member_idx = order.index(m)
                member_month_display = ""
                if member_idx < len(round_months):
                    my_y, my_m = round_months[member_idx].split("-")
                    member_month_display = f"{MONTH_NAMES_DISPLAY[int(my_m) - 1]} {my_y}"
                return ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED if paid else ft.Icons.RADIO_BUTTON_UNCHECKED, color="#2E8B57" if paid else "#888888", size=20),
                            ft.Container(
                                content=ft.Text(m, color="#2E8B57" if paid else "white", size=14, weight=ft.FontWeight.BOLD),
                                width=110,
                            ),
                            ft.Icon(ft.Icons.ARROW_FORWARD_ROUNDED, color="#FFD700", size=14),
                            ft.Text(member_month_display, color="#FFD700", size=12, weight=ft.FontWeight.BOLD),
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        spacing=10,
                    ),
                    on_click=make_toggle_paid(m) if is_admin else None,
                    padding=ft.Padding(top=8, bottom=8, left=4, right=4),
                    ink=is_admin,
                )

            unpaid_rows = []
            paid_rows = []
            for m in order:
                if m == collector:
                    continue
                paid = payments.get(m, False)
                target = paid_rows if paid else unpaid_rows
                if target:
                    target.append(ft.Divider(height=1, color="#4B0082"))
                target.append(build_member_row(m, paid))

            paid_count = sum(1 for v in payments.values() if v)
            total_pot = contribution * (1 + paid_count)

            async def advance_round(e):
                if paid_count < len(payments):
                    page.show_dialog(ft.SnackBar(ft.Text("⚠️ All payments have not been completed yet.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                    return
                await do_advance()

            async def do_advance():
                if active_group.get("current_round", 1) != current_round:
                    return  # a second tap on "Advance" — this round was already closed
                active_group.setdefault("history", []).append({
                    "round": current_round, "collector": collector, "amount": total_pot,
                    "date": datetime.date.today().isoformat(),
                })
                active_group["current_round"] = current_round + 1
                next_round = current_round + 1
                if next_round <= len(order):
                    next_collector_for_payments = order[next_round - 1]
                    active_group["payments"][str(next_round)] = {m: False for m in order if m != next_collector_for_payments}
                await save_ajo_groups(groups)
                await refresh_ajo_ui()
                if next_round <= len(order):
                    next_collector = order[next_round - 1]
                    page.show_dialog(ft.SnackBar(ft.Text(f"➡️ Next up: {next_collector} — contribute for their round!", color="white"), bgcolor="#8E24AA", duration=ft.Duration(seconds=4), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                else:
                    page.show_dialog(ft.SnackBar(ft.Text("🎉 That was the last round — the cycle is complete!", color="white"), bgcolor="#FFD700", duration=ft.Duration(seconds=4), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()

            ajo_content_area.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Text("👁 View Only — Only the Admin can edit this group", color="#FFD700", size=11, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER) if not is_admin else ft.Container(height=0),
                        group_sync_row(active_group, is_admin),
                        ft.Text(f"Round {current_round} of {len(order)}", color="white", weight=ft.FontWeight.BOLD, size=14, text_align=ft.TextAlign.CENTER),
                        ft.Text(round_month_display, color="#FFD700", size=12, text_align=ft.TextAlign.CENTER) if round_month_display else ft.Container(height=0),
                        ft.Text(countdown_text, color=countdown_color, size=14, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER) if countdown_text else ft.Container(height=0),
                        ft.Stack(
                            [
                                ft.Container(
                                    width=220, height=10,
                                    border_radius=5,
                                    gradient=ft.LinearGradient(
                                        begin=ft.Alignment(-1, 0), end=ft.Alignment(1, 0),
                                        colors=["#2E8B57", "#FFD700", "#C62828"],
                                    ),
                                ),
                                ft.Container(
                                    left=max(0, min(212, 220 * (1 - countdown_fill_ratio) - 4)),
                                    top=-3,
                                    width=8, height=16,
                                    bgcolor="white",
                                    border_radius=4,
                                    animate_position=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
                                ),
                            ],
                            width=220, height=10,
                        ) if countdown_text else ft.Container(height=0),
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text(f"👑 {collector}'s Turn to Collect", color="#FFD700", weight=ft.FontWeight.BOLD, size=17, text_align=ft.TextAlign.CENTER),
                                    ft.Text(f"₦{total_pot:,.2f}", color="#2E8B57", weight=ft.FontWeight.BOLD, size=22, text_align=ft.TextAlign.CENTER),
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
                            ),
                            padding=15, border_radius=12,
                            bgcolor=ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
                            alignment=ft.Alignment(0, 0),
                        ),
                        ft.Divider(height=1, color="#4B0082"),
                        ft.Text(f"⏳ Unpaid ({len(order) - 1 - paid_count})", color="#C62828", weight=ft.FontWeight.BOLD, size=13),
                        ft.Container(
                            content=ft.Column(unpaid_rows, spacing=2) if unpaid_rows else ft.Text("Everyone has paid! 🎉", color="#2E8B57", size=12, italic=True),
                            padding=10, border_radius=10,
                            bgcolor=ft.Colors.with_opacity(0.25, ft.Colors.RED),
                        ),
                        ft.Text(f"✅ Paid ({paid_count})", color="#2E8B57", weight=ft.FontWeight.BOLD, size=13),
                        ft.Container(
                            content=ft.Column(paid_rows, spacing=2) if paid_rows else ft.Text("No one has paid yet.", color="#888888", size=12, italic=True),
                            padding=10, border_radius=10,
                            bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.GREEN),
                        ),
                        ft.Text(f"👑 Already Collected ({len(active_group.get('history', []))})", color="#FFD700", weight=ft.FontWeight.BOLD, size=13),
                        ft.Container(
                            content=ft.Column(
                                [ft.Text(f"{h['collector']} — Round {h['round']} (₦{h['amount']:,.2f})", color="#FFD700", size=13, weight=ft.FontWeight.BOLD) for h in active_group.get("history", [])],
                                spacing=6,
                            ) if active_group.get("history") else ft.Text("No one has collected yet.", color="#888888", size=12, italic=True),
                            padding=10, border_radius=10,
                            bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.AMBER),
                        ),
                        ft.ElevatedButton(
                            content=ft.Row([ft.Icon(ft.Icons.IOS_SHARE_ROUNDED, color="white", size=16), ft.Text("Share as Picture", color="white", weight=ft.FontWeight.BOLD)], spacing=6, tight=True),
                            on_click=lambda e: share_ajo_round(active_group),
                            style=ft.ButtonStyle(bgcolor="#8E24AA"),
                        ),
                        ft.ElevatedButton(
                            content=ft.Row([ft.Icon(ft.Icons.EDIT_NOTE_ROUNDED, color="white", size=16), ft.Text("Edit Order", color="white", weight=ft.FontWeight.BOLD)], spacing=6, tight=True),
                            on_click=edit_order_dialog,
                            style=ft.ButtonStyle(bgcolor="#1E88E5"),
                            disabled=not is_admin,
                        ) if is_admin else ft.Container(height=0),
                        ft.ElevatedButton("Advance to Next Round", on_click=advance_round, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white"), disabled=not is_admin),
                    ],
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=15, border_radius=15,
                bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            )
            page.update()

        async def import_ajo_group(e):
            result = await picker_pick_files(
                dialog_title="Import Ajo Group",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["png", "json"],
                allow_multiple=False,
                with_data=True,
            )
            files = getattr(result, "files", result)
            if not files:
                page.show_dialog(ft.SnackBar(ft.Text("Import cancelled.", color="white"), bgcolor=PURPLE_TEXT, duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()
                return
            picked = files[0]
            if not getattr(picked, "bytes", None):
                page.show_dialog(ft.SnackBar(ft.Text("Could not read that file.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()
                return
            try:
                try:
                    imported_group = json.loads(read_branded_file(bytes(picked.bytes)).decode("utf-8"))
                except ValueError as ve:
                    if str(ve) == "photo":
                        page.show_dialog(ft.SnackBar(ft.Text(PHOTO_STRIPPED_MSG, color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=7), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return
                    raise
                if not is_valid_ajo_group(imported_group):
                    msg = ("That's a Money Tracker backup, not an Ajo group. Use Money Tracker → Options → Restore Data for backups."
                           if isinstance(imported_group, dict) and "profiles" in imported_group
                           else "That doesn't look like a valid group file.")
                    page.show_dialog(ft.SnackBar(ft.Text(msg, color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=5), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                    return
                for _k, _v in (("members", []), ("contribution_amount", 0), ("order", []), ("current_round", 1),
                               ("payments", {}), ("history", []), ("rules", "")):
                    imported_group.setdefault(_k, _v)
                imported_group["is_admin"] = False  # an imported copy is always a member's copy
                fresh_groups = await load_ajo_groups()
                existing_idx = next((i for i, g in enumerate(fresh_groups) if g["id"] == imported_group.get("id")), None)
                if existing_idx is not None and fresh_groups[existing_idx].get("is_admin", True):
                    page.show_dialog(ft.SnackBar(ft.Text("You are the Admin of this group — import blocked to protect your copy.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=4), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                    return
                new_t = str(imported_group.get("updated_at") or "")
                if existing_idx is not None:
                    have_t = str(fresh_groups[existing_idx].get("updated_at") or "")
                    if have_t and new_t and new_t < have_t:
                        page.show_dialog(ft.SnackBar(ft.Text(
                            f"This file is older than the copy you already have (yours: {fmt_stamp(have_t)}, file: {fmt_stamp(new_t)}). "
                            "Nothing was changed. Ask the admin for the newest file.", color="white"),
                            bgcolor="#C62828", duration=ft.Duration(seconds=7), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                        return
                    fresh_groups[existing_idx] = imported_group
                    if have_t and new_t == have_t:
                        msg = f"Already up to date: {imported_group.get('name', 'Ajo Group')} ({fmt_stamp(new_t)})."
                    else:
                        msg = f"Updated: {imported_group.get('name', 'Ajo Group')}" + (f" (admin's changes from {fmt_stamp(new_t)})" if new_t else "")
                else:
                    fresh_groups.append(imported_group)
                    msg = f"Imported: {imported_group.get('name', 'Ajo Group')}"
                await save_ajo_groups(fresh_groups)
                await save_active_ajo_id(imported_group["id"])
                page.show_dialog(ft.SnackBar(ft.Text(msg, color="white"), bgcolor="#2E8B57", duration=ft.Duration(seconds=5), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                await refresh_ajo_ui()
                page.update()
            except Exception:
                page.show_dialog(ft.SnackBar(ft.Text("That doesn't look like a valid group file.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                page.update()

        async def create_ajo_group_dialog(e=None):
            name_field = NFTextField(label="Group Name", bgcolor="#FFFFFF", color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), capitalization=ft.TextCapitalization.WORDS, max_length=30)
            name_field.on_change = with_length_warning(name_field, 30)
            rules_field = NFTextField(
                label="Rules & Regulations (optional)", multiline=True, min_lines=3, max_lines=6,
                bgcolor="#FFFFFF", color="black", text_style=ft.TextStyle(color="black"),
                capitalization=ft.TextCapitalization.SENTENCES, max_length=500,
            )
            rules_field.on_change = with_length_warning(rules_field, 500)
            error_text = ft.Text("", color="red", size=12)

            async def create_it(e):
                gname = (name_field.value or "").strip()
                if not gname:
                    error_text.value = "Enter a group name."
                    page.update()
                    return
                groups = await load_ajo_groups()
                new_group = {
                    "id": new_ajo_id(), "name": gname, "members": [], "contribution_amount": 0,
                    "order": [], "current_round": 1, "payments": {}, "history": [],
                    "rules": (rules_field.value or "").strip(),
                    "is_admin": True,
                }
                groups.append(new_group)
                await save_ajo_groups(groups)
                await save_active_ajo_id(new_group["id"])
                page.pop_dialog()
                await refresh_ajo_ui()

            dlg = ft.AlertDialog(scrollable=True, 
                modal=True, bgcolor="#FFFFFF",
                title=ft.Text("New Ajo Group", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(content=ft.Column([name_field, rules_field, error_text], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO), width=280, height=280),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.TextButton("Create", on_click=create_it, style=ft.ButtonStyle(color="#2E8B57")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        async def open_ajo_switcher(e):
            groups = await load_ajo_groups()
            active_id = await load_active_ajo_id()
            current_group_is_admin = next((g.get("is_admin", True) for g in groups if g["id"] == active_id), True)

            def make_select_group(gid):
                async def _select(e):
                    nonlocal active_id, current_group_is_admin
                    await save_active_ajo_id(gid)
                    active_id = gid
                    current_group_is_admin = next((g.get("is_admin", True) for g in groups if g["id"] == active_id), True)
                    build_rows()
                    switcher_body.controls = build_switcher_controls()
                    page.update()
                    await refresh_ajo_ui()
                return _select

            def make_delete_group(gid):
                async def _really_delete(e):
                    page.pop_dialog()
                    groups2 = await load_ajo_groups()
                    groups2 = [g for g in groups2 if g["id"] != gid]
                    await save_ajo_groups(groups2)
                    if active_id == gid:
                        await save_active_ajo_id(groups2[0]["id"] if groups2 else "")
                    await refresh_ajo_ui()

                async def _delete(e):
                    gname = next((g.get("name", "this group") for g in groups if g["id"] == gid), "this group")
                    page.pop_dialog()
                    page.show_dialog(ft.AlertDialog(
                        modal=True, bgcolor="#FFFFFF",
                        title=ft.Text("Delete group?", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        content=ft.Text(f"“{gname}” and all its members, payments and history will be removed from this phone. "
                                        "This can't be undone. (Tip: use Send Group File to Members first to keep a copy.)", color=DARK_TEXT, size=13),
                        actions=[
                            ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                            ft.ElevatedButton("Delete", on_click=_really_delete, style=ft.ButtonStyle(bgcolor="#C62828", color="white")),
                        ],
                        actions_alignment=ft.MainAxisAlignment.END,
                    ))
                return _delete

            def make_rename_group(target_group):
                def _open_rename(e):
                    rename_field = NFTextField(value=target_group["name"], bgcolor="#FFFFFF", color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), capitalization=ft.TextCapitalization.WORDS, autofocus=True, max_length=30)
                    rename_field.on_change = with_length_warning(rename_field, 30)

                    async def save_rename(e):
                        new_name = (rename_field.value or "").strip()
                        if not new_name:
                            return
                        target_group["name"] = new_name
                        await save_ajo_groups(groups)
                        page.pop_dialog()
                        build_rows()
                        switcher_body.controls = build_switcher_controls()
                        page.update()
                        await refresh_ajo_ui()

                    rename_dlg = ft.AlertDialog(scrollable=True, 
                        modal=True, bgcolor="#FFFFFF",
                        title=ft.Text("Rename Group", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        content=ft.Container(content=rename_field, width=260),
                        actions=[
                            ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                            ft.TextButton("Save", on_click=save_rename, style=ft.ButtonStyle(color="#2E8B57")),
                        ],
                        actions_alignment=ft.MainAxisAlignment.END,
                    )
                    page.show_dialog(rename_dlg)
                return _open_rename

            rows = []

            def build_rows():
                rows.clear()
                for g in groups:
                    is_active = g["id"] == active_id
                    cycle_count = len(g.get("past_cycles", []))
                    rows.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.TextButton(
                                        content=ft.Container(
                                            content=ft.Text(g["name"], color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                            width=75,
                                        ),
                                        on_click=make_select_group(g["id"]),
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text(f"{cycle_count} cyc" if cycle_count != 1 else "1 cyc", color="#888888", size=11),
                                            ft.IconButton(icon=ft.Icons.EDIT_ROUNDED, icon_color="#1E88E5", icon_size=18, on_click=make_rename_group(g)),
                                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color="#C62828", icon_size=18, on_click=make_delete_group(g["id"])),
                                        ],
                                        spacing=2,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            width=260,
                            bgcolor="#FFD700" if is_active else None,
                            border_radius=8,
                        )
                    )

            build_rows()

            async def new_group_from_switcher(e):
                page.pop_dialog()
                await create_ajo_group_dialog()

            async def view_past_cycles_dialog(e):
                page.pop_dialog()
                fresh_groups_for_view = await load_ajo_groups()
                current_active_group = next((g for g in fresh_groups_for_view if g["id"] == active_id), None)
                if not current_active_group:
                    page.show_dialog(ft.SnackBar(ft.Text("This group no longer exists.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                    return
                past_cycles = current_active_group.get("past_cycles", [])

                def make_launch(cycle_data):
                    async def _launch(e):
                        page.pop_dialog()
                        fresh_groups_for_launch = await load_ajo_groups()
                        target = next((g for g in fresh_groups_for_launch if g["id"] == current_active_group["id"]), None)
                        if not target:
                            page.show_dialog(ft.SnackBar(ft.Text("This group no longer exists.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                            page.update()
                            return
                        target["members"] = list(cycle_data.get("order", []))
                        target["contribution_amount"] = cycle_data.get("contribution_amount", 0)
                        await save_ajo_groups(fresh_groups_for_launch)
                        await refresh_ajo_ui()
                    return _launch

                def make_delete_cycle(idx):
                    async def _delete_cycle(e):
                        fresh_groups_for_delete = await load_ajo_groups()
                        target = next((g for g in fresh_groups_for_delete if g["id"] == current_active_group["id"]), None)
                        if not target:
                            page.pop_dialog()
                            page.show_dialog(ft.SnackBar(ft.Text("This group no longer exists.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                            page.update()
                            return
                        target_cycles = target.get("past_cycles", [])
                        if idx < len(target_cycles):
                            target_cycles.pop(idx)
                        await save_ajo_groups(fresh_groups_for_delete)
                        page.pop_dialog()
                        await view_past_cycles_dialog(None)
                    return _delete_cycle

                cycle_sections = []
                if not past_cycles:
                    cycle_sections.append(ft.Text("No saved cycles yet.", color=DARK_TEXT, size=12, italic=True))
                else:
                    for i, cycle in enumerate(past_cycles):
                        cycle_history = cycle.get("history", []) if isinstance(cycle, dict) else cycle
                        cycle_sections.append(
                            ft.Row(
                                [
                                    ft.Text(f"Cycle {i + 1}", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color="#C62828", icon_size=16, on_click=make_delete_cycle(i)),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            )
                        )
                        if cycle_history:
                            for h in cycle_history:
                                cycle_sections.append(ft.Text(f"Round {h.get('round')}: {h.get('collector')} — ₦{h.get('amount', 0):,.2f} ({h.get('date', '')})", color=DARK_TEXT, size=12))
                        else:
                            cycle_sections.append(ft.Text("No rounds recorded.", color="#888888", size=12, italic=True))
                        if isinstance(cycle, dict) and cycle.get("order"):
                            cycle_sections.append(
                                ft.TextButton(
                                    content=ft.Row([ft.Icon(ft.Icons.ROCKET_LAUNCH_ROUNDED, color="#2E8B57", size=14), ft.Text("Launch This Arrangement", color="#2E8B57", weight=ft.FontWeight.BOLD, size=12)], spacing=6),
                                    on_click=make_launch(cycle),
                                )
                            )
                        cycle_sections.append(ft.Divider(height=1, color="#DDDDDD"))

                dlg = ft.AlertDialog(scrollable=True, 
                    modal=True, bgcolor="#FFFFFF",
                    title=ft.Text("Past Cycles", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Container(
                        content=ft.Column(cycle_sections, spacing=6, scroll=ft.ScrollMode.AUTO, tight=True),
                        width=280, height=400,
                    ),
                    actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                page.show_dialog(dlg)

            async def view_rules_dialog(e):
                page.pop_dialog()
                current_active_group = next((g for g in groups if g["id"] == active_id), None)
                if not current_active_group:
                    return
                group_is_admin = current_active_group.get("is_admin", True)
                current_rules = current_active_group.get("rules", "")

                if group_is_admin:
                    rules_edit_field = NFTextField(
                        value=current_rules, multiline=True, min_lines=4, max_lines=8,
                        bgcolor="#FFFFFF", color="black", text_style=ft.TextStyle(color="black"),
                        capitalization=ft.TextCapitalization.SENTENCES, max_length=500,
                    )
                    rules_edit_field.on_change = with_length_warning(rules_edit_field, 500)

                    async def save_rules(e):
                        current_active_group["rules"] = (rules_edit_field.value or "").strip()
                        await save_ajo_groups(groups)
                        page.pop_dialog()

                    rules_dlg = ft.AlertDialog(scrollable=True, 
                        modal=True, bgcolor="#FFFFFF",
                        title=ft.Text("Rules & Regulations", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        content=ft.Container(content=rules_edit_field, width=280),
                        actions=[
                            ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                            ft.TextButton("Save", on_click=save_rules, style=ft.ButtonStyle(color="#2E8B57")),
                        ],
                        actions_alignment=ft.MainAxisAlignment.END,
                    )
                else:
                    rules_dlg = ft.AlertDialog(scrollable=True, 
                        modal=True, bgcolor="#FFFFFF",
                        title=ft.Text("Rules & Regulations", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                        content=ft.Container(
                            content=ft.Text(current_rules or "No rules have been set by the Admin yet.", color=DARK_TEXT, size=13),
                            width=280,
                        ),
                        actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                        actions_alignment=ft.MainAxisAlignment.END,
                    )
                page.show_dialog(rules_dlg)

            async def export_ajo_group(e):
                page.pop_dialog()
                await send_group_file(active_id)

            async def import_from_switcher(e):
                page.pop_dialog()
                await import_ajo_group(e)

            async def export_ajo_pdf(e):
                page.pop_dialog()
                current_active_group = next((g for g in groups if g["id"] == active_id), None)
                if not current_active_group:
                    return
                if not current_active_group.get("is_admin", True):
                    page.show_dialog(ft.SnackBar(ft.Text("Only the Admin can export a progress report.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                    page.update()
                    return

                note_field = NFTextField(
                    label="Note or instructions (optional)", multiline=True, min_lines=3, max_lines=6,
                    bgcolor="#FFFFFF", color="black", text_style=ft.TextStyle(color="black"),
                    capitalization=ft.TextCapitalization.SENTENCES, max_length=500,
                )
                note_field.on_change = with_length_warning(note_field, 500)

                async def generate_with_note(e):
                    page.pop_dialog()
                    try:
                        pdf_bytes = build_ajo_pdf_bytes(current_active_group, note=(note_field.value or "").strip())
                        file_path = await picker_save_file(
                            dialog_title="Save Ajo Progress Report",
                            file_name=f"Ajo_{safe_filename(current_active_group['name'])}_Progress.pdf",
                            file_type=ft.FilePickerFileType.CUSTOM,
                            allowed_extensions=["pdf"],
                            src_bytes=pdf_bytes,
                        )
                        page.show_dialog(ft.SnackBar(ft.Text("Progress report saved! Share it via WhatsApp." if file_path else "Export cancelled.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()
                    except Exception as ex:
                        page.show_dialog(ft.SnackBar(ft.Text(f"Export failed: {ex}", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=5), behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
                        page.update()

                note_dlg = ft.AlertDialog(scrollable=True, 
                    modal=True, bgcolor="#FFFFFF",
                    title=ft.Text("Add a Note? (Optional)", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Container(
                        content=ft.Column(
                            [ft.Text("Anything you type here will be included in the PDF. Leave blank to skip.", color=DARK_TEXT, size=12), note_field],
                            spacing=10, tight=True,
                        ),
                        width=280,
                    ),
                    actions=[
                        ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                        ft.TextButton("Generate PDF", on_click=generate_with_note, style=ft.ButtonStyle(color="#2E8B57")),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                page.show_dialog(note_dlg)

            def build_switcher_controls():
                return rows + [
                    ft.Divider(height=1, color="#DDDDDD"),
                    ft.TextButton("+ New Group", on_click=new_group_from_switcher, style=ft.ButtonStyle(color="#2E8B57")),
                ] + ([
                    ft.Divider(height=1, color="#DDDDDD"),
                    ft.TextButton(
                        content=ft.Row([ft.Icon(ft.Icons.GAVEL_ROUNDED, color=PURPLE_TEXT, size=16), ft.Text("Rules & Regulations", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)], spacing=8),
                        on_click=view_rules_dialog,
                    ),
                    ft.TextButton(
                        content=ft.Row([ft.Icon(ft.Icons.HISTORY_ROUNDED, color=PURPLE_TEXT, size=16), ft.Text("Past Cycles", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)], spacing=8),
                        on_click=view_past_cycles_dialog,
                    ),
                    ft.TextButton(
                        content=ft.Row([ft.Icon(ft.Icons.SHARE_ROUNDED, color="#8E24AA", size=16), ft.Text("Send Group File to Members", color="#8E24AA", weight=ft.FontWeight.BOLD)], spacing=8),
                        on_click=export_ajo_group,
                    ),
                ] if groups else []) + ([
                    ft.TextButton(
                        content=ft.Row([ft.Icon(ft.Icons.PICTURE_AS_PDF_ROUNDED, color="#C62828", size=16), ft.Text("Export Progress (PDF)", color="#C62828", weight=ft.FontWeight.BOLD)], spacing=8),
                        on_click=export_ajo_pdf,
                    ),
                ] if (groups and current_group_is_admin) else []) + [
                    ft.TextButton(
                        content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, color="#1E88E5", size=16), ft.Text("Import Group from File", color="#1E88E5", weight=ft.FontWeight.BOLD)], spacing=8),
                        on_click=import_from_switcher,
                    ),
                    ft.Container(
                        content=ft.Text(
                            "📂 Downloaded a file from WhatsApp? Find it at:\nPhone Storage → Android → Media → com.whatsapp → WhatsApp → Media → Document",
                            color="#C62828", size=10, text_align=ft.TextAlign.CENTER,
                        ),
                        padding=ft.Padding(left=8, right=8, top=0, bottom=4),
                    ),
                ]

            switcher_body = ft.Column(
                build_switcher_controls(),
                spacing=4, scroll=ft.ScrollMode.AUTO, tight=True,
            )

            dlg = ft.AlertDialog(scrollable=True, 
                modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Your Ajo Groups", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=switcher_body,
                    width=270, height=580,
                ),
                actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        ajo_switcher_btn.on_click = open_ajo_switcher

        await refresh_ajo_ui()

        ajo_tab_content = ft.Column(
            controls=[
                ft.Row([ajo_switcher_btn], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(height=10),
                ajo_content_area,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # ==================================================================
        # HOME DASHBOARD, SAVINGS GOALS, REMINDERS, REPEATING ENTRIES,
        # SHARE AS PICTURE AND APP LOCK
        # ==================================================================
        tab_labels = ["Home", "Housing Upfront", "Salary Management", "Money Tracker", "Ajo Groups"]
        tab_icons = [ft.Icons.DASHBOARD_ROUNDED, ft.Icons.HOME_ROUNDED, ft.Icons.WORK_ROUNDED, ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, ft.Icons.GROUPS_ROUNDED]
        tab_icon_colors = ["#FFD54F", "#FF8C00", "#E53935", "#1E88E5", "#8E24AA"]
        CARD_BG = ft.Colors.with_opacity(0.55, ft.Colors.BLACK)
        SOFT_TEXT = "#DDDDDD"

        def snack(text, color=PURPLE_TEXT, seconds=3):
            page.show_dialog(ft.SnackBar(ft.Text(text, color="white"), bgcolor=color, duration=ft.Duration(seconds=seconds),
                                         behavior=ft.SnackBarBehavior.FLOATING, margin=ft.Margin.only(bottom=300, left=10, right=10)))
            page.update()

        async def go_to_page(label):
            if label in tab_labels:
                await select_tab(tab_labels.index(label))(None)

        def dlg_field(**kwargs):
            """A text box styled for the white pop-ups."""
            return NFTextField(bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                               text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), **kwargs)

        # -------------------- SAVINGS GOALS --------------------
        MAX_GOALS = 10

        async def load_goals():
            try:
                raw = await prefs.get("savings_goals")
                goals = json.loads(raw) if raw else []
                return [g for g in goals if isinstance(g, dict) and g.get("id")] if isinstance(goals, list) else []
            except Exception:
                return []

        async def save_goals(goals):
            await prefs.set("savings_goals", json.dumps(goals))

        def goal_numbers(goal):
            try:
                target = float(goal.get("target", 0) or 0)
                saved = float(goal.get("saved", 0) or 0)
            except (TypeError, ValueError):
                target, saved = 0.0, 0.0
            return saved, target, ((saved / target * 100.0) if target > 0 else 0.0)

        def goal_hint(goal, today_d):
            saved, target, _pct = goal_numbers(goal)
            if target > 0 and saved >= target:
                return "Goal reached!", MONEY_GREEN
            left = max(target - saved, 0.0)
            try:
                deadline = datetime.date.fromisoformat(goal.get("deadline") or "")
            except Exception:
                return f"{fmt_money(left, 0)} to go", SOFT_TEXT
            days = (deadline - today_d).days
            when = deadline.strftime("%d %b %Y").lstrip("0")
            if days < 0:
                return f"{fmt_money(left, 0)} to go · the target date ({when}) has passed", MONEY_RED
            months_left = max(1, math.ceil(days / 30.4))
            return f"{fmt_money(left, 0)} to go by {when} · about {fmt_money(left / months_left, 0)} a month", SOFT_TEXT

        def open_goal_dialog(goal=None):
            editing = goal is not None
            current = goal or {}
            name_field = dlg_field(value=current.get("name", ""), hint_text="e.g. Rent", max_length=40,
                                   capitalization=ft.TextCapitalization.WORDS)
            name_field.on_change = with_length_warning(name_field, 40)
            try:
                target_text = f"{float(current.get('target') or 0):.0f}" if current.get("target") else ""
            except (TypeError, ValueError):
                target_text = ""
            target_field = dlg_field(value=target_text, hint_text="e.g. 500000", keyboard_type=ft.KeyboardType.NUMBER, max_length=15)
            target_field.on_change = with_length_warning(target_field, 15)
            try:
                start_deadline = datetime.date.fromisoformat(current.get("deadline") or "")
            except Exception:
                start_deadline = None
            deadline_state = {"value": start_deadline}
            no_date_label = "Pick a target date (optional)"
            deadline_text = ft.Text(start_deadline.strftime("%d %b %Y") if start_deadline else no_date_label,
                                    color="#4B0082", size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
            error_text = ft.Text("", color="red", size=12)

            def on_deadline_picked(e):
                picked = e.control.value
                if picked:
                    deadline_state["value"] = picked_to_date(picked)
                    deadline_text.value = deadline_state["value"].strftime("%d %b %Y")
                    page.update()

            deadline_picker = ft.DatePicker(
                first_date=datetime.datetime.now(),
                last_date=datetime.datetime.now() + datetime.timedelta(days=3650),
                on_change=on_deadline_picked,
            )

            def clear_deadline(e):
                deadline_state["value"] = None
                deadline_text.value = no_date_label
                page.update()

            async def save_goal(e):
                name = (name_field.value or "").strip()
                try:
                    target = to_number(target_field.value, required=True)
                except (ValueError, TypeError):
                    target = 0.0
                if not name:
                    error_text.value = "Give the goal a name."
                elif target <= 0:
                    error_text.value = "Enter the amount you want to save."
                else:
                    error_text.value = ""
                goals = await load_goals()
                if not error_text.value and not editing and len(goals) >= MAX_GOALS:
                    error_text.value = f"You can keep up to {MAX_GOALS} goals. Delete one first."
                if error_text.value:
                    page.update()
                    return
                deadline = deadline_state["value"].isoformat() if deadline_state["value"] else ""
                if editing:
                    for g in goals:
                        if g.get("id") == current.get("id"):
                            g.update({"name": name, "target": target, "deadline": deadline})
                else:
                    goals.append({"id": new_ajo_id(), "name": name, "target": target, "saved": 0.0,
                                  "deadline": deadline, "created": datetime.date.today().isoformat()})
                await save_goals(goals)
                page.pop_dialog()
                await refresh_home_ui()
                page.update()

            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Edit Goal" if editing else "New Savings Goal", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("What are you saving for, and how much do you need?", color=DARK_TEXT, size=12),
                            field_with_caption("Goal name", name_field, on_white=True),
                            field_with_caption("Target amount (₦)", target_field, on_white=True),
                            ft.Row(
                                [
                                    ft.ElevatedButton(content=ft.Container(content=deadline_text, width=170),
                                                      on_click=lambda e: page.show_dialog(deadline_picker),
                                                      style=ft.ButtonStyle(bgcolor="#FFD700")),
                                    ft.TextButton("Clear", on_click=clear_deadline, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                                ],
                                spacing=4, wrap=True,
                            ),
                            error_text,
                        ],
                        tight=True, spacing=14,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.ElevatedButton("Save Goal", on_click=save_goal, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        def open_goal_money_dialog(goal):
            saved, target, pct = goal_numbers(goal)
            amount_field = dlg_field(hint_text="e.g. 20000", keyboard_type=ft.KeyboardType.NUMBER, max_length=15)
            amount_field.on_change = with_length_warning(amount_field, 15)
            error_text = ft.Text("", color="red", size=12)

            async def change(sign):
                try:
                    amount = to_number(amount_field.value, required=True)
                except (ValueError, TypeError):
                    amount = 0.0
                if amount <= 0:
                    error_text.value = "Enter an amount."
                    page.update()
                    return
                goals = await load_goals()
                reached = False
                for g in goals:
                    if g.get("id") == goal.get("id"):
                        now_saved, now_target, _ = goal_numbers(g)
                        if sign < 0 and amount > now_saved:
                            error_text.value = f"There is only {fmt_money(now_saved, 0)} in this goal."
                            page.update()
                            return
                        g["saved"] = round(now_saved + sign * amount, 2)
                        reached = sign > 0 and now_target > 0 and now_saved < now_target <= g["saved"]
                await save_goals(goals)
                page.pop_dialog()
                await refresh_home_ui()
                page.update()
                if reached:
                    snack(f"You reached your goal: {goal.get('name', '')}!", color="#2E8B57", seconds=4)

            async def add_money(e):
                await change(1)

            async def take_out(e):
                await change(-1)

            def edit_goal(e):
                page.pop_dialog()
                open_goal_dialog(goal)

            def ask_delete(e):
                page.pop_dialog()

                async def do_delete(ev):
                    await save_goals([g for g in await load_goals() if g.get("id") != goal.get("id")])
                    page.pop_dialog()
                    await refresh_home_ui()
                    page.update()

                page.show_dialog(ft.AlertDialog(
                    scrollable=True, modal=True, bgcolor="#FFFFFF",
                    title=ft.Text("Delete this goal?", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Text(f"“{goal.get('name', '')}” and its progress will be removed. This can't be undone.",
                                    color=DARK_TEXT, size=13),
                    actions=[
                        ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                        ft.ElevatedButton("Delete", on_click=do_delete, style=ft.ButtonStyle(bgcolor="#C62828", color="white")),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                ))

            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text(goal.get("name", "Goal"), color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(f"{fmt_money(saved, 0)} saved of {fmt_money(target, 0)} ({pct:.0f}%)",
                                    color=DARK_TEXT, size=13, weight=ft.FontWeight.BOLD),
                            field_with_caption("Amount (₦)", amount_field, on_white=True),
                            error_text,
                            ft.Text("This only tracks your goal. It does not add a transaction to Money Tracker.",
                                    color="#666666", size=11),
                            ft.Row(
                                [
                                    ft.TextButton("Edit goal", on_click=edit_goal, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                                    ft.TextButton("Delete goal", on_click=ask_delete, style=ft.ButtonStyle(color="#C62828")),
                                ],
                                spacing=4, wrap=True,
                            ),
                        ],
                        tight=True, spacing=10,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.TextButton("Take out", on_click=take_out, style=ft.ButtonStyle(color="#C62828")),
                    ft.ElevatedButton("Add money", on_click=add_money, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        # -------------------- REMINDERS --------------------
        # Shown on the Home page, and once a day as a pop-up for the urgent ones. They appear when
        # the app is opened; the app does not send notifications while it is closed.
        async def compute_reminders(transactions=None):
            items = []
            today_d = datetime.date.today()
            try:
                for g in await load_ajo_groups():
                    st = ajo_round_status(g, today_d)
                    if not st or st["days_left"] is None or st["days_left"] > 7 or not st["unpaid"]:
                        continue
                    n, d = len(st["unpaid"]), st["days_left"]
                    items.append({
                        "urgent": d <= 3, "icon": ft.Icons.GROUPS_ROUNDED, "color": MONEY_RED if d <= 0 else "#FFB74D",
                        "text": f"Ajo “{st['name']}”: {due_phrase(d).lower()}. {n} member{'s' if n != 1 else ''} yet to pay.",
                        "page": "Ajo Groups",
                    })
            except Exception:
                pass
            try:
                budgets = await load_budgets()
                if budgets:
                    if transactions is None:
                        transactions = await load_transactions()
                    by_cat = month_stats(transactions, today_d.year, today_d.month)["by_cat"]
                    for cat, limit in budgets.items():
                        try:
                            limit = float(limit)
                        except (TypeError, ValueError):
                            continue
                        if limit <= 0:
                            continue
                        used = by_cat.get(cat, 0.0)
                        pct = used / limit * 100.0
                        if pct >= 100:
                            items.append({"urgent": True, "icon": ft.Icons.WARNING_ROUNDED, "color": MONEY_RED,
                                          "text": f"{cat} budget is used up ({fmt_money(used, 0)} of {fmt_money(limit, 0)}).",
                                          "page": "Money Tracker"})
                        elif pct >= 80:
                            items.append({"urgent": False, "icon": ft.Icons.WARNING_ROUNDED, "color": "#FFB74D",
                                          "text": f"{cat} budget is {pct:.0f}% used.", "page": "Money Tracker"})
            except Exception:
                pass
            try:
                for g in await load_goals():
                    saved, target, _pct = goal_numbers(g)
                    if target <= 0 or saved >= target or not g.get("deadline"):
                        continue
                    days = (datetime.date.fromisoformat(g["deadline"]) - today_d).days
                    if 0 <= days <= 14:
                        items.append({"urgent": days <= 3, "icon": ft.Icons.FLAG_ROUNDED, "color": "#FFB74D",
                                      "text": f"Goal “{g.get('name', '')}”: {due_phrase(days).lower()}, {fmt_money(target - saved, 0)} to go.",
                                      "page": "Home"})
            except Exception:
                pass
            try:
                now_dt = datetime.datetime.now()
                for t in reminder_todos(await load_todos()):
                    due = todo_due(t)
                    if due is None:
                        continue
                    days = (due.date() - today_d).days
                    if days > 1:
                        continue
                    when = due.strftime("%I:%M %p").lstrip("0")
                    if days < 0:
                        phrase = f"was due {fmt_due(due)}"
                    elif days == 0:
                        phrase = f"is due today at {when}" if due > now_dt else f"was due today at {when}"
                    else:
                        phrase = f"is due tomorrow at {when}"
                    items.append({"urgent": days <= 0, "icon": ft.Icons.ALARM_ROUNDED,
                                  "color": MONEY_RED if due <= now_dt else "#4FC3F7",
                                  "text": f"To-do “{t.get('text', '')}” {phrase}.", "page": "Home"})
            except Exception:
                pass
            try:
                days_to_end = calendar.monthrange(today_d.year, today_d.month)[1] - today_d.day
                if days_to_end <= 3:
                    this_key = f"{today_d.year:04d}-{today_d.month:02d}"
                    open_items = [t for t in await load_todos() if t.get("month") == this_key and not t.get("done")]
                    if open_items:
                        n = len(open_items)
                        items.append({"urgent": False, "icon": ft.Icons.CHECKLIST_ROUNDED, "color": "#4FC3F7",
                                      "text": f"{n} to-do item{'s' if n != 1 else ''} still open, and the month ends "
                                              f"{'today' if days_to_end == 0 else f'in {days_to_end} day' + ('s' if days_to_end != 1 else '')}.",
                                      "page": "Home"})
            except Exception:
                pass
            return items

        async def maybe_show_reminders_popup():
            """Once a day, when the app is opened, list anything urgent."""
            try:
                if lock_state["locked"] or build_gen["n"] != my_gen:
                    return
                today_s = datetime.date.today().isoformat()
                if await prefs.get("reminders_shown_on") == today_s:
                    return
                urgent = [r for r in await compute_reminders() if r["urgent"]]
                if not urgent:
                    return
                await prefs.set("reminders_shown_on", today_s)
                page.show_dialog(ft.AlertDialog(
                    scrollable=True, modal=True, bgcolor="#FFFFFF",
                    title=ft.Text("Reminders", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Container(
                        content=ft.Column(
                            [ft.Row([ft.Icon(r["icon"], color="#C62828", size=18),
                                     ft.Text(r["text"], color=DARK_TEXT, size=13, expand=True)],
                                    spacing=8, vertical_alignment=ft.CrossAxisAlignment.START) for r in urgent[:6]],
                            tight=True, spacing=12,
                        ),
                        width=300,
                    ),
                    actions=[ft.TextButton("OK", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                    actions_alignment=ft.MainAxisAlignment.END,
                ))
                page.update()
            except Exception:
                pass

        # -------------------- MONTH-END TO-DO LIST --------------------
        # A simple checklist of what you plan to do with this month's money (pay rent, send money home,
        # buy foodstuff...). Each item belongs to a month; unfinished ones can be brought into the next.
        TODO_KEY = "month_todos"
        MAX_TODOS = 30

        def month_key(d=None):
            d = d or datetime.date.today()
            return f"{d.year:04d}-{d.month:02d}"

        async def load_todos():
            try:
                raw = await prefs.get(TODO_KEY)
                items = json.loads(raw) if raw else []
                return [t for t in items if isinstance(t, dict) and t.get("id")] if isinstance(items, list) else []
            except Exception:
                return []

        async def save_todos(items):
            # Keep this month and the two before it; older lists are no longer shown anywhere.
            today_d = datetime.date.today()
            y, m = today_d.year, today_d.month
            keep = set()
            for _ in range(3):
                keep.add(f"{y:04d}-{m:02d}")
                y, m = prev_month(y, m)
            await prefs.set(TODO_KEY, json.dumps([t for t in items if t.get("month") in keep]))

        def todo_amount(t):
            try:
                return max(float(t.get("amount", 0) or 0), 0.0)
            except (TypeError, ValueError):
                return 0.0

        def reminder_todos(items):
            """Items that can still remind: not done, not brought over into a newer month, and not an
            older copy of something already on this month's list."""
            this_key = month_key()
            current = {t.get("text", "").strip().lower() for t in items if t.get("month") == this_key}
            return [t for t in items if not t.get("done") and not t.get("carried")
                    and (t.get("month") == this_key or t.get("text", "").strip().lower() not in current)]

        def todo_due(t):
            """The reminder date/time of a to-do item, or None."""
            try:
                return datetime.datetime.fromisoformat(t.get("due") or "")
            except Exception:
                return None

        def fmt_due(dt):
            time_s = dt.strftime("%I:%M %p").lstrip("0")
            return f"{dt.strftime('%d %b').lstrip('0')}, {time_s}"

        def open_todo_dialog(item=None):
            editing = item is not None
            current = item or {}
            text_field = dlg_field(value=current.get("text", ""), hint_text="e.g. Pay rent", max_length=50,
                                   capitalization=ft.TextCapitalization.SENTENCES, autofocus=not editing)
            text_field.on_change = with_length_warning(text_field, 50)
            amount_val = todo_amount(current)
            amount_field = dlg_field(value=f"{amount_val:.0f}" if amount_val else "", hint_text="e.g. 50000 (optional)",
                                     keyboard_type=ft.KeyboardType.NUMBER, max_length=15)
            amount_field.on_change = with_length_warning(amount_field, 15)
            error_text = ft.Text("", color="red", size=12)
            busy = {"v": False}

            # Reminder: an optional date and time. When it comes, the app shows a phone notification.
            start_due = todo_due(current)
            due_state = {"date": start_due.date() if start_due else None,
                         "time": start_due.time() if start_due else datetime.time(9, 0)}
            no_date_label = "Pick a date (optional)"
            date_text = ft.Text("", color="#4B0082", size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
            time_text = ft.Text("", color="#4B0082", size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
            time_button = ft.ElevatedButton(content=ft.Container(content=time_text, width=80),
                                            on_click=lambda e: page.show_dialog(time_picker),
                                            style=ft.ButtonStyle(bgcolor="#FFD700"))
            clear_button = ft.TextButton("Clear", on_click=lambda e: clear_due(), style=ft.ButtonStyle(color=PURPLE_TEXT))

            def show_due():
                d = due_state["date"]
                date_text.value = d.strftime("%a %d %b %Y") if d else no_date_label
                time_text.value = due_state["time"].strftime("%I:%M %p").lstrip("0")
                time_button.visible = d is not None
                clear_button.visible = d is not None

            def clear_due():
                due_state["date"] = None
                show_due()
                page.update()

            def on_date_picked(e):
                picked = e.control.value
                if picked:
                    due_state["date"] = picked_to_date(picked)
                    show_due()
                    request_notify_permission()
                    page.update()

            def on_time_picked(e):
                picked = e.control.value
                if isinstance(picked, datetime.time):
                    due_state["time"] = picked.replace(second=0, microsecond=0)
                    show_due()
                    page.update()

            date_picker = ft.DatePicker(
                value=datetime.datetime.combine(due_state["date"], datetime.time(12, 0))
                if due_state["date"] and due_state["date"] >= datetime.date.today() else None,
                first_date=datetime.datetime.now() - datetime.timedelta(days=1),
                last_date=datetime.datetime.now() + datetime.timedelta(days=400),
                on_change=on_date_picked,
            )
            time_picker = ft.TimePicker(value=due_state["time"], on_change=on_time_picked,
                                        help_text="Remind me at")
            show_due()

            async def save_item(e):
                if busy["v"]:
                    return
                text = (text_field.value or "").strip()
                amount = 0.0
                if (amount_field.value or "").strip():
                    try:
                        amount = to_number(amount_field.value, required=True)
                    except (ValueError, TypeError):
                        amount = -1.0
                if not text:
                    error_text.value = "Write what you want to do."
                elif amount < 0:
                    error_text.value = "Enter the amount as a number, or leave it empty."
                else:
                    error_text.value = ""
                items = await load_todos()
                this_month = month_key()
                if not error_text.value and not editing and \
                        len([t for t in items if t.get("month") == this_month]) >= MAX_TODOS:
                    error_text.value = f"You can keep up to {MAX_TODOS} items a month. Delete one first."
                if error_text.value:
                    page.update()
                    return
                busy["v"] = True
                due = ""
                if due_state["date"]:
                    due = datetime.datetime.combine(due_state["date"], due_state["time"]).isoformat(timespec="minutes")
                if editing:
                    for t in items:
                        if t.get("id") == current.get("id"):
                            if t.get("due", "") != due:
                                t["notified"] = False  # new time: remind again
                            t.update({"text": text, "amount": amount, "due": due})
                else:
                    items.append({"id": new_ajo_id(), "text": text, "amount": amount, "done": False,
                                  "month": this_month, "created": datetime.date.today().isoformat(),
                                  "due": due, "notified": False})
                await save_todos(items)
                page.pop_dialog()
                await refresh_home_ui()
                page.update()
                if due:
                    asyncio.create_task(check_todo_reminders())

            async def delete_item(e):
                if busy["v"]:
                    return
                busy["v"] = True
                items = await load_todos()
                await save_todos([t for t in items if t.get("id") != current.get("id")])
                page.pop_dialog()
                await refresh_home_ui()
                page.update()

            actions = [ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))]
            if editing:
                actions.append(ft.TextButton("Delete", on_click=delete_item, style=ft.ButtonStyle(color="#C62828")))
            actions.append(ft.ElevatedButton("Save" if editing else "Add", on_click=save_item,
                                             style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")))
            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Edit To-Do" if editing else "New To-Do", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("What do you want to do with this month's money?", color=DARK_TEXT, size=12),
                            field_with_caption("To-do", text_field, on_white=True),
                            field_with_caption("Amount (₦), optional", amount_field, on_white=True),
                            ft.Text("Remind me on", color=PURPLE_TEXT, size=12, weight=ft.FontWeight.BOLD),
                            ft.Row(
                                [
                                    ft.ElevatedButton(content=ft.Container(content=date_text, width=150),
                                                      on_click=lambda e: page.show_dialog(date_picker),
                                                      style=ft.ButtonStyle(bgcolor="#FFD700")),
                                    time_button,
                                    clear_button,
                                ],
                                spacing=6, wrap=True, run_spacing=6,
                            ),
                            ft.Text("You'll get a phone notification at that time.", color="#666666", size=11),
                            error_text,
                        ],
                        tight=True, spacing=12,
                    ),
                    width=300,
                ),
                actions=actions,
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        todo_notify_state = {"running": False}

        async def check_todo_reminders():
            """Send a phone notification for each to-do whose reminder time has come."""
            if todo_notify_state["running"]:
                return
            todo_notify_state["running"] = True
            try:
                items = await load_todos()
                now = datetime.datetime.now()
                changed = False
                for t in reminder_todos(items):
                    due = todo_due(t)
                    if t.get("notified") or due is None or due > now:
                        continue
                    amt = todo_amount(t)
                    body = t.get("text", "") + (f" ({fmt_money(amt, 0)})" if amt else "")
                    if (now - due).total_seconds() > 3600:
                        body += f". It was due {fmt_due(due)}."
                    native_notify("To-do reminder", body, notif_id=abs(hash(t.get("id"))))
                    t["notified"] = True
                    changed = True
                if changed:
                    await save_todos(items)
                    if build_gen["n"] == my_gen and tab_labels[current_tab_index["value"]] == "Home":
                        await refresh_home_ui()
                        page.update()
            except Exception:
                pass
            finally:
                todo_notify_state["running"] = False

        async def todo_reminder_loop():
            # Checks every minute while the app is open or still alive in the background.
            while build_gen["n"] == my_gen:
                await check_todo_reminders()
                await asyncio.sleep(60)

        async def toggle_todo(item_id, done):
            items = await load_todos()
            for t in items:
                if t.get("id") == item_id:
                    t["done"] = bool(done)
            await save_todos(items)
            await refresh_home_ui()
            page.update()

        async def carry_over_todos(e):
            today_d = datetime.date.today()
            p_year, p_month = prev_month(today_d.year, today_d.month)
            last_key, this_key = f"{p_year:04d}-{p_month:02d}", month_key(today_d)
            items = await load_todos()
            have = {(t.get("text", "").strip().lower(), todo_amount(t)) for t in items if t.get("month") == this_key}
            room = MAX_TODOS - len([t for t in items if t.get("month") == this_key])
            moved = 0
            for t in [t for t in items if t.get("month") == last_key and not t.get("done")]:
                if room <= 0:
                    break
                sig = (t.get("text", "").strip().lower(), todo_amount(t))
                t["carried"] = True  # the copy in this month takes over its reminders
                if sig in have:
                    continue
                items.append({"id": new_ajo_id(), "text": t.get("text", ""), "amount": todo_amount(t), "done": False,
                              "month": this_key, "created": today_d.isoformat()})
                have.add(sig)
                room -= 1
                moved += 1
            await save_todos(items)
            await prefs.set("todo_carried_" + this_key, "1")
            await refresh_home_ui()
            page.update()
            snack(f"Brought over {moved} item{'s' if moved != 1 else ''}." if moved else "Nothing new to bring over.",
                  color="#2E8B57", seconds=3)

        async def dismiss_carry_over(e):
            await prefs.set("todo_carried_" + month_key(), "1")
            await refresh_home_ui()
            page.update()

        async def toggle_hide_amounts(e):
            hidden_now = (await prefs.get("hide_amounts")) == "1"
            await prefs.set("hide_amounts", "0" if hidden_now else "1")
            await refresh_home_ui()
            page.update()

        # -------------------- HOME PAGE --------------------
        home_body = ft.Column([], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        def home_card(controls, border_color=None, on_click=None):
            side = ft.BorderSide(2, border_color) if border_color else None
            return ft.Container(
                content=ft.Column(controls, spacing=8, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                padding=15, border_radius=15, bgcolor=CARD_BG,
                border=ft.Border(side, side, side, side) if side else None,
                on_click=on_click, ink=on_click is not None,
            )

        def card_title(icon, text, color="#FFD54F", trailing=None):
            items = [ft.Icon(icon, color=color, size=18),
                     ft.Text(text, color="white", weight=ft.FontWeight.BOLD, size=14, expand=True)]
            if trailing is not None:
                items.append(trailing)
            return ft.Row(items, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        def stat_tile(label, value, color):
            return ft.Container(
                content=ft.Column(
                    [ft.Text(label, size=11, color=SOFT_TEXT),
                     ft.Text(value, size=15, weight=ft.FontWeight.BOLD, color=color, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                    spacing=2, tight=True,
                ),
                padding=10, border_radius=10, expand=True,
                bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
            )

        def tool_tile(i):
            return ft.Container(
                content=ft.Column(
                    [ft.Icon(tab_icons[i], size=28, color=tab_icon_colors[i]),
                     ft.Text(tab_labels[i], size=12, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER)],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6, tight=True,
                ),
                padding=14, border_radius=14, bgcolor=CARD_BG, expand=True,
                alignment=ft.Alignment(0, 0), on_click=select_tab(i), ink=True,
            )

        def link_button(text, handler):
            return ft.TextButton(content=ft.Text(text, color="#FFD54F", weight=ft.FontWeight.BOLD, size=12), on_click=handler)

        async def refresh_home_ui():
            today_d = datetime.date.today()
            cards = []
            try:
                transactions = await load_transactions()
            except Exception:
                transactions = []
            this = month_stats(transactions, today_d.year, today_d.month)
            profile_name = profile_names_state.get(str(active_profile_state["value"]), f"Profile {active_profile_state['value']}")

            # The eye button hides every naira amount on Home (handy when someone is looking at your phone).
            hidden = (await prefs.get("hide_amounts")) == "1"
            MASK = "₦ •••••"

            def money(value, decimals=2):
                return MASK if hidden else fmt_money(value, decimals)

            def mask_text(text):
                return re.sub(r"-?₦\s?[\d,]+(?:\.\d+)?", "₦•••", text) if hidden else text

            eye_button = ft.IconButton(
                icon=ft.Icons.VISIBILITY_OFF_ROUNDED if hidden else ft.Icons.VISIBILITY_ROUNDED,
                icon_color="#FFD54F", icon_size=20, on_click=toggle_hide_amounts,
                tooltip="Show amounts" if hidden else "Hide amounts",
                style=ft.ButtonStyle(padding=ft.Padding(left=4, right=4, top=0, bottom=0)),
            )

            async def open_money(e):
                await go_to_page("Money Tracker")

            async def open_ajo_page(e):
                await go_to_page("Ajo Groups")

            # ---- reminders (only when there is something to say)
            reminders = await compute_reminders(transactions)
            if reminders:
                def reminder_row(r):
                    async def open_it(e):
                        if r["page"] != "Home":
                            await go_to_page(r["page"])
                    return ft.Container(
                        content=ft.Row([ft.Icon(r["icon"], color=r["color"], size=18),
                                        ft.Text(mask_text(r["text"]), color="white", size=12, expand=True)],
                                       spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
                        on_click=open_it, ink=True, border_radius=8, padding=ft.Padding(left=2, right=2, top=4, bottom=4),
                    )
                cards.append(home_card(
                    [card_title(ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED, "Reminders", color="#FFB74D")] + [reminder_row(r) for r in reminders[:5]],
                    border_color="#FF8C00",
                ))

            # ---- this month
            month_rows = [
                card_title(ft.Icons.CALENDAR_MONTH_ROUNDED, today_d.strftime("%B %Y"),
                           trailing=ft.Row([ft.Text(profile_name, color="#FFD54F", size=11, weight=ft.FontWeight.BOLD),
                                            eye_button], spacing=0, tight=True,
                                           vertical_alignment=ft.CrossAxisAlignment.CENTER)),
                ft.Text("Balance this month", color=SOFT_TEXT, size=11),
                ft.Text(money(this["net"]), size=28, weight=ft.FontWeight.BOLD,
                        color="white" if hidden else (MONEY_GREEN if this["net"] >= 0 else MONEY_RED),
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([stat_tile("Money in", money(this["income"], 0), MONEY_GREEN),
                        stat_tile("Money out", money(this["spent"], 0), MONEY_RED)], spacing=8),
            ]
            if this["count"] == 0:
                month_rows.append(ft.Text("Nothing recorded this month yet. Add your first income or expense.", color=SOFT_TEXT, size=12))
            else:
                p_year, p_month = prev_month(today_d.year, today_d.month)
                last_by_now = month_stats(transactions, p_year, p_month, up_to_day=today_d.day)["spent"]
                if last_by_now > 0:
                    diff = (this["spent"] - last_by_now) / last_by_now * 100.0
                    last_name = datetime.date(p_year, p_month, 1).strftime("%B")
                    if abs(diff) < 1:
                        month_rows.append(ft.Text(f"Spending is about the same as this point in {last_name}.", color=SOFT_TEXT, size=12))
                    else:
                        month_rows.append(ft.Text(
                            f"You have spent {abs(diff):.0f}% {'less' if diff < 0 else 'more'} than at this point in {last_name}.",
                            color=MONEY_GREEN if diff < 0 else MONEY_RED, size=12, weight=ft.FontWeight.BOLD))
            month_rows.append(ft.ElevatedButton(
                content=ft.Row([ft.Icon(ft.Icons.ADD_ROUNDED, color="white", size=18),
                                ft.Text("Add income or expense", color="white", weight=ft.FontWeight.BOLD)],
                               spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
                on_click=open_money, style=ft.ButtonStyle(bgcolor="#2E8B57"),
            ))
            cards.append(home_card(month_rows, border_color="#FFD700"))

            # ---- month-end to-do list
            all_todos = await load_todos()
            this_key = month_key(today_d)
            todos = [t for t in all_todos if t.get("month") == this_key]
            p_year, p_month = prev_month(today_d.year, today_d.month)
            last_key = f"{p_year:04d}-{p_month:02d}"
            unfinished_last = [t for t in all_todos if t.get("month") == last_key and not t.get("done")]
            todo_rows = [card_title(ft.Icons.CHECKLIST_ROUNDED, f"To-Do for {today_d.strftime('%B')}", color="#4FC3F7",
                                    trailing=link_button("+ Add", lambda e: open_todo_dialog()))]
            if unfinished_last and await prefs.get("todo_carried_" + this_key) != "1":
                n_left = len(unfinished_last)
                todo_rows.append(ft.Container(
                    content=ft.Row(
                        [ft.Icon(ft.Icons.HISTORY_ROUNDED, color="#4FC3F7", size=18),
                         ft.Text(f"{n_left} item{'s' if n_left != 1 else ''} from "
                                 f"{datetime.date(p_year, p_month, 1).strftime('%B')} not done.",
                                 color="white", size=12, expand=True),
                         ft.TextButton(content=ft.Text("Bring over", color="#FFD54F", weight=ft.FontWeight.BOLD, size=12),
                                       on_click=carry_over_todos),
                         ft.IconButton(icon=ft.Icons.CLOSE_ROUNDED, icon_color=SOFT_TEXT, icon_size=16,
                                       on_click=dismiss_carry_over, tooltip="Hide")],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding(left=8, right=0, top=2, bottom=2), border_radius=10,
                    bgcolor=ft.Colors.with_opacity(0.10, "#4FC3F7"),
                ))
            if not todos:
                todo_rows.append(ft.Text("Plan what this month's salary should do: pay rent, send money home, "
                                         "buy foodstuff, save for a goal. Then tick each one off.",
                                         color=SOFT_TEXT, size=12))
            else:
                done_n = len([t for t in todos if t.get("done")])
                planned = sum(todo_amount(t) for t in todos)
                still = sum(todo_amount(t) for t in todos if not t.get("done"))
                todo_rows.append(ft.Row(
                    [ft.Text(f"{done_n} of {len(todos)} done", color="white", size=12, weight=ft.FontWeight.BOLD, expand=True),
                     ft.Text("All done!" if done_n == len(todos) else "", color=MONEY_GREEN, size=12, weight=ft.FontWeight.BOLD)],
                    spacing=6))
                todo_rows.append(ui_progress_bar(done_n / len(todos) * 100.0, "#4FC3F7" if done_n < len(todos) else "#2E8B57"))
                # Not-done items first, in the order they were added; done ones sink to the bottom.
                for t in sorted(todos, key=lambda t: bool(t.get("done"))):
                    is_done = bool(t.get("done"))
                    amt = todo_amount(t)
                    due_dt = todo_due(t)
                    due_label, due_color = "", SOFT_TEXT
                    if due_dt is not None and not is_done:
                        days = (due_dt.date() - today_d).days
                        when = due_dt.strftime("%I:%M %p").lstrip("0")
                        if days < 0 or (days == 0 and due_dt <= datetime.datetime.now()):
                            due_label, due_color = f"Due {fmt_due(due_dt)} (passed)", MONEY_RED
                        elif days == 0:
                            due_label, due_color = f"Today, {when}", "#FFB74D"
                        elif days == 1:
                            due_label, due_color = f"Tomorrow, {when}", "#FFB74D"
                        else:
                            due_label, due_color = fmt_due(due_dt), "#81D4FA"
                    elif due_dt is not None:
                        due_label = fmt_due(due_dt)

                    async def on_tick(e, tid=t["id"]):
                        await toggle_todo(tid, e.control.value)

                    todo_rows.append(ft.Container(
                        content=ft.Row(
                            [
                                ft.Checkbox(value=is_done, on_change=on_tick, active_color="#2E8B57",
                                            check_color="white",
                                            border_side=ft.BorderSide(2, "#4FC3F7")),
                                ft.Column(
                                    [ft.Text(t.get("text", ""), size=15, max_lines=2,
                                             overflow=ft.TextOverflow.ELLIPSIS,
                                             color=SOFT_TEXT if is_done else "#80D8FF",
                                             weight=ft.FontWeight.W_500 if is_done else ft.FontWeight.W_800,
                                             style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH) if is_done else None)]
                                    + ([ft.Row([ft.Icon(ft.Icons.ALARM_ROUNDED, size=13, color=due_color),
                                                ft.Text(due_label, size=11, color=due_color)], spacing=3, tight=True)]
                                       if due_label else []),
                                    spacing=1, tight=True, expand=True,
                                ),
                                ft.Text(money(amt, 0) if amt else "", size=14, weight=ft.FontWeight.W_800,
                                        color=SOFT_TEXT if is_done else "#FFD54F"),
                            ],
                            spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        border_radius=10, padding=ft.Padding(left=0, right=8, top=0, bottom=0),
                        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
                        on_click=lambda e, it=t: open_todo_dialog(it), ink=True,
                    ))
                if planned > 0:
                    # The totals, in bold green so they stand out.
                    todo_rows.append(ft.Container(
                        content=ft.Column(
                            [
                                ft.Row([ft.Text("Total planned", color="white", size=14, weight=ft.FontWeight.BOLD, expand=True),
                                        ft.Text(money(planned, 0), color=MONEY_GREEN, size=17, weight=ft.FontWeight.W_900)]),
                                ft.Row([ft.Text("Still to go" if still > 0 else "All paid", color=SOFT_TEXT, size=13,
                                                weight=ft.FontWeight.BOLD, expand=True),
                                        ft.Text(money(still, 0) if still > 0 else "✓", color=MONEY_GREEN, size=15,
                                                weight=ft.FontWeight.W_800)]),
                            ],
                            spacing=4, tight=True,
                        ),
                        padding=ft.Padding(left=12, right=12, top=10, bottom=10), border_radius=12,
                        bgcolor=ft.Colors.with_opacity(0.12, MONEY_GREEN),
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.45, MONEY_GREEN)),
                    ))
                todo_rows.append(ft.Text("Tick a box when it's done. Tap an item to edit it or set a reminder.",
                                         color=SOFT_TEXT, size=11, italic=True))
            cards.append(home_card(todo_rows, border_color="#4FC3F7"))

            # ---- the four tools
            cards.append(ft.Row([tool_tile(1), tool_tile(2)], spacing=10))
            cards.append(ft.Row([tool_tile(3), tool_tile(4)], spacing=10))

            # ---- budget left
            try:
                budgets = {c: float(v) for c, v in (await load_budgets()).items() if float(v) > 0}
            except Exception:
                budgets = {}
            if budgets:
                total_limit = sum(budgets.values())
                total_used = sum(this["by_cat"].get(c, 0.0) for c in budgets)
                left = total_limit - total_used
                pct = total_used / total_limit * 100.0
                bar_color = "#C62828" if pct >= 100 else ("#FF8C00" if pct >= 80 else "#2E8B57")
                cards.append(home_card(
                    [
                        card_title(ft.Icons.SAVINGS_ROUNDED, "Budget this month"),
                        ft.Text(f"{money(left, 0)} left" if left >= 0 else f"Over by {money(-left, 0)}",
                                size=20, weight=ft.FontWeight.BOLD, color=MONEY_GREEN if left >= 0 else MONEY_RED),
                        ui_progress_bar(pct, bar_color),
                        ft.Text(f"{money(total_used, 0)} used of {money(total_limit, 0)} across "
                                f"{len(budgets)} budget{'s' if len(budgets) != 1 else ''}", color=SOFT_TEXT, size=12),
                    ],
                    on_click=open_money,
                ))
            else:
                cards.append(home_card([
                    card_title(ft.Icons.SAVINGS_ROUNDED, "Budget this month",
                               trailing=link_button("Set a budget", lambda e: open_budget_dialog())),
                    ft.Text("Set a monthly limit for a category (e.g. Food) and see how much is left here.", color=SOFT_TEXT, size=12),
                ]))

            # ---- Ajo: the round that is due soonest
            try:
                groups = await load_ajo_groups()
            except Exception:
                groups = []
            running = []
            for g in groups:
                st = ajo_round_status(g, today_d)
                if st:
                    running.append((g, st))
            running.sort(key=lambda x: (x[1]["days_left"] is None, x[1]["days_left"] or 0))
            if running:
                g, st = running[0]

                async def open_this_group(e, gid=g["id"]):
                    await save_active_ajo_id(gid)
                    await refresh_ajo_ui()
                    await go_to_page("Ajo Groups")

                d = st["days_left"]
                ajo_rows = [
                    card_title(ft.Icons.GROUPS_ROUNDED, st["name"], color="#CE93D8",
                               trailing=ft.Text(f"Round {st['round']} of {st['rounds']}", color="#FFD54F", size=11, weight=ft.FontWeight.BOLD)),
                    ft.Text(f"{st['collector']} collects {money(st['full_pot'], 0)}", color="white", size=15, weight=ft.FontWeight.BOLD),
                ]
                if st["due"]:
                    ajo_rows.append(ft.Text(
                        f"Due {st['due'].strftime('%d %b').lstrip('0')} · {due_phrase(d)}", size=13, weight=ft.FontWeight.BOLD,
                        color=MONEY_RED if d <= 0 else ("#FFB74D" if d <= 7 else MONEY_GREEN)))
                total_members = len(st["paid"]) + len(st["unpaid"])
                ajo_rows.append(ui_progress_bar(len(st["paid"]) / total_members * 100.0 if total_members else 0, "#8E24AA"))
                ajo_rows.append(ft.Text(f"{len(st['paid'])} of {total_members} members have paid", color=SOFT_TEXT, size=12))
                if len(running) > 1:
                    ajo_rows.append(ft.Text(f"+ {len(running) - 1} more group{'s' if len(running) != 2 else ''} running", color=SOFT_TEXT, size=11))
                cards.append(home_card(ajo_rows, on_click=open_this_group))
            else:
                cards.append(home_card([
                    card_title(ft.Icons.GROUPS_ROUNDED, "Ajo Groups", color="#CE93D8",
                               trailing=link_button("Open", open_ajo_page)),
                    ft.Text("No round is running. Start a group or set its order to see the next due date here."
                            if groups else "You're not in any Ajo group yet. Create one or import a shared group.",
                            color=SOFT_TEXT, size=12),
                ]))

            # ---- savings goals
            goals = await load_goals()
            goal_rows = [card_title(ft.Icons.FLAG_ROUNDED, "Savings goals", color=MONEY_GREEN,
                                    trailing=link_button("+ Add goal", lambda e: open_goal_dialog()))]
            if not goals:
                goal_rows.append(ft.Text("Set a goal like “₦500,000 for rent by March” and track how close you are.",
                                         color=SOFT_TEXT, size=12))
            for goal in goals:
                saved, target, pct = goal_numbers(goal)
                hint, hint_color = goal_hint(goal, today_d)
                goal_rows.append(ft.Container(
                    content=ft.Column(
                        [
                            ft.Row([ft.Text(goal.get("name", "Goal"), color="white", size=13, weight=ft.FontWeight.BOLD, expand=True,
                                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(f"{min(pct, 999):.0f}%", color="#FFD54F", size=13, weight=ft.FontWeight.BOLD)], spacing=8),
                            ui_progress_bar(pct, "#2E8B57" if pct < 100 else "#FFD54F"),
                            ft.Text(f"{money(saved, 0)} of {money(target, 0)}", color="white", size=12),
                            ft.Text(mask_text(hint), color=hint_color, size=11),
                        ],
                        spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                    padding=10, border_radius=10, bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
                    on_click=lambda e, g=goal: open_goal_money_dialog(g), ink=True,
                ))
            if goals:
                goal_rows.append(ft.Text("Tap a goal to add money, edit or delete it.", color=SOFT_TEXT, size=11, italic=True))
            cards.append(home_card(goal_rows))

            home_body.controls = cards

        home_tab_content = ft.Column(
            controls=[home_body],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=10,
        )

        # -------------------- REPEATING ENTRIES: manage --------------------
        async def manage_recurring_dialog(e):
            rules = await load_recurring()
            list_col = ft.Column([], spacing=6, tight=True)
            rec_type_row, rec_type_state = build_type_toggle("expense", on_white=True)
            rec_category_picker, rec_category_state = build_category_picker("Housing" if "Housing" in CATEGORY_OPTIONS else "Other")
            amount_field = dlg_field(hint_text="e.g. 150000", keyboard_type=ft.KeyboardType.NUMBER, max_length=15)
            amount_field.on_change = with_length_warning(amount_field, 15)
            note_field = dlg_field(hint_text="e.g. Rent", max_length=40, capitalization=ft.TextCapitalization.WORDS)
            note_field.on_change = with_length_warning(note_field, 40)
            day_field = dlg_field(value=str(datetime.date.today().day), hint_text="1 to 31",
                                  keyboard_type=ft.KeyboardType.NUMBER, max_length=2)
            error_text = ft.Text("", color="red", size=12)
            info_text = ft.Text("", color="#2E8B57", size=12, weight=ft.FontWeight.BOLD)

            def first_date_for(day):
                today_d = datetime.date.today()
                this_due = datetime.date(today_d.year, today_d.month, min(day, calendar.monthrange(today_d.year, today_d.month)[1]))
                if this_due >= today_d:
                    return this_due
                y, m = (today_d.year, today_d.month + 1) if today_d.month < 12 else (today_d.year + 1, 1)
                return datetime.date(y, m, min(day, calendar.monthrange(y, m)[1]))

            def make_delete(rule_id):
                async def _delete(ev):
                    rules[:] = [r for r in rules if r.get("id") != rule_id]
                    await save_recurring(rules)
                    rebuild()
                    page.update()
                return _delete

            def rebuild():
                rows = []
                for r in rules:
                    try:
                        amount = float(r.get("amount", 0) or 0)
                        day = int(r.get("day", 1))
                    except (TypeError, ValueError):
                        amount, day = 0.0, 1
                    is_income = r.get("type") == "income"
                    rows.append(ft.Row(
                        [
                            ft.Icon(category_icon(r.get("category", "Other")), color=PURPLE_TEXT, size=18),
                            ft.Column(
                                [ft.Text((r.get("note") or r.get("category") or "Entry"), color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13,
                                         max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                 ft.Text(f"{'+' if is_income else '-'}{fmt_money(amount, 0)} · day {day} of every month",
                                         color="#2E8B57" if is_income else "#C62828", size=11)],
                                spacing=0, tight=True, expand=True,
                            ),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color="#C62828", icon_size=18,
                                          on_click=make_delete(r.get("id")), tooltip="Stop repeating"),
                        ],
                        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ))
                list_col.controls = rows or [ft.Text("Nothing repeats yet.", color="#666666", size=12, italic=True)]

            async def add_rule(ev):
                try:
                    amount = to_number(amount_field.value, required=True)
                except (ValueError, TypeError):
                    amount = 0.0
                try:
                    day = int((day_field.value or "").strip())
                except ValueError:
                    day = 0
                if amount <= 0:
                    error_text.value = "Enter the amount."
                elif not 1 <= day <= 31:
                    error_text.value = "Day must be a number from 1 to 31."
                elif len(rules) >= 20:
                    error_text.value = "You can keep up to 20 repeating entries."
                else:
                    error_text.value = ""
                if error_text.value:
                    info_text.value = ""
                    page.update()
                    return
                first = first_date_for(day)
                # "last_added" is the month before the first one, so the first entry lands on `first`.
                ly, lm = prev_month(first.year, first.month)
                rules.append({
                    "id": new_ajo_id(), "type": rec_type_state["value"] or "expense",
                    "category": rec_category_state["value"] or "Other", "amount": amount,
                    "note": (note_field.value or "").strip(), "day": day, "last_added": f"{ly:04d}-{lm:02d}",
                })
                await save_recurring(rules)
                amount_field.value = ""
                note_field.value = ""
                rebuild()
                added_now = 0
                try:
                    added_now = await apply_recurring_all()  # due today? add it straight away
                    rules[:] = await load_recurring()
                    rebuild()
                except Exception:
                    pass
                if added_now:
                    current_view_date["year"], current_view_date["month"] = datetime.date.today().year, datetime.date.today().month
                    await refresh_money_ui()
                info_text.value = ("Saved, and added to Money Tracker today. It will repeat every month." if added_now
                                   else f"Saved. The first one will be added on {first.strftime('%d %b %Y').lstrip('0')}.")
                page.update()

            rebuild()
            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Repeating Entries", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("For things that happen every month, like rent, salary or a subscription. "
                                    "The app adds them to this profile's Money Tracker by itself on the day you choose.",
                                    color=DARK_TEXT, size=12),
                            list_col,
                            ft.Divider(height=1, color="#DDDDDD"),
                            ft.Text("Add a repeating entry", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=13),
                            field_with_caption("Type", rec_type_row, on_white=True),
                            field_with_caption("Category", rec_category_picker, on_white=True),
                            field_with_caption("Amount (₦)", amount_field, on_white=True),
                            field_with_caption("Name / note (optional)", note_field, on_white=True),
                            field_with_caption("Day of the month (1 to 31)", day_field, on_white=True),
                            ft.Text("If a month is shorter (e.g. day 31 in February), it is added on the last day.",
                                    color="#666666", size=11),
                            error_text,
                            info_text,
                        ],
                        tight=True, spacing=12,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Done", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.ElevatedButton("Save Entry", on_click=add_rule, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        # -------------------- SHARE AS A PICTURE --------------------
        share_service = ft.Share()
        page.services.append(share_service)

        def brand_header(subtitle):
            return ft.Row(
                [
                    ft.Image(src="background.png", width=38, height=38, fit=ft.BoxFit.COVER, border_radius=10),
                    ft.Column([ft.Text("Naira Finance Hub", color="white", size=14, weight=ft.FontWeight.BOLD),
                               ft.Text(subtitle, color="#FFD54F", size=11, weight=ft.FontWeight.BOLD)], spacing=0, tight=True),
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        def share_card_shell(children):
            return ft.Container(
                content=ft.Column(children, spacing=10, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                width=300, padding=18,
                gradient=ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1), colors=["#6A1BB0", "#2A0845"]),
            )

        def share_line(label, value, value_color="white", size=13):
            return ft.Row([ft.Text(label, color=SOFT_TEXT, size=size), ft.Text(value, color=value_color, size=size, weight=ft.FontWeight.BOLD)],
                          alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        def open_share_card(dialog_title, card, file_stub, share_text="", copy_text=None, plain_lines=None):
            """Shows the picture, then shares it (WhatsApp etc.) or saves it to the phone."""
            shot = ft.Screenshot(content=card)
            status = ft.Text("", size=12, color=DARK_TEXT, text_align=ft.TextAlign.CENTER)
            busy = {"value": False}

            async def capture():
                if busy["value"]:
                    return None
                busy["value"] = True
                problem = ""
                try:
                    # 1) photograph the card on screen (sharp first, then the phone's own sharpness)
                    for ratio in (3, None):
                        try:
                            data = await asyncio.wait_for(shot.capture(pixel_ratio=ratio), timeout=8)
                            if data:
                                return bytes(data)
                        except Exception as ex:
                            problem = f"{type(ex).__name__}: {ex}"[:120]
                    # 2) some phones refuse that: draw the same card ourselves instead
                    if plain_lines:
                        try:
                            return await asyncio.to_thread(render_card_png, plain_lines)
                        except Exception as ex:
                            problem = f"{type(ex).__name__}: {ex}"[:120]
                    status.value = f"Couldn't make the picture. ({problem or 'no picture returned'})"
                    page.update()
                    return None
                finally:
                    busy["value"] = False

            async def save_picture(data):
                try:
                    path = await picker_save_file(
                        dialog_title="Save Picture", file_name=f"{file_stub}.png",
                        file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["png"], src_bytes=data,
                    )
                    status.value = "Picture saved. You can now send it on WhatsApp." if path else "Save cancelled."
                except Exception:
                    status.value = "Couldn't save the picture. Please try again."
                page.update()

            async def on_share(e):
                data = await capture()
                if not data:
                    return
                external_busy["n"] += 1
                try:
                    result = await share_service.share_files(
                        [ft.ShareFile.from_bytes(data, mime_type="image/png", name=f"{file_stub}.png")],
                        text=share_text or None,
                    )
                    unavailable = getattr(result, "status", None) == ft.ShareResultStatus.UNAVAILABLE
                except Exception:
                    unavailable = True
                finally:
                    external_busy["n"] -= 1
                    external_busy["until"] = time.time() + 5
                if unavailable:
                    await save_picture(data)  # no share sheet on this device: save the picture instead

            async def on_save(e):
                data = await capture()
                if data:
                    await save_picture(data)

            async def on_copy(e):
                try:
                    await page.clipboard.set(copy_text)
                    status.value = "Text copied. Paste it in WhatsApp, email, etc."
                except Exception:
                    status.value = "Could not copy automatically."
                page.update()

            actions = [ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))]
            if copy_text:
                actions.append(ft.TextButton("Copy text", on_click=on_copy, style=ft.ButtonStyle(color=PURPLE_TEXT)))
            actions.append(ft.TextButton("Save", on_click=on_save, style=ft.ButtonStyle(color=PURPLE_TEXT)))
            actions.append(ft.ElevatedButton(
                content=ft.Row([ft.Icon(ft.Icons.IOS_SHARE_ROUNDED, color="white", size=16),
                                ft.Text("Share", color="white", weight=ft.FontWeight.BOLD)], spacing=6, tight=True),
                on_click=on_share, style=ft.ButtonStyle(bgcolor="#2E8B57")))
            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                inset_padding=ft.Padding(left=16, right=16, top=24, bottom=24),
                content_padding=ft.Padding(left=12, right=12, top=12, bottom=0),
                title=ft.Text(dialog_title, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column([shot, status], tight=True, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    width=300,
                ),
                actions=actions,
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        def share_ajo_round(group):
            st = ajo_round_status(group)
            if not st:
                snack("This group has no running round to share yet.")
                return

            def names_block(title, names, color, icon):
                rows = [ft.Text(f"{title} ({len(names)})", color=color, size=12, weight=ft.FontWeight.BOLD)]
                rows += [ft.Row([ft.Icon(icon, color=color, size=14), ft.Text(n, color="white", size=13, expand=True)], spacing=6)
                         for n in names]
                if not names:
                    rows.append(ft.Text("None", color=SOFT_TEXT, size=12, italic=True))
                return ft.Column(rows, spacing=3, tight=True)

            children = [
                brand_header("Ajo update"),
                ft.Text(st["name"], color="white", size=20, weight=ft.FontWeight.BOLD),
                ft.Text(f"Round {st['round']} of {st['rounds']}" + (f" · {st['month_label']}" if st["month_label"] else ""),
                        color="#FFD54F", size=12, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Column(
                        [ft.Row([ft.Icon(ft.Icons.EMOJI_EVENTS_ROUNDED, color="#FFD54F", size=18),
                                 ft.Text(f"{st['collector']} collects", color="white", size=14, weight=ft.FontWeight.BOLD, expand=True)], spacing=6),
                         ft.Text(fmt_money(st["full_pot"], 0), color="#FFD54F", size=26, weight=ft.FontWeight.BOLD),
                         ft.Text(f"{fmt_money(st['contribution'], 0)} each · {fmt_money(st['pot'], 0)} in so far", color=SOFT_TEXT, size=11)],
                        spacing=2, tight=True,
                    ),
                    padding=12, border_radius=12, bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.WHITE),
                ),
            ]
            if st["due"]:
                d = st["days_left"]
                children.append(ft.Text(f"Due {st['due'].strftime('%d %b %Y').lstrip('0')} · {due_phrase(d)}", size=13, weight=ft.FontWeight.BOLD,
                                        color=MONEY_RED if d <= 0 else ("#FFB74D" if d <= 7 else MONEY_GREEN)))
            children.append(names_block("Paid", st["paid"], MONEY_GREEN, ft.Icons.CHECK_CIRCLE_ROUNDED))
            children.append(names_block("Yet to pay", st["unpaid"], MONEY_RED, ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED))
            children.append(ft.Text(f"As at {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p').lstrip('0')} · from the Naira Finance Hub app",
                                    color=SOFT_TEXT, size=10))
            plain = [
                ("Naira Finance Hub", "brand"), ("Ajo update", "sub"), ("", "gap"),
                (st["name"], "title"),
                (f"Round {st['round']} of {st['rounds']}" + (f" · {st['month_label']}" if st["month_label"] else ""), "gold"),
                ("", "gap"),
                (f"{st['collector']} collects", "text"),
                (fmt_money(st["full_pot"], 0), "big"),
                (f"{fmt_money(st['contribution'], 0)} each · {fmt_money(st['pot'], 0)} in so far", "soft"),
                ("", "gap"),
            ]
            if st["due"]:
                d = st["days_left"]
                plain.append((f"Due {st['due'].strftime('%d %b %Y').lstrip('0')} · {due_phrase(d)}",
                              "bad" if d <= 0 else ("warn" if d <= 7 else "good")))
                plain.append(("", "gap"))
            plain.append((f"Paid ({len(st['paid'])})", "good"))
            plain += [(f"✔ {n}", "text") for n in st["paid"]] or [("None", "soft")]
            plain.append(("", "gap"))
            plain.append((f"Yet to pay ({len(st['unpaid'])})", "bad"))
            plain += [(f"○ {n}", "text") for n in st["unpaid"]] or [("None", "soft")]
            plain.append(("", "gap"))
            plain.append((f"As at {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p').lstrip('0')} · from the Naira Finance Hub app", "soft"))
            open_share_card(
                "Share This Round", share_card_shell(children), f"Ajo_{safe_filename(st['name'])}_Round_{st['round']}",
                share_text=f"{st['name']} · Round {st['round']} of {st['rounds']}: {len(st['paid'])} paid, {len(st['unpaid'])} yet to pay.",
                plain_lines=plain,
            )

        def share_payslip(result, copy_text):
            children = [
                brand_header("Payslip estimate"),
                share_line("Basic salary", fmt_money(result["basic"])),
                share_line("Housing allowance", fmt_money(result["housing"])),
                share_line("Transport allowance", fmt_money(result["transport"])),
                share_line("Other allowances", fmt_money(result["other"])),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
                share_line("Gross pay (monthly)", fmt_money(result["gross_monthly"]), MONEY_GREEN),
                share_line("Pension (8%)", f"-{fmt_money(result['pension_monthly'])}", MONEY_RED),
                share_line("NHF (2.5%)", f"-{fmt_money(result['nhf_monthly'])}", MONEY_RED),
                share_line("PAYE tax", f"-{fmt_money(result['paye_monthly'])}", MONEY_RED),
                ft.Container(
                    content=ft.Column([ft.Text("Net pay (monthly)", color=SOFT_TEXT, size=12),
                                       ft.Text(fmt_money(result["net_monthly"]), color="#FFD54F", size=26, weight=ft.FontWeight.BOLD)],
                                      spacing=2, tight=True),
                    padding=12, border_radius=12, bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.WHITE),
                ),
                ft.Text("Estimate for guidance only, using the Nigeria Tax Act 2025 bands. Not an official payslip. "
                        "Made with the Naira Finance Hub app.", color=SOFT_TEXT, size=10),
            ]
            plain = [
                ("Naira Finance Hub", "brand"), ("Payslip estimate", "sub"), ("", "gap"),
                ("Basic salary", fmt_money(result["basic"]), "text"),
                ("Housing allowance", fmt_money(result["housing"]), "text"),
                ("Transport allowance", fmt_money(result["transport"]), "text"),
                ("Other allowances", fmt_money(result["other"]), "text"),
                ("", "gap"),
                ("Gross pay (monthly)", fmt_money(result["gross_monthly"]), "good"),
                ("Pension (8%)", f"-{fmt_money(result['pension_monthly'])}", "bad"),
                ("NHF (2.5%)", f"-{fmt_money(result['nhf_monthly'])}", "bad"),
                ("PAYE tax", f"-{fmt_money(result['paye_monthly'])}", "bad"),
                ("", "gap"),
                ("Net pay (monthly)", "soft"),
                (fmt_money(result["net_monthly"]), "big"),
                ("", "gap"),
                ("Estimate for guidance only, using the Nigeria Tax Act 2025 bands. Not an official payslip. "
                 "Made with the Naira Finance Hub app.", "soft"),
            ]
            open_share_card("Share Payslip", share_card_shell(children), "Payslip_Estimate",
                            share_text="My payslip estimate from Naira Finance Hub", copy_text=copy_text, plain_lines=plain)

        # -------------------- APP LOCK (PIN) --------------------
        # Keeps other people who pick up the phone out of the app. The PIN is never stored itself,
        # only a scrambled check value; the data is not encrypted.
        pin_state = {
            "hash": await load_saved("app_pin_hash", ""),
            "salt": await load_saved("app_pin_salt", ""),
            "recovery": await load_saved("app_pin_recovery", ""),
        }
        lock_state = {"locked": bool(pin_state["hash"]), "entered": "", "fails": 0, "blocked_until": 0.0, "hidden_at": None}
        LOCK_PROMPT = "Enter your PIN"
        lock_message = ft.Text(LOCK_PROMPT, color="white", size=16, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
        lock_dots = ft.Row(
            [ft.Container(width=16, height=16, border_radius=8, bgcolor=ft.Colors.with_opacity(0.25, ft.Colors.WHITE)) for _ in range(4)],
            alignment=ft.MainAxisAlignment.CENTER, spacing=16,
        )

        def paint_lock_dots():
            filled = len(lock_state["entered"])
            for i, dot in enumerate(lock_dots.controls):
                dot.bgcolor = "#FFD54F" if i < filled else ft.Colors.with_opacity(0.25, ft.Colors.WHITE)

        async def save_pin(pin, recovery_word):
            salt = os.urandom(8).hex()
            pin_state.update({"salt": salt, "hash": hash_secret(pin, salt),
                              "recovery": hash_secret(recovery_word.strip().lower(), salt)})
            for key in ("hash", "salt", "recovery"):
                await prefs.set(f"app_pin_{key}", pin_state[key])

        async def clear_pin():
            for key in ("hash", "salt", "recovery"):
                pin_state[key] = ""
                await prefs.set(f"app_pin_{key}", "")

        async def unlock_app():
            lock_state.update({"locked": False, "entered": "", "fails": 0})
            paint_lock_dots()
            lock_message.value = LOCK_PROMPT
            lock_overlay.visible = False
            page.update()
            await maybe_show_reminders_popup()

        def lock_app():
            if not pin_state["hash"] or lock_state["locked"]:
                return
            lock_state.update({"locked": True, "entered": ""})
            paint_lock_dots()
            lock_message.value = LOCK_PROMPT
            lock_overlay.visible = True
            for _ in range(6):  # close any pop-up so nothing sits on top of the lock screen
                try:
                    if page.pop_dialog() is None:
                        break
                except Exception:
                    break
            page.update()

        def make_lock_key(key):
            async def press(e):
                if not lock_state["locked"]:
                    return
                wait = lock_state["blocked_until"] - time.time()
                if wait > 0:
                    lock_message.value = f"Too many wrong tries. Wait {int(wait) + 1} seconds."
                    _refresh(lock_message)
                    return
                if key == "back":
                    lock_state["entered"] = lock_state["entered"][:-1]
                elif len(lock_state["entered"]) < 4:
                    lock_state["entered"] += key
                    lock_message.value = LOCK_PROMPT
                if len(lock_state["entered"]) == 4:
                    if hash_secret(lock_state["entered"], pin_state["salt"]) == pin_state["hash"]:
                        await unlock_app()
                        return
                    lock_state["entered"] = ""
                    lock_state["fails"] += 1
                    if lock_state["fails"] >= 5:
                        lock_state["fails"] = 0
                        lock_state["blocked_until"] = time.time() + 30
                        lock_message.value = "Too many wrong tries. Wait 30 seconds."
                    else:
                        lock_message.value = "Wrong PIN. Try again."
                paint_lock_dots()
                _refresh(lock_message, lock_dots)
            return press

        def open_forgot_pin(e):
            word_field = dlg_field(hint_text="Your recovery word", max_length=30, password=True, can_reveal_password=True)
            error_text = ft.Text("", color="red", size=12)

            async def check_word(ev):
                word = (word_field.value or "").strip().lower()
                if word and pin_state["recovery"] and hash_secret(word, pin_state["salt"]) == pin_state["recovery"]:
                    await clear_pin()
                    page.pop_dialog()
                    await unlock_app()
                    snack("PIN removed. You can set a new one in Menu → Settings.", color="#2E8B57", seconds=4)
                else:
                    error_text.value = "That is not the recovery word you saved."
                    page.update()

            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Forgot your PIN?", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Type the recovery word you chose when you set the PIN.", color=DARK_TEXT, size=13),
                            word_field,
                            error_text,
                            ft.Text("Forgot that too? The only way in is to clear this app's storage in your phone's Settings "
                                    "(this deletes the app's data) and then use Restore Data with your backup file.",
                                    color="#666666", size=11),
                        ],
                        tight=True, spacing=10,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.ElevatedButton("Remove PIN", on_click=check_word, style=ft.ButtonStyle(bgcolor="#C62828", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        def lock_key_button(key):
            if key == "forgot":
                return ft.Container(content=ft.Text("Forgot?", color="#FFD54F", size=13, weight=ft.FontWeight.BOLD),
                                    width=68, height=68, alignment=ft.Alignment(0, 0), border_radius=34,
                                    on_click=open_forgot_pin, ink=True)
            if key == "back":
                content = ft.Icon(ft.Icons.BACKSPACE_OUTLINED, color="white", size=24)
                bg = None
            else:
                content = ft.Text(key, color="white", size=26, weight=ft.FontWeight.BOLD)
                bg = ft.Colors.with_opacity(0.14, ft.Colors.WHITE)
            return ft.Container(content=content, width=68, height=68, alignment=ft.Alignment(0, 0), border_radius=34,
                                bgcolor=bg, on_click=make_lock_key(key), ink=True)

        lock_overlay = ft.Container(
            visible=lock_state["locked"],
            left=0, top=0, right=0, bottom=0,
            bgcolor="#2A0845",
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                [
                    ft.Image(src="background.png", width=76, height=76, fit=ft.BoxFit.COVER, border_radius=18),
                    ft.Text("Naira Finance Hub", color="white", size=18, weight=ft.FontWeight.BOLD),
                    ft.Container(height=4),
                    lock_message,
                    lock_dots,
                    ft.Container(height=4),
                ] + [
                    ft.Row([lock_key_button(k) for k in row], alignment=ft.MainAxisAlignment.CENTER, spacing=22)
                    for row in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"), ("forgot", "0", "back"))
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER,
                spacing=14, tight=True,
            ),
        )

        def open_set_pin_dialog():
            def pin_field(hint):
                return dlg_field(hint_text=hint, keyboard_type=ft.KeyboardType.NUMBER, max_length=4, password=True,
                                 can_reveal_password=True, input_filter=ft.NumbersOnlyInputFilter())
            pin1, pin2 = pin_field("4 digits"), pin_field("Type it again")
            word_field = dlg_field(hint_text="e.g. your first school", max_length=30)
            error_text = ft.Text("", color="red", size=12)

            async def save_new_pin(ev):
                a, b = (pin1.value or "").strip(), (pin2.value or "").strip()
                word = (word_field.value or "").strip()
                if len(a) != 4 or not a.isdigit():
                    error_text.value = "The PIN must be exactly 4 digits."
                elif a != b:
                    error_text.value = "The two PINs don't match."
                elif len(word) < 3:
                    error_text.value = "Choose a recovery word of at least 3 letters."
                else:
                    error_text.value = ""
                if error_text.value:
                    page.update()
                    return
                await save_pin(a, word)
                page.pop_dialog()
                snack("App lock is on. You'll be asked for the PIN when you open the app.", color="#2E8B57", seconds=4)

            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text("Set App Lock PIN", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("The app will ask for this PIN each time it is opened, and after it has been in the "
                                    "background for a minute.", color=DARK_TEXT, size=12),
                            field_with_caption("New PIN", pin1, on_white=True),
                            field_with_caption("Confirm PIN", pin2, on_white=True),
                            field_with_caption("Recovery word (used if you forget the PIN)", word_field, on_white=True),
                            ft.Text("Pick a word you will remember but others won't guess. Capital letters don't matter.",
                                    color="#666666", size=11),
                            error_text,
                        ],
                        tight=True, spacing=12,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.ElevatedButton("Turn On", on_click=save_new_pin, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        def open_pin_settings(e):
            if not pin_state["hash"]:
                open_set_pin_dialog()
                return
            current_field = dlg_field(hint_text="Current PIN", keyboard_type=ft.KeyboardType.NUMBER, max_length=4, password=True,
                                      can_reveal_password=True, input_filter=ft.NumbersOnlyInputFilter())
            error_text = ft.Text("", color="red", size=12)

            def pin_ok():
                if hash_secret((current_field.value or "").strip(), pin_state["salt"]) == pin_state["hash"]:
                    return True
                error_text.value = "That PIN is not correct."
                page.update()
                return False

            async def turn_off(ev):
                if pin_ok():
                    await clear_pin()
                    page.pop_dialog()
                    snack("App lock is off.", seconds=3)

            def change_pin(ev):
                if pin_ok():
                    page.pop_dialog()
                    open_set_pin_dialog()

            page.show_dialog(ft.AlertDialog(
                scrollable=True, modal=True, bgcolor="#FFFFFF",
                title=ft.Text("App Lock is On", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [ft.Text("Enter your current PIN to turn the lock off or change the PIN.", color=DARK_TEXT, size=13),
                         current_field, error_text],
                        tight=True, spacing=10,
                    ),
                    width=300,
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda ev: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                    ft.TextButton("Turn off", on_click=turn_off, style=ft.ButtonStyle(color="#C62828")),
                    ft.ElevatedButton("Change PIN", on_click=change_pin, style=ft.ButtonStyle(bgcolor="#2E8B57", color="white")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            ))

        # -------------------- TABS (manual, animated, icon-enhanced) --------------------
        tab_contents = [home_tab_content, housing_tab_content, salary_tab_content, money_tab_content, ajo_tab_content]
        # Reopen on the page you were on last time (e.g. Ajo Groups). The first time after this
        # update, and for new users, the app opens on Home.
        try:
            saved_page = await prefs.get("last_page")
        except Exception:
            saved_page = None
        start_tab = tab_labels.index(saved_page) if saved_page in tab_labels else 0
        current_tab_index = {"value": start_tab}

        tab_content_area = ft.Container(
            content=ft.Container(content=tab_contents[start_tab], padding=ft.Padding(top=15, left=0, right=0, bottom=0)),
            opacity=1,
            scale=1,
            animate_opacity=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
            animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
        )

        current_tab_title = ft.Row(
            [ft.Icon(tab_icons[start_tab], size=20, color=tab_icon_colors[start_tab]), ft.Text(tab_labels[start_tab], size=18, weight=ft.FontWeight.BOLD, color="white")],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
        )

        def select_tab(idx):
            async def handler(e):
                if current_tab_index["value"] == idx:
                    return
                current_tab_index["value"] = idx

                current_tab_title.controls[0].icon = tab_icons[idx]
                current_tab_title.controls[0].color = tab_icon_colors[idx]
                current_tab_title.controls[1].value = tab_labels[idx]

                if tab_labels[idx] == "Home":
                    try:
                        await refresh_home_ui()  # fresh numbers every time you come back to Home
                    except Exception:
                        pass

                # Only redraw the tab area (not the whole app) so switching pages feels instant.
                if motion["on"]:
                    tab_content_area.opacity = 0
                    tab_content_area.scale = 0.96
                    _refresh(current_tab_title, tab_content_area)
                    await asyncio.sleep(0.15)
                tab_content_area.content = ft.Container(content=tab_contents[idx], padding=ft.Padding(top=15, left=0, right=0, bottom=0))
                tab_content_area.opacity = 1
                tab_content_area.scale = 1
                _refresh(current_tab_title, tab_content_area)
                try:
                    await prefs.set("last_page", tab_labels[idx])
                except Exception:
                    pass
            return handler

        try:
            await refresh_home_ui()
        except Exception:
            home_body.controls = [ft.Text("Home could not load. Use the menu to open a page.", color="white", size=13)]

        tab_title_bar = ft.Container(
            content=current_tab_title,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
        )

        tabs = ft.Column(
            controls=[tab_title_bar, tab_content_area],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # -------------------- BANNER AD --------------------
        banner_ad_slot = ft.Container(
            height=50,
            alignment=ft.Alignment(0, 0),
            content=ft.Text("Loading ad...", color="white", size=12) if page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS) else None
        )

        ad_retry = {"count": 0}

        def load_banner_ad():
            if page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
                def on_ad_error(e):
                    # No ad available (no fill, offline, etc.): hide the slot instead of
                    # showing a technical error message, and quietly try again later.
                    banner_ad_slot.content = None
                    banner_ad_slot.height = 0
                    _refresh(banner_ad_slot)
                    if ad_retry["count"] < 3:
                        ad_retry["count"] += 1

                        async def _retry():
                            await asyncio.sleep(60 * ad_retry["count"])  # 1, 2, then 3 min
                            if app_active["value"]:
                                banner_ad_slot.height = 50
                                load_banner_ad()
                        asyncio.create_task(_retry())

                def on_ad_load(e):
                    page.update()

                banner_ad_slot.content = fta.BannerAd(
                    # The personal build shows Google's test ads, so your own phone never counts
                    # as views on your real AdMob account.
                    unit_id=("ca-app-pub-3940256099942544/6300978111" if is_personal_build()
                             else BANNER_AD_UNIT_ID.get(page.platform, BANNER_AD_UNIT_ID[ft.PagePlatform.ANDROID])),
                    width=320,
                    height=50,
                    on_load=on_ad_load,
                    on_error=on_ad_error,
                )
                page.update()

        content_wrapper = ft.Container(
            content=ft.Column(
                controls=[header_container, greeting_row, tabs, ft.Container(height=10), banner_ad_slot],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5,
            ),
            width=420,
            alignment=ft.Alignment(0, -1),
        )

        main_content = ft.Column(
            controls=[content_wrapper, ft.Container(height=40)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        TILT_OVERSCAN = 45

        if is_dark_mode:
            initial_galaxy_stars, initial_galaxy_stack = build_galaxy_background()
        else:
            initial_galaxy_stars, initial_galaxy_stack = [], None

        background_layer = ft.Container(
            content=initial_galaxy_stack if is_dark_mode else build_light_background(),
            bgcolor=None,
            left=-TILT_OVERSCAN, top=-TILT_OVERSCAN, right=-TILT_OVERSCAN, bottom=-TILT_OVERSCAN,
            animate_position=ft.Animation(80, ft.AnimationCurve.EASE_OUT),
        )
        if is_dark_mode:
            galaxy_stars_active["value"] = True
            asyncio.create_task(twinkle_galaxy(initial_galaxy_stars))

        foreground_layer = ft.Container(
            content=main_content, alignment=ft.Alignment(0, -1), padding=10,
            left=0, top=0, right=0, bottom=0,
            animate_position=ft.Animation(80, ft.AnimationCurve.EASE_OUT),
        )

        last_tilt_update = {"time": 0.0}

        def handle_tilt_reading(e: ft.AccelerometerReadingEvent):
            try:
                # Never let a tilt reading trigger Flet's automatic whole-page redraw;
                # we redraw just the background and logo ourselves below.
                ft.context.mark_update_called()
            except Exception:
                pass
            try:
                if not app_active["value"] or not motion["on"]:
                    return
                now = asyncio.get_event_loop().time()
                if now - last_tilt_update["time"] < 0.12:
                    return
                last_tilt_update["time"] = now

                tilt_x = max(-9.8, min(9.8, e.x))
                tilt_y = max(-9.8, min(9.8, e.y))
                # Ignore tiny sensor jitter so a phone lying still doesn't redraw the screen 8x a second.
                if abs(tilt_x - last_tilt_update.get("x", 99)) < 0.15 and abs(tilt_y - last_tilt_update.get("y", 99)) < 0.15:
                    return
                last_tilt_update["x"], last_tilt_update["y"] = tilt_x, tilt_y

                bg_shift_x = tilt_x * 3.6
                bg_shift_y = tilt_y * 3.6
                background_layer.left = -TILT_OVERSCAN + bg_shift_x
                background_layer.right = -TILT_OVERSCAN - bg_shift_x
                background_layer.top = -TILT_OVERSCAN + bg_shift_y
                background_layer.bottom = -TILT_OVERSCAN - bg_shift_y

                logo_offset_x = max(-0.15, min(0.15, tilt_x * 0.02))
                logo_offset_y = max(-0.15, min(0.15, tilt_y * 0.02))
                logo_wrapper.offset = ft.Offset(logo_offset_x, logo_offset_y)

                _refresh(background_layer, logo_wrapper)
            except Exception:
                pass

        def handle_tilt_error(e: ft.SensorErrorEvent):
            pass

        tilt_sensor = {"control": None}

        def start_tilt_sensor():
            _SENSOR_GATE["on"] = True
            if tilt_sensor["control"] is None:
                tilt_sensor["control"] = ft.Accelerometer(
                    on_reading=handle_tilt_reading,
                    on_error=handle_tilt_error,
                    interval=ft.Duration(milliseconds=120),
                    cancel_on_error=False,
                )
                page.services.append(tilt_sensor["control"])

        def stop_tilt_sensor():
            _SENSOR_GATE["on"] = False
            sensor = tilt_sensor["control"]
            tilt_sensor["control"] = None
            if sensor is not None:
                try:
                    page.services.remove(sensor)
                except Exception:
                    pass
            # Put the background and logo back in the middle.
            background_layer.left = background_layer.top = -TILT_OVERSCAN
            background_layer.right = background_layer.bottom = -TILT_OVERSCAN
            logo_wrapper.offset = ft.Offset(0, 0)

        if motion["on"]:
            start_tilt_sensor()

        async def set_motion_effects(on):
            motion["on"] = bool(on)
            try:
                await prefs.set("motion_effects", "on" if on else "off")
            except Exception:
                pass
            if on:
                start_tilt_sensor()
            else:
                stop_tilt_sensor()
                logo_container.scale = 1.0
                wave_hand.rotate = 0
            restart_galaxy()
            page.update()

        settings_actions["motion"] = set_motion_effects

        hamburger_positioned = ft.Container(
            content=hamburger_menu_btn,
            left=10,
            top=40,
        )

        ajo_draw_overlay_container = ft.Container(
            visible=False,
            bgcolor="#0D0D1A",
            left=0, top=0, right=0, bottom=0,
        )

        view_container = ft.Stack(
            controls=[
                background_layer,
                foreground_layer,
                hamburger_positioned,
                ajo_draw_overlay_container,
                lock_overlay,
            ],
            expand=True,
            opacity=0,
            animate_opacity=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
        )

        page.controls.clear()
        if not motion["on"]:
            view_container.opacity = 1
            view_container.animate_opacity = None
        page.add(view_container)
        page.update()
        if motion["on"]:
            await asyncio.sleep(0.03)
            view_container.opacity = 1
            _refresh(view_container)

        async def after_first_screen():
            # Heavy extras wait until the app is already usable.
            await asyncio.sleep(2.5)
            if build_gen["n"] != my_gen:
                return
            if os.path.exists(NOTIF_INBOX_FILE) or os.path.exists(NOTIF_INBOX_FILE + ".processing"):
                last_auto_ingest["t"] = 0.0
                try:
                    await asyncio.wait_for(refresh_money_ui(), timeout=15)
                    page.update()
                except Exception:
                    pass
            asyncio.create_task(todo_reminder_loop())
            await maybe_show_reminders_popup()
            await asyncio.sleep(1.5)
            if build_gen["n"] == my_gen:
                load_banner_ad()

        asyncio.create_task(after_first_screen())
        resume_state = {"task": None}

        async def _catch_up_after_resume():
            # Runs in the background so the screen is usable the instant you come back,
            # and gives up after 10 s instead of freezing the app if something is stuck.
            try:
                await asyncio.wait_for(check_todo_reminders(), timeout=5)
            except Exception:
                pass
            try:
                await asyncio.wait_for(apply_recurring_all(), timeout=5)
            except Exception:
                pass
            try:
                await asyncio.wait_for(refresh_money_ui(), timeout=10)
            except Exception:
                pass
            try:
                if tab_labels[current_tab_index["value"]] == "Home":
                    await asyncio.wait_for(refresh_home_ui(), timeout=5)
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass
            if draw_sound.pop("resume_after", False) and ajo_draw_overlay_container.visible:
                try:
                    await asyncio.wait_for(start_draw_music(), timeout=3)
                except Exception:
                    pass

        async def on_app_lifecycle(e):
            state = getattr(e, "state", None)
            if state in (ft.AppLifecycleState.HIDE, ft.AppLifecycleState.PAUSE):
                app_active["value"] = False
                if lock_state["hidden_at"] is None:
                    lock_state["hidden_at"] = time.time()
                if draw_sound["music_playing"]:
                    draw_sound["resume_after"] = True
                    try:
                        # The phone may stop answering while the app is hidden; never wait forever.
                        await asyncio.wait_for(stop_draw_music(), timeout=3)
                    except Exception:
                        draw_sound["music_playing"] = False
            elif state in (ft.AppLifecycleState.RESUME, ft.AppLifecycleState.SHOW):
                hidden_at, lock_state["hidden_at"] = lock_state["hidden_at"], None
                in_chooser = external_busy["n"] > 0 or time.time() < external_busy["until"]
                if hidden_at is not None and time.time() - hidden_at > 60 and not in_chooser:
                    lock_app()  # away for over a minute: ask for the PIN again (if one is set)
                if not app_active["value"]:
                    app_active["value"] = True
                    running = resume_state["task"]
                    if running is None or running.done():
                        resume_state["task"] = asyncio.create_task(_catch_up_after_resume())

        page.on_app_lifecycle_state_change = on_app_lifecycle
        asyncio.create_task(animate_logo_pulse_loop())
        asyncio.create_task(animate_logo_spin_loop())
        asyncio.create_task(animate_wave_loop())

    # ==================================================================
    # STARTUP FLOW
    # ==================================================================
    # Show the logo straight away while saved data loads, instead of a blank screen.
    page.bgcolor = "#4B0082"
    page.controls.clear()
    page.add(ft.Container(
        content=ft.Column(
            [ft.Image(src="background.png", width=110, height=110, fit=ft.BoxFit.COVER, border_radius=24),
             ft.Text("Naira Finance Hub", size=20, weight=ft.FontWeight.BOLD, color="white"),
             ft.ProgressRing(width=22, height=22, stroke_width=3, color="#FFD700")],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=14,
        ),
        expand=True, alignment=ft.Alignment(0, 0),
    ))
    page.update()
    await prefs.preload()

    try:
        terms_already_accepted = await prefs.get("terms_accepted")
    except Exception:
        terms_already_accepted = False

    if not terms_already_accepted:
        show_terms_screen()
    else:
        await check_name()


async def main(page: ft.Page):
    try:
        await build_ui(page)
    except Exception as ex:
        import traceback
        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Startup Error", size=20, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(str(ex), size=14, color="yellow", selectable=True),
                        ft.Divider(color="white"),
                        ft.Text(traceback.format_exc(), size=10, color="white", selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
                padding=20,
                expand=True,
            )
        )
        page.update()

if __name__ == "__main__":
    ft.run(main)
