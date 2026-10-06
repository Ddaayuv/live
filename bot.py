#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تواصل (مراسلة مجهولة) - Telegram Anonymous Messaging Bot
================================================================
الميزات:
  - طريقة استخدام أوامر البوت
  - تغيير الرد التلقائي
  - تغيير رسالة الترحيب
  - تفعيل / تعطيل إظهار هوية المرسل عند التوجيه للمطوّر
  - الاشتراك الإجباري في قناة/قنوات قبل استخدام البوت
  - الإحصائيات (عدد المستخدمين، عدد الرسائل، ...)
  - قائمة المحظورين (حظر / فك حظر)
  - إذاعة (بث) رسالة لجميع المشتركين
  - إعدادات أخرى للبوت
  - مراسلة المبرمج للاستفسار (يظهر للمستخدمين، ويتيح للمطوّر الرد)

يعتمد على مكتبة python-telegram-bot (الإصدار 20+).
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberUpdated,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

# ----------------------------------------------------------------------------
# الإعدادات الأساسية - عدّلها قبل التشغيل
# ----------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT-YOUR-BOT-TOKEN-HERE")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
# مثال: ADMIN_IDS = [123456789]  (يمكن إضافة أكثر من مطوّر/مشرف)

# مجلد حفظ البيانات: على Render ضع DATA_DIR=/data إذا أضفت Persistent Disk
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "data.json")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# تخزين البيانات (JSON بسيط - يمكن استبداله بقاعدة بيانات لاحقاً)
# ----------------------------------------------------------------------------
DEFAULT_DATA = {
    "settings": {
        "welcome_message": "👋 مرحباً بك في البوت!\nأرسل رسالتك وسيتم توصيلها مباشرة.",
        "auto_reply": "✅ تم استلام رسالتك، سيتم الرد عليك في أقرب وقت.",
        "show_identity": True,  # تفعيل/تعطيل إظهار هوية المرسل للمطوّر
        "force_sub_channels": [],  # ["@channel_username", ...]
        "bot_enabled": True,
    },
    "users": {},  # "user_id": {"first_name":..., "username":..., "joined_at":...}
    "banned": [],  # [user_id, ...]
    "stats": {
        "total_messages": 0,
        "total_broadcasts": 0,
    },
    "message_map": {},  # "admin_forwarded_msg_id": {"user_id": ..., "user_msg_id": ...} (للربط عند الرد كـ Reply حقيقي)
}


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_DB_LOCK = threading.Lock()


@contextmanager
def _db_cursor():
    """يفتح اتصال، ينفّذ commit عند النجاح، ثم يغلق الاتصال دائماً."""
    import psycopg2

    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    try:
        with conn, conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def _db_init() -> None:
    with _db_cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS bot_data ("
            "id INTEGER PRIMARY KEY, data JSONB NOT NULL, "
            "updated_at TIMESTAMPTZ DEFAULT now())"
        )


def _fill_defaults(data: dict) -> dict:
    # التأكد من وجود كل المفاتيح الأساسية (عند تحديث البوت مستقبلاً)
    for key, value in DEFAULT_DATA.items():
        data.setdefault(key, json.loads(json.dumps(value)))
    for key, value in DEFAULT_DATA["settings"].items():
        data["settings"].setdefault(key, value)
    return data


def _load_from_file():
    if not os.path.exists(DATA_FILE):
        return None
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_data() -> dict:
    if DATABASE_URL:
        from psycopg2.extras import Json

        _db_init()
        with _db_cursor() as cur:
            cur.execute("SELECT data FROM bot_data WHERE id = 1")
            row = cur.fetchone()
            if row:
                return _fill_defaults(row[0])
            # أول تشغيل: استيراد data.json القديم إن وُجد، وإلا بيانات افتراضية
            data = _load_from_file() or json.loads(json.dumps(DEFAULT_DATA))
            data = _fill_defaults(data)
            cur.execute(
                "INSERT INTO bot_data (id, data) VALUES (1, %s)", (Json(data),)
            )
            return data

    data = _load_from_file()
    if data is None:
        save_data(DEFAULT_DATA)
        return json.loads(json.dumps(DEFAULT_DATA))
    return _fill_defaults(data)


def save_data(data: dict) -> None:
    if DATABASE_URL:
        from psycopg2.extras import Json

        try:
            with _DB_LOCK, _db_cursor() as cur:
                cur.execute(
                    "INSERT INTO bot_data (id, data) VALUES (1, %s) "
                    "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                    (Json(data),),
                )
        except Exception:
            logger.exception("فشل حفظ البيانات في قاعدة البيانات")
        return
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


DATA = load_data()

# awaiting_input[admin_id] = "auto_reply" | "welcome" | "broadcast" | "add_channel" | "remove_channel" | "ban" | "unban"
AWAITING_INPUT: dict[int, str] = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ----------------------------------------------------------------------------
# لوحات المفاتيح (القوائم)
# ----------------------------------------------------------------------------
def main_admin_menu() -> InlineKeyboardMarkup:
    identity_status = "✅ مُفعل" if DATA["settings"]["show_identity"] else "❌ مُعطل"
    buttons = [
        [InlineKeyboardButton("📖 طريقة أستخدام اوامر البوت", callback_data="help_admin")],
        [
            InlineKeyboardButton("✳️ تغيير الرد التلقائي", callback_data="set_auto_reply"),
            InlineKeyboardButton("✳️ تغيير رسالة الترحيب", callback_data="set_welcome"),
        ],
        [InlineKeyboardButton(f"تفعل الهوية: {identity_status}", callback_data="toggle_identity")],
        [
            InlineKeyboardButton("✳️ الاشتراك الإجباري", callback_data="force_sub_menu"),
            InlineKeyboardButton("✳️ الاحصائيات", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("📮 اذاعة للمشتركين", callback_data="broadcast_start"),
            InlineKeyboardButton("🚫 قائمة المحظورين", callback_data="banned_list"),
        ],
        [InlineKeyboardButton("⚙️ اعدادات أخرى للبوت", callback_data="other_settings")],
    ]
    return InlineKeyboardMarkup(buttons)


def force_sub_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel")],
        [InlineKeyboardButton("➖ حذف قناة", callback_data="remove_channel")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(buttons)


def banned_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("➕ حظر مستخدم (بالأيدي)", callback_data="ban_user")],
        [InlineKeyboardButton("➖ فك حظر مستخدم", callback_data="unban_user")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(buttons)


def other_settings_kb() -> InlineKeyboardMarkup:
    bot_status = "✅ يعمل" if DATA["settings"]["bot_enabled"] else "🛑 متوقف"
    buttons = [
        [InlineKeyboardButton(f"حالة البوت: {bot_status}", callback_data="toggle_bot_status")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(buttons)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])


def forwarded_msg_kb(target_user_id: int, target_msg_id: int) -> InlineKeyboardMarkup:
    """أزرار (اضغط للرد / حظر) تظهر تحت كل رسالة موجّهة من مستخدم للمطوّر."""
    buttons = [
        [
            InlineKeyboardButton("✅ اضغط للرد", callback_data=f"replybtn:{target_user_id}:{target_msg_id}"),
            InlineKeyboardButton("⛔ حظر", callback_data=f"banbtn:{target_user_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


# ----------------------------------------------------------------------------
# التحقق من الاشتراك الإجباري
# ----------------------------------------------------------------------------
async def check_force_sub(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    """يرجع قائمة القنوات التي لم يشترك بها المستخدم بعد."""
    missing = []
    for channel in DATA["settings"]["force_sub_channels"]:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                missing.append(channel)
        except TelegramError:
            # لو تعذر التحقق (البوت ليس مشرفاً في القناة مثلاً) نتجاهلها بدل تعطيل البوت
            logger.warning("تعذر التحقق من الاشتراك في %s", channel)
    return missing


def force_sub_keyboard(missing: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"📢 اشترك في {ch}", url=f"https://t.me/{ch.lstrip('@')}")]
        for ch in missing
    ]
    buttons.append([InlineKeyboardButton("✅ تحققت من الاشتراك", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)


# ----------------------------------------------------------------------------
# أوامر المستخدم العادي
# ----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id_str = str(user.id)

    if user.id not in DATA["banned"]:
        DATA["users"].setdefault(
            user_id_str,
            {
                "first_name": user.first_name,
                "username": user.username,
                "joined_at": datetime.utcnow().isoformat(),
            },
        )
        save_data(DATA)

    if user.id in DATA["banned"]:
        await update.message.reply_text("🚫 أنت محظور من استخدام هذا البوت.")
        return

    missing = await check_force_sub(user.id, context)
    if missing:
        await update.message.reply_text(
            "⚠️ يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:",
            reply_markup=force_sub_keyboard(missing),
        )
        return

    await update.message.reply_text(DATA["settings"]["welcome_message"])

    if is_admin(user.id):
        await update.message.reply_text(
            "🛠 لوحة تحكم المطوّر:", reply_markup=main_admin_menu()
        )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🛠 لوحة تحكم المطوّر:", reply_markup=main_admin_menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 <b>طريقة استخدام البوت</b>\n\n"
        "• أرسل أي رسالة نصية / صورة / فيديو وسيتم توصيلها مباشرة للمطوّر.\n"
        "• سيصلك رد تلقائي فور إرسال رسالتك.\n"
        "• عند رد المطوّر عليك، ستصلك رسالته مباشرة هنا.\n\n"
        "<b>أوامر المطوّر:</b>\n"
        "/admin - فتح لوحة التحكم\n"
        "/stats - عرض الإحصائيات\n"
        "/ban [id] - حظر مستخدم\n"
        "/unban [id] - فك حظر مستخدم\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ----------------------------------------------------------------------------
# استقبال رسائل المستخدمين وتوجيهها للمطوّر (نظام المراسلة المجهولة)
# ----------------------------------------------------------------------------
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message

    if not DATA["settings"]["bot_enabled"] and not is_admin(user.id):
        await message.reply_text("🛑 البوت متوقف مؤقتاً، حاول لاحقاً.")
        return

    if user.id in DATA["banned"]:
        await message.reply_text("🚫 أنت محظور من استخدام هذا البوت.")
        return

    missing = await check_force_sub(user.id, context)
    if missing:
        await message.reply_text(
            "⚠️ يجب عليك الاشتراك في القنوات التالية أولاً:",
            reply_markup=force_sub_keyboard(missing),
        )
        return

    # لو المُرسل هو المطوّر ويرد على رسالة موجّهة من مستخدم -> أرسل الرد لذلك المستخدم
    if is_admin(user.id) and message.reply_to_message:
        replied_id = str(message.reply_to_message.message_id)
        link = DATA["message_map"].get(replied_id)
        if link:
            target_user_id = link["user_id"] if isinstance(link, dict) else link
            target_msg_id = link.get("user_msg_id") if isinstance(link, dict) else None
            try:
                await context.bot.copy_message(
                    chat_id=int(target_user_id),
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                    reply_to_message_id=target_msg_id,  # يظهر عند المستخدم كـ Reply على رسالته الأصلية
                    allow_sending_without_reply=True,
                )
                await message.reply_text("✅ تم إرسال ردّك للمستخدم.")
            except TelegramError as e:
                await message.reply_text(f"⚠️ تعذر إرسال الرد: {e}")
            return

    if is_admin(user.id):
        # رسالة عادية من المطوّر بدون رد على أحد (تجاهل، أو استخدم /admin)
        return

    # توجيه رسالة المستخدم لكل المطوّرين
    for admin_id in ADMIN_IDS:
        try:
            if DATA["settings"]["show_identity"]:
                header = (
                    f"📩 رسالة جديدة من:\n"
                    f"الاسم: {user.first_name}\n"
                    f"المعرف: @{user.username if user.username else 'لا يوجد'}\n"
                    f"الأيدي: <code>{user.id}</code>"
                )
                await context.bot.send_message(chat_id=admin_id, text=header, parse_mode=ParseMode.HTML)
            forwarded = await context.bot.copy_message(
                chat_id=admin_id,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
            )
            DATA["message_map"][str(forwarded.message_id)] = {
                "user_id": str(user.id),
                "user_msg_id": message.message_id,
            }
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=admin_id,
                    message_id=forwarded.message_id,
                    reply_markup=forwarded_msg_kb(user.id, message.message_id),
                )
            except TelegramError:
                pass  # بعض أنواع الرسائل قد لا تدعم تعديل الأزرار، نتجاهل الخطأ
        except TelegramError as e:
            logger.error("تعذر توجيه الرسالة للمطوّر %s: %s", admin_id, e)

    DATA["stats"]["total_messages"] += 1
    save_data(DATA)

    await message.reply_text(DATA["settings"]["auto_reply"])


# ----------------------------------------------------------------------------
# استقبال ضغطات الأزرار (لوحة تحكم المطوّر)
# ----------------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "check_sub":
        missing = await check_force_sub(user_id, context)
        if missing:
            await query.answer("لا زلت غير مشترك في كل القنوات المطلوبة.", show_alert=True)
        else:
            await query.answer("✅ تم التحقق، يمكنك الآن استخدام البوت.", show_alert=True)
            await query.message.delete()
        return

    if not is_admin(user_id):
        await query.answer("⛔ هذه الأزرار مخصصة للمطوّر فقط.", show_alert=True)
        return

    await query.answer()

    if data.startswith("replybtn:"):
        _, target_uid, target_msgid = data.split(":", 2)
        AWAITING_INPUT[user_id] = f"reply:{target_uid}:{target_msgid}"
        await context.bot.send_message(
            chat_id=user_id,
            text="✍️ اكتب الآن ردّك (نص/صورة/فيديو...) وسيتم إرساله للمستخدم مباشرة كـ Reply.",
        )
        return

    if data.startswith("banbtn:"):
        _, target_uid = data.split(":", 1)
        tuid = int(target_uid)
        if tuid not in DATA["banned"]:
            DATA["banned"].append(tuid)
            save_data(DATA)
        await context.bot.send_message(chat_id=user_id, text=f"🚫 تم حظر المستخدم {tuid}.")
        return

    if data == "back_main":
        await query.edit_message_text("🛠 لوحة تحكم المطوّر:", reply_markup=main_admin_menu())

    elif data == "help_admin":
        text = (
            "📖 <b>أوامر وأزرار لوحة التحكم</b>\n\n"
            "✳️ <b>تغيير الرد التلقائي</b>: الرسالة التي تصل للمستخدم بعد إرساله رسالة.\n"
            "✳️ <b>تغيير رسالة الترحيب</b>: تظهر عند /start.\n"
            "✳️ <b>تفعيل الهوية</b>: إظهار/إخفاء اسم ومعرف المرسل عند توجيه رسالته لك.\n"
            "✳️ <b>الاشتراك الإجباري</b>: إجبار المستخدمين على الاشتراك بقناة قبل استخدام البوت.\n"
            "✳️ <b>الإحصائيات</b>: عدد المستخدمين والرسائل.\n"
            "🚫 <b>قائمة المحظورين</b>: حظر أو فك حظر مستخدم بالأيدي.\n"
            "📮 <b>إذاعة</b>: إرسال رسالة لكل المستخدمين دفعة واحدة.\n"
            "⚙️ <b>إعدادات أخرى</b>: تشغيل/إيقاف البوت مؤقتاً.\n\n"
            "للرد على مستخدم: فقط اعمل Reply على رسالته المُوجّهة إليك واكتب ردك."
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "set_auto_reply":
        AWAITING_INPUT[user_id] = "auto_reply"
        await query.edit_message_text(
            f"✍️ أرسل الآن نص الرد التلقائي الجديد.\n\nالحالي:\n{DATA['settings']['auto_reply']}",
            reply_markup=back_kb(),
        )

    elif data == "set_welcome":
        AWAITING_INPUT[user_id] = "welcome"
        await query.edit_message_text(
            f"✍️ أرسل الآن نص رسالة الترحيب الجديدة.\n\nالحالية:\n{DATA['settings']['welcome_message']}",
            reply_markup=back_kb(),
        )

    elif data == "toggle_identity":
        DATA["settings"]["show_identity"] = not DATA["settings"]["show_identity"]
        save_data(DATA)
        await query.edit_message_text("🛠 لوحة تحكم المطوّر:", reply_markup=main_admin_menu())

    elif data == "force_sub_menu":
        channels = DATA["settings"]["force_sub_channels"]
        text = "📢 قنوات الاشتراك الإجباري الحالية:\n" + (
            "\n".join(channels) if channels else "لا توجد قنوات مضافة."
        )
        await query.edit_message_text(text, reply_markup=force_sub_menu_kb())

    elif data == "add_channel":
        AWAITING_INPUT[user_id] = "add_channel"
        await query.edit_message_text(
            "✍️ أرسل معرف القناة (مثال: @my_channel).\nملاحظة: يجب أن يكون البوت مشرفاً في القناة.",
            reply_markup=back_kb(),
        )

    elif data == "remove_channel":
        AWAITING_INPUT[user_id] = "remove_channel"
        await query.edit_message_text("✍️ أرسل معرف القناة التي تريد حذفها.", reply_markup=back_kb())

    elif data == "stats":
        text = (
            "📊 <b>إحصائيات البوت</b>\n\n"
            f"👥 عدد المستخدمين: {len(DATA['users'])}\n"
            f"✉️ إجمالي الرسائل المستلمة: {DATA['stats']['total_messages']}\n"
            f"📮 عدد مرات الإذاعة: {DATA['stats']['total_broadcasts']}\n"
            f"🚫 عدد المحظورين: {len(DATA['banned'])}"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "banned_list":
        banned = DATA["banned"]
        text = "🚫 قائمة المحظورين:\n" + (
            "\n".join(str(x) for x in banned) if banned else "لا يوجد محظورون حالياً."
        )
        await query.edit_message_text(text, reply_markup=banned_menu_kb())

    elif data == "ban_user":
        AWAITING_INPUT[user_id] = "ban"
        await query.edit_message_text("✍️ أرسل آيدي المستخدم المراد حظره.", reply_markup=back_kb())

    elif data == "unban_user":
        AWAITING_INPUT[user_id] = "unban"
        await query.edit_message_text("✍️ أرسل آيدي المستخدم المراد فك حظره.", reply_markup=back_kb())

    elif data == "broadcast_start":
        AWAITING_INPUT[user_id] = "broadcast"
        await query.edit_message_text(
            "✍️ أرسل الرسالة (نص/صورة/فيديو) التي تريد إذاعتها لجميع المستخدمين.",
            reply_markup=back_kb(),
        )

    elif data == "other_settings":
        await query.edit_message_text("⚙️ إعدادات أخرى:", reply_markup=other_settings_kb())

    elif data == "toggle_bot_status":
        DATA["settings"]["bot_enabled"] = not DATA["settings"]["bot_enabled"]
        save_data(DATA)
        await query.edit_message_text("⚙️ إعدادات أخرى:", reply_markup=other_settings_kb())


# ----------------------------------------------------------------------------
# استقبال الرد النصي/الوسائط بعد اختيار المطوّر لإحدى عمليات الإدخال أعلاه
# ----------------------------------------------------------------------------
async def admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """يرجع True لو تمت معالجة الرسالة كإدخال إداري (لمنع تمريرها كرسالة عادية)."""
    user_id = update.effective_user.id
    if user_id not in AWAITING_INPUT:
        return False

    action = AWAITING_INPUT.pop(user_id)
    message = update.message
    text = message.text or message.caption or ""

    if action.startswith("reply:"):
        _, target_uid, target_msgid = action.split(":", 2)
        try:
            await context.bot.copy_message(
                chat_id=int(target_uid),
                from_chat_id=message.chat_id,
                message_id=message.message_id,
                reply_to_message_id=int(target_msgid),
                allow_sending_without_reply=True,
            )
            await message.reply_text("✅ تم إرسال ردّك للمستخدم.")
        except TelegramError as e:
            await message.reply_text(f"⚠️ تعذر إرسال الرد: {e}")
        return True

    if action == "auto_reply":
        DATA["settings"]["auto_reply"] = text
        save_data(DATA)
        await message.reply_text("✅ تم تحديث الرد التلقائي.", reply_markup=back_kb())

    elif action == "welcome":
        DATA["settings"]["welcome_message"] = text
        save_data(DATA)
        await message.reply_text("✅ تم تحديث رسالة الترحيب.", reply_markup=back_kb())

    elif action == "add_channel":
        channel = text.strip()
        if not channel.startswith("@"):
            channel = "@" + channel
        if channel not in DATA["settings"]["force_sub_channels"]:
            DATA["settings"]["force_sub_channels"].append(channel)
            save_data(DATA)
        await message.reply_text(f"✅ تم إضافة {channel} لقائمة الاشتراك الإجباري.", reply_markup=back_kb())

    elif action == "remove_channel":
        channel = text.strip()
        if not channel.startswith("@"):
            channel = "@" + channel
        if channel in DATA["settings"]["force_sub_channels"]:
            DATA["settings"]["force_sub_channels"].remove(channel)
            save_data(DATA)
            await message.reply_text(f"✅ تم حذف {channel}.", reply_markup=back_kb())
        else:
            await message.reply_text("⚠️ هذه القناة غير موجودة في القائمة.", reply_markup=back_kb())

    elif action == "ban":
        try:
            uid = int(text.strip())
            if uid not in DATA["banned"]:
                DATA["banned"].append(uid)
                save_data(DATA)
            await message.reply_text(f"🚫 تم حظر المستخدم {uid}.", reply_markup=back_kb())
        except ValueError:
            await message.reply_text("⚠️ آيدي غير صحيح.", reply_markup=back_kb())

    elif action == "unban":
        try:
            uid = int(text.strip())
            if uid in DATA["banned"]:
                DATA["banned"].remove(uid)
                save_data(DATA)
                await message.reply_text(f"✅ تم فك حظر المستخدم {uid}.", reply_markup=back_kb())
            else:
                await message.reply_text("⚠️ هذا المستخدم غير محظور أصلاً.", reply_markup=back_kb())
        except ValueError:
            await message.reply_text("⚠️ آيدي غير صحيح.", reply_markup=back_kb())

    elif action == "broadcast":
        sent, failed = 0, 0
        for uid_str in list(DATA["users"].keys()):
            try:
                await context.bot.copy_message(
                    chat_id=int(uid_str),
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                )
                sent += 1
            except TelegramError:
                failed += 1
        DATA["stats"]["total_broadcasts"] += 1
        save_data(DATA)
        await message.reply_text(
            f"📮 تم إرسال الإذاعة.\n✅ نجح: {sent}\n❌ فشل: {failed}", reply_markup=back_kb()
        )

    return True


# ----------------------------------------------------------------------------
# موجّه الرسائل الرئيسي: يميّز بين إدخال إداري ورسالة عادية
# ----------------------------------------------------------------------------
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if is_admin(user_id) and user_id in AWAITING_INPUT:
        handled = await admin_text_input(update, context)
        if handled:
            return
    await handle_user_message(update, context)


# ----------------------------------------------------------------------------
# أوامر إدارية سريعة (اختيارية، بديل عن الأزرار)
# ----------------------------------------------------------------------------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    text = (
        f"👥 عدد المستخدمين: {len(DATA['users'])}\n"
        f"✉️ إجمالي الرسائل: {DATA['stats']['total_messages']}\n"
        f"🚫 عدد المحظورين: {len(DATA['banned'])}"
    )
    await update.message.reply_text(text)


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("الاستخدام: /ban <user_id>")
        return
    uid = int(context.args[0])
    if uid not in DATA["banned"]:
        DATA["banned"].append(uid)
        save_data(DATA)
    await update.message.reply_text(f"🚫 تم حظر {uid}.")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("الاستخدام: /unban <user_id>")
        return
    uid = int(context.args[0])
    if uid in DATA["banned"]:
        DATA["banned"].remove(uid)
        save_data(DATA)
    await update.message.reply_text(f"✅ تم فك حظر {uid}.")


# ----------------------------------------------------------------------------
# سيرفر صغير للـ Health Check (مطلوب لـ Render Web Service)
# ----------------------------------------------------------------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # إخفاء سجلات الطلبات


def start_health_server() -> None:
    # Railway وغيره لا يحتاجون هذا السيرفر؛ يمكن تعطيله بـ DISABLE_HEALTH_SERVER=1
    if os.environ.get("DISABLE_HEALTH_SERVER") == "1":
        return
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server listening on port %s", port)


# ----------------------------------------------------------------------------
# نقطة الانطلاق
# ----------------------------------------------------------------------------
def main() -> None:
    if BOT_TOKEN == "PUT-YOUR-BOT-TOKEN-HERE" or not BOT_TOKEN:
        raise SystemExit(
            "❌ ضع توكن البوت في متغير البيئة BOT_TOKEN أو مباشرة داخل الكود قبل التشغيل."
        )
    if not ADMIN_IDS:
        logger.warning("⚠️ لم يتم تحديد أي ADMIN_IDS - لوحة التحكم لن تعمل لأي شخص.")

    start_health_server()

    app: Application = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))

    app.add_handler(CallbackQueryHandler(button_handler))

    # أي رسالة (نص/صورة/فيديو/صوت/ملف...) غير الأوامر
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_router))

    logger.info("🚀 البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
