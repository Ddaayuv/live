# تشغيل البوت على Railway

## 1) جهّز التوكن والآيدي
- التوكن: من [@BotFather](https://t.me/BotFather) بالأمر `/newbot`.
- آيديك: من [@userinfobot](https://t.me/userinfobot).

## 2) ارفع الملفات على GitHub (Private)
ارفع كل الملفات: `bot.py` ، `requirements.txt` ، `railway.toml` ، `.python-version` ، `Procfile` ، `.gitignore`

## 3) أنشئ المشروع
1. افتح https://railway.com وسجّل بحساب GitHub.
2. **New Project ← Deploy from GitHub repo** ← اختر المستودع.

## 4) قاعدة البيانات (اختر واحد)
**أ) قاعدة Railway نفسها (الأسهل):**
- داخل المشروع: **New ← Database ← Add PostgreSQL**.
- في خدمة البوت ← **Variables ← New Variable**:
  - الاسم: `DATABASE_URL`
  - القيمة: `${{Postgres.DATABASE_URL}}`

**ب) قاعدة خارجية (Neon / Supabase):** ضع الرابط مباشرة في `DATABASE_URL`.

## 5) باقي المتغيرات (Variables)
| الاسم | القيمة |
|---|---|
| `BOT_TOKEN` | توكن البوت |
| `ADMIN_IDS` | آيديك (أكثر من واحد مفصولين بفاصلة) |
| `DATABASE_URL` | من الخطوة 4 |

بعد إضافة المتغيرات يعيد Railway النشر تلقائياً.

## 6) تأكد أنه شغال
**Deployments ← View Logs** ويجب أن تشوف: `🚀 البوت يعمل الآن...`
ثم جرّب `/start` و `/admin` في تليجرام.

## ملاحظات
- Railway لا ينيّم الخدمة، فلا تحتاج UptimeRobot ولا Generate Domain.
- لا تحذف `DATABASE_URL`، لأن ملفات Railway مؤقتة وبدونه تضيع البيانات.
- اتبع صفحة **Usage** لمتابعة الرصيد والتكلفة.
- المشاكل الشائعة: توكن خاطئ ← `Unauthorized` في اللوغ. نسيان `ADMIN_IDS` ← لوحة `/admin` ما تفتح.
