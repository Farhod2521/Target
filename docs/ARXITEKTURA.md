# TargetologAI backend — FastAPI

Django loyihasining (`targetolog-ai`) backend qismi FastAPI'ga ko'chirilmoqda.
Frontend (Next.js) shu API orqali ishlaydi. Baza — o'sha PostgreSQL, jadvallar
nomi va ustunlari Django'dagidek, shuning uchun mavjud bazani shunchaki ulash
mumkin.

Graf xaritasi: `docs/arxitektura-grafi.html` (brauzerda oching) va
`docs/GRAPH_REPORT.md` — graphify bilan Django kodidan qurilgan
(1745 fayl, 23 126 tugun, 441 jamoa).

## Tuzilma

```
targetolog_backend/
├── app/
│   ├── main.py            FastAPI ilova, xatolar, CORS
│   ├── models.py          barcha jadvallar (Alembic uchun)
│   ├── api/               /api/v1 router, deps (sessiya, joriy foydalanuvchi)
│   ├── common/            config, db, crypto, parol, JWT, hooks, xatolar
│   └── modules/<modul>/
│       ├── models/        bitta fayl = bitta jadval (Django'dan generatsiya)
│       ├── constants.py   enumlar
│       ├── exceptions.py
│       ├── schemas/       kiruvchi/chiquvchi JSON
│       ├── selectors/     o'qish
│       ├── services/      yozish, bitta fayl = bitta amal
│       ├── routers/       endpointlar
│       └── tasks.py       Celery
├── core/                  domen logikasi, Django'siz (o'zgarishsiz ko'chgan)
├── packages/              metaads, llmkit, videokit, ... (o'zgarishsiz)
├── migrations/            Alembic
├── tools/                 gen_models.py, port_constants.py, django_schema.json
└── tests/
```

Qatlamlar: `routers → services/selectors → core → packages`. `core` va
`packages` FastAPI ham, SQLAlchemy ham bilmaydi.

Modullar bir-birini import qilmasdan ham ta'sir qila oladi:
`app/common/hooks.py` — `fire("accounts.user_registered", ...)` va
`@on("accounts.user_registered")`.

## Modullar

| Modul | Vazifasi | Django hajmi | Modellar | Holat |
|---|---|---|---|---|
| accounts | Ro'yxatdan o'tish, kirish (JWT), profil, parol, til | 3.3k qator | 1 | ✅ API, block_user, purge, handoff, CRM member login |
| audit | Hodisalar (outbox), ActionLog, LLM xarajati, xatolar | 2.8k | 4 | ✅ selectors, services, tasks |
| referrals | Taklif kodi, mukofot, hamyon, pul yechish, fikr | 4.0k | 8 | ✅ selectors, services, router `/referrals`, `/r/{code}/` |
| integrations | Meta ulash (OAuth), reklama akkauntlari, sahifalar | 16.9k | 7 | ✅ selectors, services, tasks, router `/connections` (DRF staff konsoli qolgan) |
| businesses | Biznes profili, kategoriya | 2.0k | 3 | ✅ selectors, services, router `/business` |
| billing | Tarif, obuna, to'lov (Payme/Click/Paynet) | 12.1k | 7 | ✅ selectors, services, tasks, router `/billing`, webhook `/webhooks/pay/{provider}` |
| ads | Kampaniya yaratish (launch), boshqaruv, kreativ, geo | 62.1k | 15 | ✅ selectors, mirror/media sinxron, boshqaruv, o'chirish, lapse, yetkazib berish to'xtashlari (`DeliveryStop`), tasks; router `/campaigns` (ro'yxat, tafsilot, sinxron, pauza/yoqish/budjet/qaytarish/o'chirish), `/launch` (yangi reklama ustasi: reja, rasmlar, taklif, yaratish, lid forma), `/google` (Google Ads ekrani va Search ustasi); Django admin va boshqaruv buyruqlari ⏳ |
| leads | Lidlar, Meta webhook, formalar, eksport | 9.5k | 4 | ✅ selectors, services, tasks, router `/leads`, webhook `/webhooks/meta/leads/` |
| destinations | Lidlarni Google Sheets'ga yozish | 3.8k | 3 | ✅ selectors, services, tasks (6), `schedule.py` (har daqiqa yozish, 04:35 tekshirish), router `/destinations` (panel, Google OAuth, rejim, picker, uzish, qayta yaratish) |
| metrics | Dashboard raqamlari, CRM paneli | 16.0k | 4 | ✅ sinxron (tungi/bugungi/kuzatilgan), saqlash, segmentlar, lid tafovuti, dashboard, kampaniya paneli, kreativ hisobot, tasks, router `/metrics` `/metrics/numbers` javobida `setup` (sozlash bloki) |
| agent | AI agent: tahlil va takliflar | 11.9k | 5 | ✅ selectors (takliflar, kartalar, tungi dalillar, haftalik chastota, kuzatuv, o'zi to'xtatish nomzodlari, strategiya, baholar), services (tungi o'tish `run_agent`, Claude ko'rigi, rad etilgan reklamaga yangi matn, takliflarni saqlash/eskirtirish, o'zi tuzatish, natijani baholash, tashxis, nosozlikka taklif, natijasiz guruhni to'xtatish, chastota darajalari, kuzatuv tugmalari), tasks, router `/agent` |
| chat | AI yordamchi chat | 11.4k | 3 | ✅ selectors (kontekst, 14 ta lookup, kunlik/haftalik hisobot), services (savol, javob oqimi, rad etish izohi, hisobot izohi), tasks, router `/chat` (ekran, `/ask`, SSE `/stream/{turn_id}`, `/report`, `/choices/{pk}`); kutish ro'yxati (inbox) — notifications `/actions` |
| notifications | Telegram bot, xabarlar, hisobotlar | 13.6k | 4 | 🟡 bot ulash, sozlamalar, referal/pul yechish/fikr xabarlari, amallar ekrani va qo'ng'iroqcha (router `/actions`, 28 turdan 28 tasi); bot dialogi, hisobotlar, Telegram xabarlari ⏳ |
| miniapp | Telegram Mini App kirishi | 0.8k | 0 | ✅ router `/miniapp` |
| onboarding | Boshlash qadamlari | 0.9k | 0 | ✅ selectors (tayyorlik, sahifa tanlash, `setup_overview`), `finish_setup`, router `/start` (ekran + poll, `/finish`, `/gate` — Django middleware o'rniga) |
| public | Bosh sahifa: maslahat arizasi, o'chirish so'rovi, sharhlar | 2.1k | 3 | ✅ selectors, services, router `/public`, `/data-deletion/callback/` |
| surveys | Haftalik/oylik so'rovnomalar | 1.7k | 3 | 🟡 mijoz tomoni: router `/surveys` (`/due`, `/answer`, `/later`); ofis tomoni (yaratish, tarjima) va Telegram orqali yuborish ⏳ |
| supportchat | Mijoz va ofis o'rtasidagi chat | 3.5k | 4 | 🟡 mijoz tomoni: router `/support` (ekran, xabar/fayl, tahrir, o'chirish, poll), WebSocket `/support/ws` (Redis pub/sub); ofis servislari bor, ofis endpointlari va Telegram xabarlari ⏳ |
| backoffice | Ofis (xodimlar paneli) | 10.8k | 1 | 🟡 permissions, journal (record/seen); qolgan ekranlar ⏳ |
| crm | Mijozning o'z CRM doskasi (menejerlar, ustunlar) | 4.6k | 6 | ✅ selectors, services, tasks, router `/crm`; har bir sahifa + reklama akkaunti juftligi alohida CRM (`?pair=`), menejer bitta juftlikda, har sahifaga 1 bepul o'rin; Django'dagi bitta CRM 0006 migratsiyasida juftliklarga taqsimlanadi (`app/modules/crm/backfill.py`). O'rin sotib olish, sifatli lidlarni Meta'ga yuborish, jamoa statistikasi ⏳ |
| sales | Sotuv doskasi (xodimlar) | 5.4k | 9 | ✅ selectors, services, tasks, router `/office/sales` |
| content_studio | Video montaj (`D:\TARGET\FASTAPI\Content_Studio` dan qo'shiladi) | 7.1k | 2 | ⏳ |

Barcha 89 model allaqachon SQLAlchemy'da (`app/modules/*/models/`), ya'ni
baza qatlami to'liq. ⏳ — servis va endpointlari hali ko'chirilmagan.

## Yangi reklama, Google Ads va agent API

Hammasi `/api/v1` ostida; provayder va Claude faqat worker'da chaqiriladi,
endpoint navbatga qo'yadi va javob beradi, natijani so'rov (poll) o'qiydi.
Maydon bo'yicha rad etish — `422`, `{"detail", "code": "invalid_input",
"problems": {"maydon": "sabab"}}`.

| Yo'l | Vazifasi |
|---|---|
| `POST /launch` | Tayyorlashni ochish (ochiq bo'lsa — o'shani qaytaradi) |
| `GET/POST /launch/{id}/plan` | 1-qadam: maqsad, kunlik byudjet, manzil, boshlanish kuni |
| `GET/POST /launch/{id}/plan/goal`, `/plan/chat-questions` | Maqsadni so'z bilan o'qish, chat savollari (poll `tries`) |
| `GET/POST /launch/{id}/media`, `/media/upload`, `/media/upload/chunk`, `/media/upload/finish`, `/media/status`, `/media/text` | 2-qadam: rasm/video, kutubxona, matnlar |
| `GET /launch/{id}/review`, `/review/state` | Taklif ekrani va uning holati (poll) |
| `POST /launch/{id}/edit` | Taklifni tahrirlash (PATCH) — yuborilmagan bo'lim yoki maydon o'zgarmaydi, `null` tozalaydi; hamma bo'lim bir yo'la yoki hech biri |
| `POST /launch/{id}/create`, `/start`, `/retry`, `/discard`, `/clean-up` | Yaratish (pul sarflaydi), yoqish, qayta urinish, bekor qilish, tozalash |
| `GET/POST /launch/{id}/form`, `/form/auto`, `/form/new`, `/form/refresh`, `/form-depth/{depth}` | Lid forma tanlash va savollar chuqurligi |
| `GET /google`, `POST /google/switch`, `/budget`, `/delete`, `/refresh` | Google Ads ekrani va bosishlar |
| `POST /google/launch`, `GET/POST /google/launch/{id}/answers`, `/words`, `GET /review`, `POST /create` | Google Search ustasi |
| `GET /agent` | Kutilayotgan takliflar, kuzatuv qatorlari, chastota, bugun pul kuydirayotgan guruhlar |
| `POST /agent/{id}/approve`, `/reject`, `GET/POST /agent/{id}/new-ad` | Taklifga javob, rad etilgan reklamaning yangi matni |
| `GET /agent/history`, `GET/PUT /agent/settings`, `GET /agent/verdicts` | Tarix, sozlamalar, kampaniya ro'yxatidagi baholar |
| `POST /agent/watch/{adset_id}/{move}`, `/agent/frequency/{id}/fine`, `GET /agent/frequency/{id}/creative` | Kuzatuv va chastota tugmalari |

Davriy vazifalar har modulning `schedule.py` faylidagi `SCHEDULE` ro'yxatida
turadi; `app.worker` ularni yig'adi va RedBeat (Redis) orqali yuboradi.
Django'da `django-celery-beat` (Postgres) edi — vaqtlar uning
`seed_schedules` buyrug'idan o'zgarishsiz olinadi, hammasi UTC.

- ✅ 42 ta vazifa: ads 8, leads 8, agent 6, integrations 5, metrics 4, audit 2,
  chat 2, billing 2, sales 2, destinations 2, crm 1 (har modulning `schedule.py` fayli)
- ⏳ 10 tasi vazifa kodi ko'chirilgach qo'shiladi: notifications 8 (xabarlar,
  kunlik/haftalik hisobot, chastota, obuna tugashi, nosozlik, so'rovnoma),
  montaj 1, crm `sweep_quality_task` 1

Beat `compose.yaml`da `beat` profili ortida: eski Django o'chirilgandan keyin
`docker compose --profile beat up -d beat` bilan yoqiladi. Ikkala beat bir
vaqtda ishlasa, bir xil reklama akkauntlari ikki marta sinxronlanadi va
to'xtatiladi.

## Ko'chirish tartibi

Grafdagi bog'liqliklar bo'yicha — har bosqich o'zidan oldingilarga tayanadi:

1. **Poydevor** ✅ — config, baza, 89 model, Alembic, crypto, parol, JWT
2. **accounts + audit** ✅ (audit qolgan qismi bilan keyingi bosqichlarda)
3. **integrations + businesses** — Meta ulash, akkaunt, sahifa
4. **billing + referrals** — obuna va to'lov
5. **ads** — kampaniya yaratish va boshqarish
6. **leads + destinations + metrics** — lidlar, Sheets, dashboard, CRM
7. **agent + chat + notifications + miniapp**
8. **public + onboarding + surveys + supportchat**
9. **backoffice + sales** — xodimlar paneli
10. **content_studio** — montaj
11. **API hujjati (DOCX)** — har endpoint, JSON namunalar bilan

## Baza

Mavjud Django bazasiga ulash:

```bash
cp .env.example .env          # DATABASE_URL, ENCRYPTION_KEY — Django'dagi qiymatlar
uv run alembic stamp 0001     # jadvallar bor: faqat belgilab qo'yadi
```

`ENCRYPTION_KEY` Django'dagi bilan bir xil bo'lishi shart — Meta tokenlari
shu kalit bilan shifrlangan. Parollar Django formatida (`pbkdf2_sha256`) —
foydalanuvchilar eski parol bilan kiradi.

Yangi bo'sh baza: `uv run alembic upgrade head`.

## Ishga tushirish

```bash
uv sync
uv run uvicorn app.main:app --reload     # http://localhost:8000/docs
uv run pytest                            # testlar
uv run ruff check . && uv run ruff format .
```

## Asboblar

- `tools/gen_models.py` — Django sxemasidan modellarni qayta generatsiya qiladi
  (`tools/django_schema.json`). Django modeli o'zgarsa: sxemani qayta oling va
  shu skriptni ishga tushiring.
- `tools/port_constants.py` — Django `constants.py` ni enumlarga o'giradi.
