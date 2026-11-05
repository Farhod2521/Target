# Google Ads — Frontend uchun API

Hammasi `Authorization` bilan (kabinet tokeni). Prefiks: `/api/v1`.
Xato shakli hamma joyda: `{"detail": "matn", "code": "kod", "problems"?: {maydon: matn}}`.
Pul (`Money`): `{"minor": 5000000, "currency": "UZS", "exponent": 2}` → `minor / 10^exponent`.

> Google Ads egasi uchun yoqilmagan bo'lsa, quyidagi API'lar `404` qaytaradi
> (faqat `GET /google/screen` — `{"screen": null}`). Menyuni ko'rsatish uchun:
> `GET /connections/cabinet` → `google_ads_nav: true|false`.

---

## 1. Ulanish — `/connections/google`

Bu bo'limda javoblar **snake_case**.

| Metod | Yo'l | Body | Javob |
|---|---|---|---|
| GET | `/connections/google` | — | Karta (pastda) |
| POST | `/connections/google/start` | `{"next": "/app/connections"}` | `{"url"}` → shu manzilga yo'naltiring |
| POST | `/connections/google/account` | `{"external_id"}` | `{"message"}` — ekranda shu akkaunt ko'rinadi |
| POST | `/connections/google/add` | `{"external_id"}` | `{"message"}` — akkauntni obunaga qo'shadi |
| POST | `/connections/google/refresh` | — | `{"message"}` — akkauntlar ro'yxatini Google'dan qayta o'qiydi |

Google ruxsatdan keyin `next` manziliga qaytaradi:
`?connected=google` (muvaffaqiyat) yoki `?error=<matn>` (xato — matnni ko'rsating).

**Karta (`GET /connections/google`):**

```json
{
  "google_ads_on": true,
  "connected": true,
  "connection": {...} | null,
  "accounts": [AdAccount],
  "subscribed": [{"account": AdAccount, "profile_id": "uuid" | null}],
  "others": [AdAccount],
  "slots": {"allowed": 1, "used": 1, "free": 0, "has_room": false},
  "loading": false,
  "taken": [...],
  "has_subscription": true
}
```

- `loading: true` — ulanish yangi, akkauntlar hali kelmagan: 2–3 soniyada qayta so'rang.
- `slots.has_room: false` bo'lsa «Qo'shish» o'rniga tarifga yo'naltiring.
- `AdAccount`: `id, external_id, name, currency, timezone, account_status, may_advertise, payment_due, is_active, is_current, cap_reached, synced_at`.

**Biznes profil** (har Google akkaunt uchun, reklama berishdan oldin to'liq bo'lishi kerak):
`GET /business/google/{account_id}` → forma, `PUT /business/google/{account_id}` → saqlash.
`account_id` — `AdAccount.id` (uuid).

---

## 2. Ekran — `/google` (camelCase)

### `GET /google/screen?period=today|7|30` (default `7`)

```json
{
  "screen": {
    "account": {"id", "name", "currency", "syncedAt"},
    "accounts": [{"id", "name", "currency"}],
    "period": "7",
    "totals": Figures,
    "anyPending": false,
    "campaigns": [{
      "id", "name",
      "delivery": "active|learning|pending|rejected|paused|finished",
      "pending": false,
      "dailyBudget": Money | null,
      "budgetHeld": false,
      "sharesWith": ["Boshqa kampaniya"],
      "figures": Figures,
      "rejectedAds": 0,
      "rejection": Refusal | null,
      "groups": [{
        "id", "name",
        "delivery": "... | paused_above",
        "pending": false,
        "figures": Figures,
        "rejectedAds": 0,
        "rejection": Refusal | null
      }]
    }]
  } | null
}
```

- `Figures`: `{spend: Money, impressions, clicks, results, costPerResult: Money | null}`.
- `screen: null` — Google Ads akkaunti yo'q → «Ulash» tugmasi.
- `pending` / `anyPending: true` — bosilgan amal Google'ga ketmoqda: 3–5 soniyada ekranni qayta o'qing.
- `budgetHeld: true` — «Byudjet yetmayapti» belgisi.
- `sharesWith` bo'sh emas — byudjet o'zgartirishda ogohlantiring: yangi summa shu kampaniyalarga ham tegadi.
- `paused_above` — guruh o'zi yoniq, lekin kampaniyasi to'xtatilgan.
- `rejection` (`Refusal`): `{title, cause, steps[], providerWords, fix: {label, url}}`.
  Google'da `key` doim `null` — `GET /refusals/answer` **chaqirilmaydi**.
  `fix.url` — Google Ads «Policy manager» havolasi.
  ⚠️ `rejectedAds`/`rejection` hali `main`da emas (feat/google-ads-local), tez orada qo'shiladi.

### Amallar (hammasi `{"message"}` qaytaradi — toast qilib ko'rsating, so'ng ekranni qayta o'qing)

| Yo'l | Body |
|---|---|
| POST `/google/switch` | `{"level": "campaign" \| "adset", "id", "wanted": "pause" \| "resume"}` |
| POST `/google/budget` | `{"id": "<kampaniya>", "budget": Money}` — faqat kampaniya darajasida |
| POST `/google/delete` | `{"id": "<kampaniya>"}` — butunlay o'chiradi, oldin tasdiq so'rang |
| POST `/google/refresh` | — |
| POST `/google/account` | `{"id": "<external id>"}` — ekrandagi akkauntni almashtirish |

---

## 3. Reklama berish (Search) — Meta bilan bir xil draft API

Google draft Meta draft bilan **bir xil** `LaunchDraft` shaklini qaytaradi; farqi — `flow: "google"`, `networkId: "google"` va `google` maydoni to'ldirilgan.

| Qadam | So'rov |
|---|---|
| Ochish | `POST /launch/drafts` `{"flow": "google"}` → `LaunchDraft` |
| O'qish | `GET /launch/drafts/{id}` |
| 1. Javoblar (`step: "plan"`) | `PATCH /launch/drafts/{id}` — `goal`, `linkUrl`, `phone`, `areas`, `dailyBudget` |
| Hududlar ro'yxati | `GET /launch/drafts/{id}/areas` → `[{key, name, parent}]` |
| «Davom etish» | `PATCH` `{"step": "words"}` — javoblar yuboriladi, AI so'z va matn yozadi |
| 2. So'zlar (`step: "words"`) | `PUT /launch/drafts/{id}/google` — body pastda |
| 3. Ko'rib chiqish | `step: "review"`, `proposal` to'ldiriladi |
| «Yaratish» | `POST /launch/drafts/{id}/create` |
| «Qayta urinish» | `POST /launch/drafts/{id}/retry` |
| Bekor qilish | `POST /launch/drafts/{id}/discard` (204) |

**Javoblar qadami:**
- `goal`: faqat `"click"` (saytga kirish) yoki `"call"` (qo'ng'iroq).
- `linkUrl` — majburiy, `https://` bilan.
- `phone` — `call` uchun majburiy, `+998901234567` shaklida, saytda ham bo'lishi kerak.
- `areas` — ≤ 10 ta `key`; bo'sh = butun mamlakat.
- `dailyBudget` — `Money`, > 0.
- Javoblar `PATCH` qilingan sari saqlanib turadi, Google'ga faqat `step` bilan ketadi.
  Xato bo'lsa `422`, `problems` kaliti: `goal | linkUrl | phone | areas | budget`.

**`status` bo'yicha ekran:**

| `status` | Ko'rsatish |
|---|---|
| `draft` | Joriy `step` |
| `building` | AI yozmoqda — loader, 2–3 soniyada `GET` qiling |
| `ready` | Ko'rib chiqish, «Yaratish» |
| `creating` | Yaratilmoqda — `creation` progress, polling |
| `sent` | Tayyor, Google ko'rib chiqmoqda (`reviewEta: "hours"`) |
| `failed` | `failure.title` / `failure.text`, tugma `failure.fix` (`to: "words"`) + «Qayta urinish» |

**`google` maydoni** (so'zlar qadami, `null` — AI hali yozmagan):

```json
{
  "say": "",
  "keywords": [{"text": "plastik oyna", "volume": 1200}],
  "minus": ["bepul"],
  "headlines": ["..."],
  "descriptions": ["..."],
  "url": "https://...",
  "urlCheck": null,
  "paths": ["oyna", "narx"],
  "places": ["Toshkent"]
}
```

**`PUT /launch/drafts/{id}/google`** — xuddi shu shaklni **to'liq** yuboring (hamma maydon majburiy). Cheklovlar:

| Maydon | Qoida |
|---|---|
| `keywords` | 1–20 ta, har biri ≤ 80 belgi, ≤ 10 so'z |
| `minus` | 0–15 ta |
| `headlines` | 3–15 ta, har biri ≤ 30 belgi |
| `descriptions` | 2–4 ta, har biri ≤ 90 belgi |
| `paths` | 2 ta, har biri ≤ 15 belgi (bo'sh bo'lishi mumkin) |
| `url` | o'zgarsa sayt yangilanadi; xato → `problems.url` |

Javob — yangilangan `LaunchDraft`, `step: "review"`.
Xato: `400`, `code: "google_words_invalid"`, `detail` — foydalanuvchiga ko'rsatiladigan matn.

**Xato kodlari (`code`)**: `google_website_required`, `google_phone_required`,
`google_places_too_many`, `google_goal_unknown`, `google_budget_required`,
`google_words_invalid`, `google_launch_closed` (allaqachon yaratilmoqda),
`google_launch_not_ready` (AI hali yozmoqda — kuting).
Hamma holatda `detail`ni foydalanuvchiga to'g'ridan-to'g'ri ko'rsatish mumkin.

---

## Muhim

- Hozircha faqat **Search** kampaniya (rasm/video yo'q).
- Google'da byudjet faqat kampaniyada; guruhga byudjet tugmasi qo'ymang.
- Chat, lid forma, Instagram, media qadami Google'da yo'q — `flow: "google"` bo'lsa bu qadamlarni yashiring.
