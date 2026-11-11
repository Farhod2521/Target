# Yagona AI chat — `/api/v2/assistant` (1-bosqich)

Kabinetdagi yagona chat: savol-javob, muammoni tekshirish, reklamani o'zgartirish
(byudjet, pauza, yoqish) va Support'ga zayavka — hammasi bitta joyda. Support
xodimining javobi ham shu chatning o'ziga keladi.

Eski `/api/v1/chat` va `/api/v1/support` o'zgarmagan, ular ishlab turibdi.

Base URL: `https://api.targetolog.ai/api/v2`. Token: `Authorization: Bearer <access_token>`.

---

## 1. Ekran

### `GET /assistant` — chat ekrani (yangi suhbat)
### `GET /assistant/threads/{id}` — bitta suhbat

```json
{
  "entitled": true,
  "mode": "ai",
  "sessions": [{ "id": "…", "title": "Yordam", "last_message_at": "…", "support": true }],
  "thread": { "id": "…", "title": "…", "support": false } ,
  "messages": [ /* 2-bo'lim */ ],
  "support": {
    "thread_id": "…",
    "unread": false,
    "waiting": false,
    "ws_path": "/api/v1/support/ws",
    "send_key": "…",
    "composer": { "max_body_chars": 2000, "max_files": 10, "stickers": [ … ], … }
  },
  "questions_left": 18,
  "questions_total": 20
}
```

- `entitled: false` — obuna yo'q. AI yopiq, lekin chat yopilmaydi: composer faqat
  **Operator** rejimida ishlaydi (`POST /assistant/support`). To'lov muammosi bo'lgan
  mijoz ham Support'ga yoza olishi kerak.
- `mode` — composer standart holatda kimga yozadi:
  - `"ai"` → `POST /assistant/ask`
  - `"support"` → `POST /assistant/support` (suhbat hozir odam bilan)

  Composer ustida almashtirgich qo'ying: **🤖 AI yordamchi | 👤 Operator**. Standart
  holat `mode` dan olinadi, mijoz o'zi almashtira oladi.
- `support.unread: true` — Support javob yozgan, hali o'qilmagan. Menyuda badge
  ko'rsating, bosilganda `support.thread_id` suhbatini oching. Suhbatni ochish
  javobni "o'qildi" qiladi.
- Mijoz avval eski «Yordam» oynasida yozgan bo'lsa, birinchi ochilganda o'sha
  yozishmalar «Yordam» nomli suhbat bo'lib keladi.

## 2. Xabar

```json
{
  "id": "…",
  "author": "user | ai | staff",
  "text": "…",
  "html": "…",
  "status": "pending | done | failed",
  "buttons": [ /* 4-bo'lim */ ],
  "replies": ["Ha", "Yo'q"],
  "meta": { "author": "Aziza" },
  "to_support": false,
  "support": null,
  "created_at": "…"
}
```

| `author` | Kim | Qanday chizish |
|---|---|---|
| `user` | Mijoz | O'ngda. `to_support: true` — ostida kichik "Operatorga yuborildi" |
| `ai` | AI | Chapda, AI belgisi bilan. `html` ni chizing |
| `staff` | Support xodimi | Chapda, boshqa rangda, `meta.author` (ism) + "Support" belgisi |

`support` maydoni — Support chatiga tegishli xabar uchun Support oynasining o'z
ko'rinishi: `files` (har birida `url`, `view_url`), `kind` (`voice`, `sticker`…),
`sticker_emoji`, `edited_at`, `read` (✓✓), `editable`, `deletable`. Mijoz o'z
xabarini tahrirlashi yoki o'chirishi: `PATCH` / `DELETE /api/v1/support/messages/{support.id}`.

`replies` — faqat eng oxirgi AI javobida keladi: tugma bosilsa, matni savol sifatida
yuboriladi.

## 3. Savol berish va javobni oqim bilan olish

### `POST /assistant/ask`
```json
{ "question": "Reklamam nega to'xtadi?", "session": "<thread id yoki bo'sh>" }
```
Javob: `{ "turn_id", "session_id", "message_id", "left" }`.

Waiting list qatoriga javob: `"item": "<key>"`. Agent taklifi haqida: `"suggestion": "<id>"`.

### `GET /assistant/stream/{turn_id}?token=<access_token>` (SSE)

Har bir freym:
```json
{ "delta": "Reklamangiz ", "restart": false, "status": "", "done": false, "error": "" }
```
- **`delta` ni oldingi matnga qo'shib boring** — javob so'zma-so'z chiqadi.
- `restart: true` — matnni tozalab, `delta` dan qayta boshlang (kamdan-kam).
- `status` — AI tekshirayotgan paytdagi yozuv: "Hisobingiz holatini tekshiryapman…".
- Oxirgi freym `done: true`: `html` (tayyor javob — `delta` matnini shu bilan
  almashtiring), `buttons`, `replies`.
- `error`: `failed` | `denied` | `timeout`.

## 4. Tugmalar

`buttons[]` har bir elementi: `kind`, `key`, `label`, `state`, `state_text`.

| `kind` | Nima | Bosilganda |
|---|---|---|
| `ticket` | «Mutaxassisga yuborish» | Zayavka Support doskasida ochiladi + Telegram'ga boradi |
| `change` | Byudjet / pauza / yoqish (`before` → `after`) | Reklama ekranining o'z servisi bilan bajariladi |
| `offer` | Agent taklifi | Amallar ekranining o'z servisi bilan tasdiqlanadi |
| `guest_ticket` | Mehmon uchun | Ism + telefon forma (6-bo'lim) |

- Bosish: `POST /assistant/buttons/{message_id}/{key}`
- Rad etish: `POST /assistant/buttons/{message_id}/{key}/dismiss`
- Holat: `GET /assistant/buttons/{message_id}/{key}` — `working` paytida 3–5 soniyada so'rang.

Javob: `{ "kind", "key", "state", "text" }`.

| `state` | Ma'nosi |
|---|---|
| `open` | Hali bosilmagan |
| `sent` | Zayavka yuborildi ("Javob shu chatga keladi") |
| `working` | Zayavka: xodim ishlayapti. O'zgarish: bajarilmoqda |
| `done` | Zayavka: hal qilindi. O'zgarish: bajarildi |
| `refused` | O'zgarish rad etildi — `text` da sabab |
| `dismissed` / `gone` | Bekor qilingan / endi yo'q |

`change` tugmasida kartochka chizing: `target` («nomi»), `label`, `before` → `after`.

## 5. Operatorga yozish

### `POST /assistant/support` (multipart/form-data)
| Maydon | |
|---|---|
| `body` | Matn |
| `session` | Suhbat id. Bo'sh — Support bor suhbat yoki yangi «Yordam» suhbati |
| `attachments` | 10 tagacha fayl |
| `voice` + `voice_seconds` | Ovozli xabar |
| `sticker` | Stiker kodi |
| `send_key` | `support.send_key` (har yuborishda yangisi) |

Javob 201: `{ "already_sent", "session_id", "message" }`. Obuna shart emas.

**Support javobini jonli olish:** `support.ws_path` ga WebSocket bilan ulaning (eski
Support oynasidagidek). `message` hodisasi kelganda ochiq suhbatni
`GET /assistant/threads/{id}` bilan qayta o'qing. Yoki `mode: "support"` paytida har
5–10 soniyada qayta o'qing.

## 6. Mehmon (login qilmagan)

- `POST /assistant/ask` tokensiz: `{"question": "...", "guest_id": "<brauzer id>", "asked": [oldingi savollar]}`.
- AI odam kerak deb hisoblasa, oxirgi freymda `buttons: [{ "kind": "guest_ticket", … }]`
  keladi. Forma chiqaring: **Ism**, **Telefon**, Email (ixtiyoriy).
- `POST /assistant/guest-ticket`:
  ```json
  { "turn_id": "…", "name": "Ali", "phone": "+998 90 123 45 67", "email": "" }
  ```
  201 → `{ "token", "chat" }`. Keyin bu mehmon Support chati: `GET /api/v1/support/guest`
  (header `X-Guest-Token: <token>`).
  422 — `problems` da maydon xatolari; 404 — zayavka topilmadi yoki yuborilgan; 409 — yuborilmoqda.

## 7. Ofis: yechimlar bazasi (Support va Owner)

AI muammo yechimini shu maqolalardan oladi.

| Method | URL | |
|---|---|---|
| GET | `/api/v2/office/help-articles?q=` | Ro'yxat |
| POST | `/api/v2/office/help-articles` | Yangi |
| GET / PUT / DELETE | `/api/v2/office/help-articles/{id}` | Bitta |
| POST | `/api/v2/office/help-articles/search?q=&language=uz` | AI nimani ko'rishini sinash |

```json
{
  "code": "lead-telegram",
  "problem_uz": "Lidlar Telegram guruhga kelmayapti",
  "problem_ru": "", "problem_en": "",
  "steps_uz": "Botni guruhga admin qilib qo'shing\nMijozlar sahifasida qayta ulang",
  "steps_ru": "", "steps_en": "",
  "keywords": "lid, telegram, guruh",
  "is_published": true,
  "position": 0
}
```
Qadamlar — har biri alohida qatorda. Chop etish uchun `problem_uz` va `steps_uz` majburiy.

Support doskasida AI chatdan kelgan zayavka sababi: `code: "ai"`, `label: "AI chatdan"`.
