# Ofis AI chat — `/api/v2/office/ai`

Ofis xodimlari uchun AI yordamchi. U tizim haqidagi savollarga ofisning o'z
ma'lumotlaridan javob beradi: nechta odam ro'yxatdan o'tdi, qanchasi to'lov
qildi, qancha pul tushdi, qaysi tarif sotilyapti, kimning obunasi tugayapti,
hozir nimalar odamni kutyapti. Mijozlar kabinetidagi chatdan butunlay alohida.

- AI **faqat o'qiydi**, hech narsani o'zgartirmaydi: bloklamaydi, tarif
  bermaydi, pul qaytarmaydi.
- Raqamlar dashboard bilan bir xil manbadan olinadi, shuning uchun ekran va
  javob bir-biriga zid chiqmaydi.
- AI o'zi to'qib chiqargan raqam javobda `[?]` bo'lib ko'rinadi.

Base URL: `https://api.targetolog.ai/api/v2`. Token: `Authorization: Bearer <access_token>`.

---

## Kimga ochiq

| Rol | Kira oladimi |
|---|---|
| Owner (Egasi) | Ha, pul ma'lumotlari bilan |
| Superuser | Ha, pul ma'lumotlari bilan |
| Support, Finance, Sales, Engineer va boshqalar | Yo'q — 404 |

**Menyuda ko'rsatish:** `GET /api/v1/office/me` → `sections` ichida
`"ai"` bo'lsa, «AI yordamchi» bandini ko'rsating. U faqat Owner va
superuserga keladi. `"ai"` bo'lmasa, bandni ham, sahifani ham ko'rsatmang:
rolsiz xodim `/office/ai` ga kirsa, backend 404 qaytaradi.

Xuddi shu AI Telegram'dagi `@owners_tai_bot` da ham ishlaydi: `.env` dagi
`STAFF_BOT_ADMIN_IDS` ro'yxatidagi odamlar botga oddiy matn yozsa, AI
javob beradi. `/yangi` buyrug'i yangi suhbat boshlaydi.

Har kim **faqat o'z suhbatlarini** ko'radi. Birovning suhbatini ochish 404 qaytaradi.

## 1. Ekran

### `GET /office/ai` — bo'sh ekran
### `GET /office/ai/threads/{id}` — bitta suhbat

```json
{
  "sees_money": true,
  "threads": [{ "id": "…", "title": "Bugun nechta?", "last_message_at": "…", "created_at": "…" }],
  "thread": { "id": "…", "title": "…", "last_message_at": "…", "created_at": "…" },
  "messages": [ /* 2-bo'lim, eng yangi 50 tasi */ ],
  "has_earlier": false,
  "suggestions": [
    "Bugun nechta odam ro'yxatdan o'tdi?",
    "Shu oy qancha to'lov tushdi, qaysi tarif ko'p sotildi?",
    "…"
  ],
  "questions_left": 99,
  "questions_total": 100,
  "questions_reset_at": "2026-11-17T00:00:00+05:00",
  "pending_turn": null
}
```

- `suggestions` — bo'sh ekranda tugma qilib ko'rsating. Bosilsa, matni savol bo'lib yuboriladi.
- `sees_money` — Owner va superuser uchun doim `true`. Eslatma kerak emas.
- `questions_left` — bugun qolgan savollar. Bitta xodimga kuniga 100 ta.
- `questions_reset_at` — limit qachon to'lishi: Toshkent vaqti bilan
  keyingi yarim tun.
- `questions_total` — doim haqiqiy son (hozir 100). `0` kelmaydi va
  «cheksiz» degani emas.
- `pending_turn` — shu suhbatda hali yozilayotgan javobning `turn_id` si.
  Sahifa yangilanganda `null` bo'lmasa, `/stream/{pending_turn}` ni oching.
  Har 4 soniyada qayta o'qish shart emas. Javob tayyor bo'lsa, `null`.

## 2. Xabar

```json
{
  "id": "…",
  "author": "user | ai",
  "text": "…",
  "html": "…",
  "status": "pending | done | failed",
  "masked_figures": 0,
  "meta": { "lookups": ["customers_summary", "money_summary"] },
  "created_at": "…"
}
```

- **`html` xavfsiz.** Matn avval to'liq escape qilinadi, keyin faqat `p`,
  `br`, `strong`, `code`, `ul`, `ol`, `li`, `dl`, `dt`, `dd` va jadval teglari
  qo'shiladi. Atribut va havola bo'lmaydi. To'g'ridan-to'g'ri chizish mumkin.
- `masked_figures > 0` — javobda AI tekshirib bo'lmagan raqam bor, u `[?]` bo'lib
  ko'rinadi. Javob ostida "Ba'zi raqamlar tasdiqlanmadi" deb yozing.
- `meta.lookups` — AI javob uchun o'qigan manbalar nomlari, tartib bilan,
  satrlar ro'yxati. Bo'lishi mumkin bo'lganlar va o'zbekcha nomi:

  | Qiymat | Ko'rsatish |
  |---|---|
  | `customers_summary` | Mijozlar |
  | `money_summary` | Tushum |
  | `platform_activity` | Platforma |
  | `waiting_now` | Kutayotganlar |
  | `sales_by_manager` | Sotuv |
  | `recent_payments` | Oxirgi to'lovlar |
  | `customer_list` | Mijozlar ro'yxati |
  | `plans_summary` | Tariflar |

  Hech narsa o'qilmagan bo'lsa, `[]`.
- `meta.stopped: true` — xodim javobni to'xtatgan.
- `status: "pending"` — `meta.turn_id` bor (`pending_turn` bilan bir xil).
- `status: "failed"` — `meta.error` sababni aytadi:
  - `model` — AI xizmati javob bermadi yoki band: «AI hozir javob bera
    olmadi, birozdan keyin qayta urinib ko'ring».
  - `broke` — serverdagi xato: «Javob olinmadi, qayta urinib ko'ring».
  - `stuck` — javob 20 daqiqada tugamadi: «Javob olinmadi, qayta urinib
    ko'ring».

## 3. Savol berish va javobni oqim bilan olish

### `POST /office/ai/ask`
```json
{ "question": "Shu oy qancha to'lov tushdi?", "thread": "<suhbat id yoki bo'sh>" }
```
Javob: `{ "turn_id", "thread_id", "message_id", "left" }`.
`thread` bo'sh bo'lsa, yangi suhbat ochiladi va nomi savolning boshidan olinadi.

Xatolar:
- `400`, `code: "office_ai_empty"` — savol bo'sh.
- `429`, `code: "office_ai_spent"` — bugungi savollar tugadi.
  `detail` da tayyor matn keladi. Qachon yangilanishi `questions_reset_at` da.
- `404` — suhbat topilmadi, yoki xodim Owner/superuser emas.

### `GET /office/ai/stream/{turn_id}?token=<access_token>` (SSE)

Mijozlar chatidagi bilan bir xil shakl:
```json
{ "delta": "Shu oy ", "restart": false, "status": "", "done": false, "error": "" }
```
- `delta` ni oldingi matnga qo'shib boring.
- `restart: true` — matnni tozalab, `delta` dan qayta boshlang.
- `status` — AI ma'lumot o'qiyotgan paytdagi yozuv: "Tushumni hisoblayapman…".
- Oxirgi freymda `done: true` bilan quyidagilar keladi:
  - `html` — yakuniy ko'rinish, matnni shu bilan almashtiring.
  - `masked` — **son**: nechta raqam `[?]` qilingani, xabardagi
    `masked_figures` bilan bir xil.
  - `stopped` — true yoki false.
  - `lookups` — xabardagi `meta.lookups` bilan bir xil ro'yxat.
- `error` — faqat oqim haqida, xabarga yozilmaydi:
  - `failed` — javob yiqildi. Xabar `status: "failed"` va `meta.error`
    bilan saqlanadi.
  - `denied` — bu boshqa xodimning javobi yoki token eskirgan. Hech narsa
    saqlanmaydi, chunki javobning o'zi buzilmagan.
  - `timeout` — 120 soniya ichida yangi narsa kelmadi. Javob hali
    yozilayotgan bo'lishi mumkin: suhbatni qayta o'qing, `pending_turn`
    bo'lsa oqimni qayta oching.

### `POST /office/ai/stop/{turn_id}`
Javobni shu joyida to'xtatadi: `{ "stopped": true }`. AI yozishni boshlamasdan
to'xtatilsa, savol limitdan hisoblanmaydi.

## 4. Suhbatni boshqarish

| Method | URL | |
|---|---|---|
| GET | `/office/ai/threads/{id}/messages?before=<xabar id>` | Eski xabarlar → `{ messages, has_earlier }` |
| PATCH | `/office/ai/threads/{id}` `{"title": "…"}` | Nomini o'zgartirish |
| DELETE | `/office/ai/threads/{id}` | O'chirish → 204 |

## 5. AI nimalarga javob bera oladi

| Mavzu | Savol misoli |
|---|---|
| Mijozlar | "Bugun nechta odam ro'yxatdan o'tdi?", "Bu hafta ro'yxatdan o'tganlarning nechtasi to'ladi?", "Hozir nechta odam trialda?" |
| Tushum (Moliya, Egasi) | "Shu oy qancha pul tushdi?", "Qaysi tarif ko'p sotildi?", "O'tgan oyga nisbatan qanday?" |
| Oxirgi to'lovlar (Moliya, Egasi) | "Oxirgi kim to'lov qildi?" |
| Platforma | "Hozir nechta kampaniya ishlayapti?", "Bu hafta nechta lid keldi?" |
| Kutayotganlar | "Javobsiz support chatlar bormi?", "Qanday muammolar bor?" |
| Sotuv | "Qaysi menejer shu oy ko'p sotdi?" |
| Mijozni topish | "ali@mail.uz kim, tarifi qanday?", "Kimlarning obunasi tugayapti?" |
| Tariflar | "Har bir tarifda nechta odam bor?" |

Kunlar so'zda aytilsa, AI ularni o'zi tushunadi: "bugun", "kecha", "shu hafta",
"o'tgan oy", "noyabr", "1-dan 10-gacha". Kun aytilmasa, oxirgi 30 kun olinadi
va AI buni javobda aytadi.
