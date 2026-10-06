# رفع البوت على Render + قاعدة بيانات دائمة

## 1) أنشئ قاعدة بيانات مجانية (PostgreSQL)
اختر واحد من هذي (أنصح بـ Neon أو Supabase لأن قاعدة Render المجانية تنتهي بعد فترة):
- **Neon**: https://neon.tech ← Create project ← انسخ **Connection string**.
- **Supabase**: https://supabase.com ← New project ← Project Settings ← Database ← Connection string (URI).

الرابط يكون بهذا الشكل:
`postgresql://user:password@host/dbname?sslmode=require`

البوت ينشئ الجدول بنفسه، ما تحتاج تسوي شي يدوي.

## 2) ارفع الملفات على GitHub (Private)
`bot.py` ، `requirements.txt` ، `render.yaml` ، `.gitignore`

## 3) أنشئ الخدمة على Render
New ← Blueprint ← اختر المستودع (أو Web Service يدوياً بالأمر `python bot.py`).

## 4) المتغيرات (Environment Variables)
| الاسم | القيمة |
|---|---|
| `BOT_TOKEN` | توكن البوت من @BotFather |
| `ADMIN_IDS` | آيديك (أكثر من واحد مفصولين بفاصلة) |
| `DATABASE_URL` | رابط قاعدة البيانات من الخطوة 1 |
| `PYTHON_VERSION` | `3.12.3` |

عند نجاح الاتصال بالقاعدة، المستخدمين والمحظورين والإعدادات والإحصائيات كلها تنحفظ فيها وما تضيع عند إعادة التشغيل.
إذا ما ضفت `DATABASE_URL` يرجع البوت يستخدم `data.json` (بيانات مؤقتة).

## 5) أبقِ البوت صاحي (الخطة المجانية)
الخدمة تنام بعد 15 دقيقة بدون زيارات. أضف رابط الخدمة في
[UptimeRobot](https://uptimerobot.com) أو [cron-job.org](https://cron-job.org) كل 5 دقائق.
