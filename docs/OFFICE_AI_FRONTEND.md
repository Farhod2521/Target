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

| Rol | Kira oladimi | Pul haqidagi savollar |
|---|---|---|
| Owner (Egasi) | Ha | Ha |
| Finance (Moliya) | Ha | Ha |
| Support | Ha | Yo'q — AI "pul faqat Moliya va Egasiga ko'rinadi" deydi |
| Superuser | Ha | Ha |
| Sales, Engineer va boshqalar | Yo'q — 404 | — |

Bu dashboard bilan bir xil qoida: pulni dashboardda kim ko'rsa, AI'da ham
o'sha ko'radi.

**Menyuda ko'rsatish:** `GET /api/v1/office/me` → `sections` ichida
`"home"` bo'lsa (Support, Finance, Owner), «AI yordamchi» bandini ko'rsating.

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
  "questions_total": 100
}
```

- `suggestions` — bo'sh ekranda tugma qilib ko'rsating. Bosilsa, matni savol bo'lib yuboriladi.
- `sees_money: false` — kiritish maydoni ostida kichik eslatma: "To'lov va tushum
  ma'lumotlari faqat Moliya va Egasiga ko'rinadi".
- `questions_left` — bugun qolgan savollar. Bitta xodimga kuniga 100 ta,
  Toshkent vaqti bilan yarim tunda yangilanadi.

## 2. Xabar

```json
{
  "id": "…",
  "author": "user | ai",
  "text": "…",
  "html": "…",
  "status": "pending | done | failed",
  "masked_figures": 0,
  "meta": { "lookups": ["customers_summary"], "stopped": true },
  "created_at": "…"
}
```

- **`html` xavfsiz.** Matn avval to'liq escape qilinadi, keyin faqat `p`,
  `br`, `strong`, `code`, `ul`, `ol`, `li`, `dl`, `dt`, `dd` va jadval teglari
  qo'shiladi. Atribut va havola bo'lmaydi. To'g'ridan-to'g'ri chizish mumkin.
- `masked_figures > 0` — javobda AI tekshirib bo'lmagan raqam bor, u `[?]` bo'lib
  ko'rinadi. Javob ostida "Ba'zi raqamlar tasdiqlanmadi" deb yozing.
- `meta.lookups` — AI javob uchun nimalarni o'qigani. Ixtiyoriy ravishda
  kichik yozuv sifatida ko'rsatish mumkin ("Manba: mijozlar, tushum").
- `meta.stopped: true` — xodim javobni to'xtatgan.
- `status: "failed"` — "Javob olinmadi, qayta urinib ko'ring" deb ko'rsating.

## 3. Savol berish va javobni oqim bilan olish

### `POST /office/ai/ask`
```json
{ "question": "Shu oy qancha to'lov tushdi?", "thread": "<suhbat id yoki bo'sh>" }
```
Javob: `{ "turn_id", "thread_id", "message_id", "left" }`.
`thread` bo'sh bo'lsa, yangi suhbat ochiladi va nomi savolning boshidan olinadi.

Xatolar: `400` (savol bo'sh), `429` `code: "office_ai_spent"` (bugungi savollar
tugadi), `404` (suhbat topilmadi).

### `GET /office/ai/stream/{turn_id}?token=<access_token>` (SSE)

Mijozlar chatidagi bilan bir xil shakl:
```json
{ "delta": "Shu oy ", "restart": false, "status": "", "done": false, "error": "" }
```
- `delta` ni oldingi matnga qo'shib boring.
- `restart: true` — matnni tozalab, `delta` dan qayta boshlang.
- `status` — AI ma'lumot o'qiyotgan paytdagi yozuv: "Tushumni hisoblayapman…".
- Oxirgi freymda `done: true`, `html` (yakuniy ko'rinish — matnni shu bilan
  almashtiring), `masked`, `stopped` keladi.
- `error`: `failed`, `denied` (boshqa xodimning javobi) yoki `timeout`.

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
