# Frontend integratsiyasi

TargetologAI backend (FastAPI) bilan ishlash uchun umumiy qo'llanma.
Batafsil hujjatlar:

- [DASHBOARD_API.md](DASHBOARD_API.md) — asosiy sahifa raqamlari
- [CRM_API.md](CRM_API.md) — CRM doskasi va sozlamalari
- [RAHMAT_TOLOV.md](RAHMAT_TOLOV.md) — Rahmat (Multicard) orqali to'lov

To'liq va jonli ro'yxat: `https://<api-host>/docs` (Swagger) va
`/openapi.json` — undan TypeScript tiplarini generatsiya qilsa bo'ladi
(`openapi-typescript`).

---

## 1. Asosiy qoidalar

| Narsa | Qiymat |
|---|---|
| Prefiks | Hamma endpoint `/api/v1` ostida (webhooklardan tashqari) |
| Format | JSON so'rov va javob |
| Avtorizatsiya | `Authorization: Bearer <access_token>` |
| Sanalar | ISO 8601, UTC (`2026-10-28T09:12:00Z`) |
| Pul | `*_minor` — butun son, tiyin/sentda. Tayyor matn (`spend`, `cpl`, `display`) server formatlaydi |
| Til | Javob matnlari foydalanuvchi tilida (`uz`, `ru`, `en`) — `PUT /account/language` |
| CORS | `targetolog.ai` ruxsat etilgan. Yangi domen backend sozlamasidagi `cors_allowed_origins` ro'yxatiga qo'shiladi |

**Bitta domen.** Backend o'zi yasaydigan havolalarda (Meta OAuth callback,
`/r/{code}/`, to'lovdan qaytish) bitta `SITE_URL` ishlatadi. Shuning uchun
frontend va backend bitta domen ostida turadi: proxy `/api/`, `/webhooks/`,
`/r/`, `/data-deletion/callback/` yo'llarini backendga, qolganini frontendga
yuboradi.

Server matnlari (`detail`, `message`, `label`, `hint`) **foydalanuvchiga
o'zgarishsiz ko'rsatiladi** — frontend ularni tarjima qilmaydi.

---

## 2. Avtorizatsiya

### Ro'yxatdan o'tish

```http
POST /api/v1/auth/signup
{
  "email": "ali@example.com",
  "full_name": "Ali Valiyev",
  "password": "kamida8belgi",
  "phone": "+998901234567",
  "language": "uz",
  "referral_code": ""
}
```

`201` → `{"user": {...}, "access_token", "refresh_token", "token_type"}`.
Akkaunt darhol ochiladi va foydalanuvchi tizimga kirgan bo'ladi — kod
kutilmaydi. `user.email_verified_at` hali `null`.

Bitta IP'dan soatiga 20 tadan ko'p signup → `429`.

Referal havola `/r/{code}/` orqali kelgan bo'lsa, `referral_code`ni
yuboring.

### Emailni tasdiqlash (ixtiyoriy)

Foydalanuvchi o'zi xohlasa, profilidan emailini tasdiqlaydi. Ikkalasi ham
`Authorization: Bearer` talab qiladi.

```http
POST /api/v1/account/email/code
```

`202` → `{"email", "expires_in", "resend_in", "message"}`. Emailga 5 xonali
kod ketadi, **3 daqiqa** amal qiladi. Qayta so'rash — `resend_in` soniya
o'tgach (`429 resend_too_soon`), soatiga ko'pi bilan 5 ta (`429 too_many_codes`).

```http
POST /api/v1/account/email/verify
{"code": "12345"}
```

`200` → yangilangan `user` (`email_verified_at` to'ldirilgan). Xatolar:
`code_wrong` (qolgan urinishlar `detail`da), `code_tries_spent`,
`code_expired`. Allaqachon tasdiqlangan bo'lsa → `409 email_already_verified`.

### Kirish

```http
POST /api/v1/auth/login
{"email": "...", "password": "..."}
```

→ `{"access_token", "refresh_token", "token_type": "bearer"}`

### Tokenlar

| Token | Muddat |
|---|---|
| `access_token` | 60 daqiqa |
| `refresh_token` | 30 kun |

`401` kelsa:

```http
POST /api/v1/auth/refresh
{"refresh_token": "..."}
```

→ yangi juftlik. Bu ham `401` bersa — login sahifasiga.

Chiqish (`logout`) endpointi yo'q: tokenlarni frontend o'chiradi.

### CRM menejeri

Menejer ham `POST /auth/login` bilan kiradi, lekin unga **faqat**
`/crm`, `/auth` va `/account/language` ochiq. Boshqa hamma joyda
`403 {"detail": "Faqat CRM doskasi."}`. Menejer ekanini `GET /crm/nav` yoki
istalgan boshqa endpointdan kelgan `403`dan bilish mumkin. Batafsil:
[CRM_API.md](CRM_API.md).

---

## 3. Xatolar

### Biznes qoidasi buzilganda

```json
{"detail": "Bu lidni boshqa menejer oldi.", "code": "already_taken"}
```

| Status | Ma'nosi |
|---|---|
| `400` | Qoida buzildi — `detail`ni ko'rsating, `code` bo'yicha tarmoqlang |
| `401` | Token yo'q/eskirgan → refresh |
| `403` | Ruxsat yo'q (`not_allowed`) |
| `404` | Topilmadi yoki boshqa foydalanuvchiniki |
| `409` | Holat to'g'ri kelmaydi (`conflict`) |
| `422` | Maydon xatosi (pastda) |
| `429` | Juda ko'p urinish |

`code` — har rad etishning o'z nomi (`trial_limit_reached`,
`no_entitlement`, ...). UI shunga qarab qaror qiladi (tariflarga yuborish,
profilga yuborish, maydon yonida ko'rsatish).

Ba'zi javoblarda qo'shimcha: `problems` (maydon → sabab) va `hints`.

### Maydon xatolari (`422`)

Ikki xil shakl bor:

1. Biznes tekshiruvi (ads ustasi va boshqalar):

   ```json
   {
     "detail": "...",
     "code": "invalid_input",
     "problems": {"daily_budget": "..."}
   }
   ```

   `problems` kalitlari — so'rovdagi maydon nomlari; xatoni o'sha maydon
   yonida ko'rsating.

2. FastAPI'ning o'z tekshiruvi (tur, uzunlik, majburiy maydon):

   ```json
   {"detail": [{"loc": ["body", "email"], "msg": "...", "type": "value_error"}]}
   ```

`detail` massiv bo'lsa — 2-shakl, matn bo'lsa — 1-shakl.

---

## 4. Uzoq ishlar: so'rab turish (polling)

Meta va Claude so'rovlari endpointda kutilmaydi — worker'da bajariladi.
Endpoint ishni navbatga qo'yadi va darhol javob beradi, natija so'rab
turish orqali olinadi. Hammasida bir xil naqsh:

```text
POST ...           → { ..., "tries": 0, "poll_seconds": 3 }
loop har poll_seconds:
    GET ...?tries=<oxirgi tries>
    polling/syncing == false → tugadi
    gave_up == true          → "kechikmoqda" deb yozing, to'xtating
```

Qayerlarda:

| Ish | Boshlash | So'rash |
|---|---|---|
| Dashboard yangilash | `POST /metrics/numbers/refresh` | `GET /metrics/numbers/poll` |
| Kampaniya bugungi raqamlari | `POST /metrics/campaigns/{id}/today` | `GET /metrics/campaigns/{id}/today` |
| Kampaniyalar sinxroni | `POST /campaigns/sync` | `GET /campaigns/poll` |
| Reklama ustasi: maqsad, savollar | `POST /launch/{id}/plan/goal` | `GET` xuddi shu |
| Reklama ustasi: taklif | `GET /launch/{id}/review` | `GET /launch/{id}/review/state` |
| Media yuklash | `POST /launch/{id}/media/upload/finish` | `GET /launch/{id}/media/status` |
| AI chat | `POST /chat/ask` | `GET /chat/stream/{turn_id}` (SSE) |
| To'lov | `POST /billing/checkout` | `GET /billing/invoice/{number}` |
| CRM doskasi | — | `GET /crm/pulse?cursor=` (`204` = o'zgarmagan) |

---

## 5. Modullar va endpointlar

### Akkaunt — `/account`

| Endpoint | Vazifasi |
|---|---|
| `GET /account` | Profil |
| `PUT /account` | Ism va telefon |
| `PUT /account/phone` | Faqat telefon |
| `PUT /account/password` | `{"current_password", "new_password"}` |
| `PUT /account/language` | `{"language": "uz"\|"ru"\|"en"}` |

### Biznes — `/business`

`GET/PUT /business`, `GET /business/choices`,
`GET/PUT /business/pages/{page_id}`, `GET/PUT /business/google/{account_id}`

### Ulanishlar — `/connections`

| Guruh | Endpointlar |
|---|---|
| Ekran | `GET /connections`, `GET /connections/cabinet`, `GET /connections/pages` |
| Meta OAuth | `POST /connections/meta/start {"next": "<qaytish yo'li>"}` → `{"url"}`, brauzerni shu `url`ga yo'naltiring. Meta backenddagi `/connections/meta/callback`ga qaytaradi, u `next`ga yuboradi |
| Meta tanlash | `POST /meta/ad-account`, `/meta/page`, `/meta/page/account`, `/meta/page/pair`, `/meta/add/page`, `/meta/instagram`, `/meta/pixel` |
| Almashtirish | `POST /meta/switch/ad-account`, `/meta/switch/page`, `/meta/switch/pair` |
| Boshqa | `POST /meta/refresh`, `/meta/disconnect`, `/meta/confirmed`, `/meta/leads/recheck`, `/meta/pages/{page_id}/leads` |
| Instagram profil | `GET /meta/instagram/profile`, `POST .../refresh` |
| Google | `GET /connections/google`, `POST /google/start`, `/google/account`, `/google/add`, `/google/refresh` |
| Auditoriyalar | `GET /audiences`, `GET /audiences/rows`, `POST /audiences`, `/audiences/rule`, `/audiences/lookalike`, `/audiences/{pk}/fill`, `DELETE /audiences/{pk}` |

### Kampaniyalar — `/campaigns`

| Endpoint | Vazifasi |
|---|---|
| `GET /campaigns` | Ro'yxat |
| `POST /campaigns/sync`, `GET /campaigns/poll` | Meta'dan yangilash |
| `GET /campaigns/{id}` | Tafsilot |
| `GET /campaigns/{id}/ads` | Reklamalar |
| `GET /campaigns/{id}/history` | O'zgarishlar tarixi |
| `GET/POST /campaigns/{id}/edit` | Sozlamalarni tahrirlash |
| `POST /campaigns/{id}/delete` | O'chirish |
| `POST /campaigns/manage/{level}/{external_id}/pause\|resume\|revert` | `level`: `campaign`, `adset`, `ad` |
| `GET/POST /campaigns/manage/{level}/{external_id}/budget` | Byudjet |
| `GET /campaigns/manage/{level}/{external_id}/state` | Amal holati (poll) |
| `GET /campaigns/manage/ad/{external_id}/preview` | Reklamani oldindan ko'rish |
| `GET/POST /campaigns/manage/ad/{external_id}/edit` | Reklama matni |
| `POST /campaigns/manage/ad\|adset/{external_id}/delete` | O'chirish |

### Yangi reklama ustasi — `/launch`

| Qadam | Endpointlar |
|---|---|
| Ochish | `POST /launch` (ochiq tayyorlash bo'lsa — o'shani qaytaradi), `GET /launch/{id}` |
| 1. Reja | `GET/POST /launch/{id}/plan`, `GET/POST .../plan/goal`, `GET/POST .../plan/chat-questions` |
| 2. Media | `GET/POST .../media`, `POST .../media/upload`, `.../media/upload/chunk`, `.../media/upload/finish`, `GET .../media/status`, `POST .../media/text`, `.../media/refresh`, `.../media/{position}/remove`, `.../media/{asset_id}/delete`, `GET .../media/{asset_id}/preview`, `GET .../media/{position}/file` |
| 3. Taklif | `GET .../review`, `GET .../review/state`, `POST .../edit` (PATCH: yuborilmagan maydon o'zgarmaydi, `null` tozalaydi), `POST .../name`, `.../budget/fit`, `.../ads/trim`, `.../ads/{position}/remove`, `.../regenerate/{section}` |
| Lid forma | `GET/POST .../form`, `POST .../form/auto`, `.../form/new`, `.../form/refresh`, `.../forms/refresh`, `GET/POST .../form-depth/{depth}` |
| Yakun | `POST .../create` (pul sarflaydi), `.../start`, `.../retry`, `.../discard`, `.../clean-up` |

### Reklama joyi — `/launch/drafts/{id}` (faqat Meta)

Google draft bu API'lardan 404 oladi: Google'ning joylari alohida (`GET .../areas`).

**Qidiruv:** `GET /launch/drafts/{id}/locations?q=&country=`

- `q` 2 belgidan qisqa bo'lsa `[]` qaytadi va Meta'ga so'rov ketmaydi.
- `country` (ISO-2, ixtiyoriy) o'sha mamlakat qatorlarini birinchi qo'yadi,
  boshqalari qoladi. Berilmasa biznes mamlakati olinadi.
- Javob: `[{id, name, type, context, countryCode}]`, `type`: `city`, `region`, `country`.
- Nomlar `ru`, `en` foydalanuvchilariga o'z tilida, `uz` uchun inglizcha.
- Foydalanuvchiga daqiqasiga 60 ta so'rov: `429`. Meta javob bermasa: `503`,
  `code: place_search_failed`.

**Saqlash:** `PUT /launch/drafts/{id}/edit`, `geo` bo'limi

| Maydon | Ma'nosi |
|---|---|
| `mode` | `list` (joylar) yoki `map` (nuqta + radius). Bir vaqtda bittasi ishlaydi |
| `places` | Tanlangan qatorlar. Qidiruvdan kelgan qator `id` va `name` bilan o'zgarmasdan yuboriladi |
| `lat`, `lng`, `km`, `address` | `map` rejimi uchun |
| `minKm`, `maxKm`, `placeLimit` | Faqat o'qish: chegaralar shu yerdan olinadi. Maxsus kategoriyada `minKm` 24 |

Xatolar (`422`, `problems`): qidiruv bermagan joy yoki joylar soni oshsa
`audience.places`; radius chegaradan tashqarida bo'lsa `geo.km`; nuqta yo'q bo'lsa
`audience.geo_mode`.

### Google Ads — `/google`

`GET /google`, `POST /google/switch`, `/google/budget`, `/google/delete`,
`/google/refresh`. Search ustasi: `POST /google/launch`,
`GET/POST /google/launch/{id}/answers`, `GET/POST .../words`,
`GET .../review`, `POST .../create`.

### Lidlar — `/leads`

| Endpoint | Vazifasi |
|---|---|
| `GET /leads` | Ro'yxat (filtrlar: `verdict`, `ad`, `adset`, `q`) |
| `GET /leads/stream?since=<cursor>` | Yangi lidlar uchun poll. `204` — o'zgarmagan |
| `GET /leads/sources` | Manbalar hisoboti |
| `GET /leads/export` | Eksport |
| `POST /leads/recover` | Yo'qolgan lidlarni Meta'dan qayta olish |
| `GET /leads/{pk}` | Tafsilot |
| `POST /leads/{pk}/verdict` | Sifatli/Sifatsiz belgisi (hozircha UI'da ko'rsatilmaydi) |

### Raqamlar — `/metrics`

[DASHBOARD_API.md](DASHBOARD_API.md) ga qarang. Kampaniya ekranlari uchun:
`GET /metrics/campaigns/figures`, `/metrics/ads/figures`,
`/metrics/campaigns/{id}/figures`, `/metrics/campaigns/{id}/creatives`,
`POST/GET /metrics/campaigns/{id}/today`.

### AI agent — `/agent`

| Endpoint | Vazifasi |
|---|---|
| `GET /agent` | Takliflar, kuzatuv, chastota |
| `POST /agent/{id}/approve`, `/reject` | Taklifga javob |
| `GET/POST /agent/{id}/new-ad` | Rad etilgan reklamaga yangi matn |
| `GET /agent/history` | Tarix |
| `GET/PUT /agent/settings` | Sozlamalar |
| `GET /agent/verdicts` | Kampaniyalar ro'yxatidagi baholar |
| `POST /agent/watch/{adset_id}/{move}` | Kuzatuv tugmalari |
| `POST /agent/frequency/{id}/fine`, `GET .../creative` | Chastota |

### AI chat — `/chat`

| Endpoint | Vazifasi |
|---|---|
| `GET /chat` | Ekran |
| `GET /chat/threads/{pk}` | Bitta suhbat |
| `POST /chat/ask` | Savol → `turn_id` |
| `GET /chat/stream/{turn_id}` | Javob oqimi (**SSE**, `EventSource`) |
| `GET /chat/report` | Hisobot |
| `GET/POST /chat/choices/{pk}` | Javob ostidagi tanlov tugmasi |
| `GET/POST /chat/changes/{message_id}/{key}`, `POST .../dismiss` | Chat tayyorlagan o'zgarish (byudjet, pauza) — egasi bossa bajariladi |

`EventSource` header yubora olmaydi, shuning uchun stream tokenni query'da
ham qabul qiladi: `new EventSource("/api/v1/chat/stream/<turn_id>?token=<access_token>")`.
`fetch` + `ReadableStream` ishlatilsa — oddiy `Authorization` header.

### CRM — `/crm`

[CRM_API.md](CRM_API.md) ga qarang.

### To'lov — `/billing`

| Endpoint | Vazifasi |
|---|---|
| `GET /billing` | Tariflar, joriy obuna, promo, to'lov usullari |
| `GET /billing/display` | Narxni qaysi valyutada ko'rsatish (login kerak emas) |
| `GET /billing/status` | Obuna holati, tugashiga necha kun |
| `GET /billing/paywall` | Paywall oynasi |
| `POST /billing/checkout` | Tarif sotib olish |
| `POST /billing/pages` | Qo'shimcha sahifa sotib olish |
| `GET /billing/invoice/{number}` | Hisob holati (poll) |
| `GET /billing/history` | Tarix |
| `POST /billing/promo`, `/promo/seen`, `/promo/page` | Promo kod |

Batafsil: [RAHMAT_TOLOV.md](RAHMAT_TOLOV.md).

### Referallar — `/referrals`

`GET /referrals` (hamyon), `GET /referrals/bonus`, `POST /referrals/code`,
`GET /referrals/invite`, `POST /referrals/withdraw`,
`POST /referrals/feedback`, `GET/POST /referrals/feedback/prompt`.

### Bildirishnomalar — `/notifications`

`GET /notifications`, `POST /notifications/connect` (Telegram botni ulash),
`POST /notifications/disconnect`, `POST /notifications/preferences`.

### Telegram Mini App — `/miniapp`

`GET /miniapp/entry`, `POST /miniapp/auth` (Telegram `initData` → tokenlar).

### Boshlash qadamlari — `/start`

| Endpoint | Vazifasi |
|---|---|
| `GET /start` | Qadamlar, nima bajarilgan, sahifa/akkaunt tanlovi, `next_action`. `?tries=&watch=` bilan — poll |
| `POST /start/finish` | "Yakunlash". Javob — yangilangan ekran va `message` |
| `GET /start/gate` | `{setup_pending, redirect_to, message, closed[]}` |

Django yakunlanmagan sozlashda boshqa bo'limlarni `/app/start`ga
yo'naltirardi. API hech narsani bloklamaydi: frontend `GET /start/gate`dan
`setup_pending: true` va ochilgan ekran `closed` ro'yxatida bo'lsa,
`redirect_to`ga o'tkazadi va `message`ni ko'rsatadi.

### Amallar va qo'ng'iroqcha — `/actions`

| Endpoint | Vazifasi |
|---|---|
| `GET /actions` | Amallar ekrani: `urgent`, `decisions`, `news` bo'limlari, takliflar, tarix, `counts` |
| `POST /actions/bell` | Qo'ng'iroqcha ochildi: oxirgi 6 element va ularni ko'rildi deb belgilaydi (shuning uchun POST) |
| `GET /actions/counts` | Badge: `{new, waiting}` — faqat o'qiydi |
| `GET /actions/history?before=` | Tarix, `next_before` bilan sahifalanadi |
| `GET /actions/proposals` | Agent takliflari va tarix |

Har element: `key`, `kind`, `level`, `title`, `body`, `since`, `action`
(tugma matni), `href` (frontend yo'li), `method` (`get`/`post`), `actions[]`
(bir nechta tugma), `ask` (AI chatga havola).

### So'rovnomalar — `/surveys`

| Endpoint | Vazifasi |
|---|---|
| `GET /surveys/due` | Hozir ko'rsatiladigan so'rovnoma yoki `survey: null` |
| `POST /surveys/answer` | `{survey, answers: {question_id: [qiymat]}, channel: "web"\|"miniapp"}` |
| `POST /surveys/later` | "Keyinroq" → `{ask_again_in: 605}` soniya |

Javob xatosi — `400 survey_answer_invalid`, `problems` kalitlari savol id.

### Yordam chati — `/support`

| Endpoint | Vazifasi |
|---|---|
| `GET /support?page=` | Chat ekrani: xabarlar, sahifalar, `cursor`, `send_key`, `composer` cheklovlari. Ochilganda o'qildi deb belgilaydi |
| `GET /support/panel` | Burchakdagi oyna (oxirgi sahifa) |
| `GET /support/widget` | `{has_chat, unread, preview}` — hech narsani belgilamaydi |
| `POST /support/messages` | Yuborish, **multipart**: `body`, `attachments[]`, `voice` + `voice_seconds`, `sticker`, `reply_to`, `send_key`, `nonce` |
| `PATCH /support/messages/{id}` | `{"body"}` — tahrirlash |
| `DELETE /support/messages/{id}` | Qaytarib olish |
| `GET /support/messages?after=<cursor>` | Poll: `204` — o'zgarmagan, `200` — o'zgargan/yangi xabarlar (`id` bo'yicha almashtiring) |
| `GET /support/files/{attachment_id}`, `/support/messages/{id}/file` | Fayl. `?view=1` — ichida ko'rsatish; `?token=` — `<img>`/`<video>` uchun |

**Jonli yangilanish — WebSocket** `wss://<host>/api/v1/support/ws?token=<access_token>`:

- Yuborish: `{"body": "...", "nonce": "...", "reply_to": null}`, `{"typing": true}`, `{"read": true}`
- Qabul: `{"type": "message"|"replace"|"read"|"typing"|"error", ...}`

Socket bo'lmasa — `GET /support/messages?after=` bilan poll.

### Google Sheets — `/destinations`

| Endpoint | Vazifasi |
|---|---|
| `GET /destinations/sheet` | Panel: `{enabled, panel}`. `panel.state`: `off`, `choosing`, `preparing`, `active`, `broken` |
| `POST /destinations/google/start` | `{mode, scope, only_form, next}` → `{url}` — Google'ga yo'naltiring |
| `POST /destinations/sheet/mode` | Yozish rejimini o'zgartirish (`single`, `per_form`, `own_file`) |
| `GET /destinations/sheet/picker` | Google File Picker uchun `{token, key, app_id, locale}` |
| `POST /destinations/sheet/pick` | `{file_id}` — tanlangan fayl |
| `POST /destinations/sheet/disconnect` | Uzish |
| `POST /destinations/sheet/recreate` | Yo'qolgan faylni qayta yaratish |

Google `…/destinations/google/callback`ga qaytaradi, backend
`next`ga (standart `/app/leads`) `?connected=sheet&sheet=<holat>` yoki
`?error=<matn>` bilan yo'naltiradi. `panel.state: "preparing"` paytida
`poll_seconds` oralig'ida `GET /destinations/sheet`ni qayta so'rang.

### Ochiq sahifalar — `/public` (login kerak emas)

`GET /public/home`, `POST /public/consult`, `GET /public/privacy`,
`GET /public/privacy/{business_id}`, `GET /public/terms`,
`GET/POST /public/data-deletion`, `GET /public/data-deletion/status/{code}`.

---

## 6. Hali backendda yo'q

Bu ekranlar uchun endpoint **hozircha yo'q** — UI'da yashiring yoki
"tez orada" deb ko'rsating:

| Ekran | Holat |
|---|---|
| Parolni tiklash ("Parolni unutdim") | ❌ |
| Telegram'dan brauzerga o'tish (handoff) | ❌ endpoint yo'q |
| Akkaunt sozlamalari ro'yxati (`/app/account/settings`) | ❌ |
| Video montaj | ❌ |
| Ortiqcha sahifa juftligini olib tashlash | ❌ |
| CRM menejer o'rnini sotib olish | ❌ |
| Yordam chati — ofis (xodim) tomoni | ❌ mijoz tomoni bor |
