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
| ads | Kampaniya yaratish (launch), boshqaruv, kreativ, geo | 62.1k | 14 | ⏳ eng katta |
| leads | Lidlar, Meta webhook, formalar, eksport | 9.5k | 4 | ✅ selectors, services, tasks, router `/leads`, webhook `/webhooks/meta/leads/` |
| destinations | Lidlarni Google Sheets'ga yozish | 3.8k | 3 | ⏳ |
| metrics | Dashboard raqamlari, CRM paneli | 16.0k | 4 | ⏳ |
| agent | AI agent: tahlil va takliflar | 11.9k | 5 | ⏳ |
| chat | AI yordamchi chat | 11.4k | 3 | ⏳ |
| notifications | Telegram bot, xabarlar, hisobotlar | 13.6k | 4 | ⏳ |
| miniapp | Telegram Mini App kirishi | 0.8k | 0 | ⏳ |
| onboarding | Boshlash qadamlari | 0.9k | 0 | ⏳ |
| public | Bosh sahifa: maslahat arizasi, o'chirish so'rovi, sharhlar | 2.1k | 3 | ✅ selectors, services, router `/public`, `/data-deletion/callback/` |
| surveys | Haftalik/oylik so'rovnomalar | 1.7k | 3 | ⏳ |
| supportchat | Mijoz va ofis o'rtasidagi chat | 3.5k | 4 | ⏳ |
| backoffice | Ofis (xodimlar paneli) | 10.8k | 1 | 🟡 permissions, journal (record/seen); qolgan ekranlar ⏳ |
| crm | Mijozning o'z CRM doskasi (menejerlar, ustunlar) | 4.6k | 6 | ✅ selectors, services, tasks, router `/crm` |
| sales | Sotuv doskasi (xodimlar) | 5.4k | 9 | ✅ selectors, services, tasks, router `/office/sales` |
| content_studio | Video montaj (`D:\TARGET\FASTAPI\Content_Studio` dan qo'shiladi) | 7.1k | 2 | ⏳ |

Barcha 89 model allaqachon SQLAlchemy'da (`app/modules/*/models/`), ya'ni
baza qatlami to'liq. ⏳ — servis va endpointlari hali ko'chirilmagan.

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
