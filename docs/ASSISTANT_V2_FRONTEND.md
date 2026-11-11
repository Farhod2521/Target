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
  "sessions": [{ "id": "…", "title": "Yordam", "last_message_at": "…", "created_at": "…", "support": true }],
  "thread": { "id": "…", "title": "…", "support": false },
  "messages": [ /* 2-bo'lim, eng yangi 50 tasi */ ],
  "has_earlier": true,
  "support": {
    "thread_id": "…",
    "unread": false,
    "waiting": false,
    "ws_path": "/api/v1/support/ws",
    "send_key": "…",
    "composer": {
      "max_body_chars": 2000,
      "max_upload_mb": 100,
      "max_send_mb": 200,
      "max_files": 10,
      "max_voice_seconds": 300,
      "typing_beat_ms": 2500,
      "typing_shown_ms": 5000,
      "allowed_suffixes": ["doc", "docx", "gif", "jpeg", "jpg", "mov", "mp4", "pdf", "png", "txt", "webp", "xls", "xlsx", "zip"],
      "voice_suffixes": ["m4a", "mp3", "ogg", "webm"],
      "stickers": [{ "code": "thumbs-up", "emoji": "👍", "name": "Zo'r" }]
    }
  },
  "questions_left": 18,
  "questions_total": 20,
  "questions_reset_at": "2026-11-12T00:00:00+05:00"
}
```

`composer` — eski Support oynasidagi bilan bir xil:

| Maydon | Ma'nosi |
|---|---|
| `max_body_chars` | Matn uzunligi chegarasi |
| `max_upload_mb` | Bitta fayl hajmi chegarasi |
| `max_send_mb` | Bitta xabardagi hamma fayllar jami |
| `max_files` | Bitta xabardagi fayllar soni |
| `max_voice_seconds` | Ovozli xabar uzunligi |
| `typing_beat_ms` / `typing_shown_ms` | "Yozmoqda…" signalini qancha vaqtda yuborish / ko'rsatish |
| `allowed_suffixes` | Ruxsat etilgan fayl kengaytmalari |
| `voice_suffixes` | Ovozli xabar formatlari |
| `stickers` | `code` (yuboriladigan), `emoji`, `name` |

- **`questions_left`** — bugungi qolgan savollar. Hisob **Toshkent vaqti bilan yarim
  tunda** (00:00, UTC+5) nolga tushadi; aniq vaqt `questions_reset_at` da keladi —
  brauzer vaqtini taxmin qilish shart emas. Har bir savoldan keyin yangi qiymat
  `POST /ask` javobidagi `left` da keladi. Faqat AI javob bergan savol hisoblanadi. Limit eski `/api/v1/chat` bilan umumiy.

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

**`html` xavfsiz.** Backend AI matnini avval to'liq escape qiladi (`<script>` →
`&lt;script&gt;`), keyin o'zi faqat shu teglarni qo'shadi: `p`, `br`, `strong`,
`code`, `ul`, `ol`, `li`, `dl`, `dt`, `dd`, `table`, `thead`, `tbody`, `tr`, `th`,
`td`. Atributlar (`href`, `onclick`, `style`…) va havolalar umuman bo'lmaydi.
`v-html` / `dangerouslySetInnerHTML` bilan to'g'ridan-to'g'ri chizish mumkin.
Qo'shimcha himoya istasangiz DOMPurify'dan shu ro'yxat bilan o'tkazing — hech narsa
yo'qolmaydi. O'z Markdown chizgichingiz shart emas (va `html` bilan farq qilib
qolishi mumkin).

`meta.stopped: true` — mijoz javobni to'xtatgan (7-bo'lim). Matn qayergacha
ko'rsatilgan bo'lsa, shu yergacha saqlanadi; ostida "To'xtatildi" deb yozing.

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
Javob: `{ "turn_id", "session_id", "message_id", "left" }`. `left` —
bugun qolgan savollar (`questions_left` ni shu bilan yangilang).

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
- `stopped: true` (oxirgi freymda) — javob to'xtatildi (7-bo'lim).
- `error`: `failed` | `denied` | `timeout`.

## 4. Tugmalar

`buttons[]` har bir elementida doim: `kind`, `key`, `label`, `state`, `state_text`.
Qolgan maydonlar `kind` ga qarab keladi:

| `kind` | Qo'shimcha maydonlar |
|---|---|
| `change` | `target` (obyekt nomi), `target_kind` (`kampaniya` / `reklama guruhi` / `reklama`), `action` (`budget` / `pause` / `resume`), `before`, `after` (tayyor matn: `"$10"`, `"Yoqilgan"`), `level`, `external_id`; byudjetda yana `currency`, `daily_budget_minor` |
| `ticket` / `guest_ticket` | `summary` (AI yozgan muammo tavsifi), `checked` (AI tekshirgan narsalar ro'yxati) |
| `offer` | `pk` (agent taklifi id), `target` (obyekt nomi), `rule` (qaysi qoida), `label` (taklif) |

Ichki maydonlarga (`log_id` va h.k.) tayanmang.

`change` kartochkasi, masalan:
```json
{
  "kind": "change", "key": "P1", "label": "Kunlik budjetni o'zgartirish",
  "target": "Kuzgi aksiya", "target_kind": "kampaniya", "action": "budget",
  "before": "$10", "after": "$15", "currency": "USD",
  "state": "open", "state_text": ""
}
```
→ **Kunlik budjetni o'zgartirish** · kampaniya «Kuzgi aksiya» · $10 → $15

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


## 5. Operatorga yozish

### `POST /assistant/support` (multipart/form-data)
| Maydon | |
|---|---|
| `body` | Matn |
| `session` | Suhbat id. Bo'sh — Support bor suhbat yoki yangi «Yordam» suhbati |
| `attachments` | 10 tagacha fayl |
| `voice` + `voice_seconds` | Ovozli xabar |
| `sticker` | Stiker kodi |
| `send_key` | Takroriy yuborishdan himoya kaliti (pastda) |

Javob 201: `{ "already_sent", "session_id", "message", "send_key" }`. Obuna shart emas.

**`send_key`** — bitta xabar uchun bitta kalit. Tarmoq uzilib, xuddi shu xabar
qayta yuborilsa, **eski kalitni** yuboring: server uni tanib `already_sent: true`
qaytaradi va ikkinchi nusxa yaratmaydi. Keyingi **yangi** xabar uchun kalitni:
- `POST /assistant/support` javobidagi `send_key` dan oling (ekranni qayta o'qish
  shart emas);
- yoki ekran javobidagi `support.send_key` dan oling.

O'zingiz `crypto.randomUUID()` ham yaratsangiz bo'ladi — server faqat har xabar
uchun alohida bo'lishini talab qiladi.

**Support javobini jonli olish:** `support.ws_path` ga WebSocket bilan ulaning (eski
Support oynasidagidek). `message` hodisasi kelganda ochiq suhbatni
`GET /assistant/threads/{id}` bilan qayta o'qing. Yoki `mode: "support"` paytida har
5–10 soniyada qayta o'qing.

## 6. Suhbatni boshqarish

| Method | URL | |
|---|---|---|
| GET | `/assistant/threads/{id}/messages?before=<xabar id>` | Oldingi xabarlar |
| PATCH | `/assistant/threads/{id}` `{"title": "…"}` | Nomini o'zgartirish → `ThreadOut` |
| DELETE | `/assistant/threads/{id}` | O'chirish → 204 |

**Sahifalash.** Ekran (`GET /assistant/threads/{id}`) suhbatning **eng yangi 50
ta** xabarini beradi; undan eskisi bo'lsa `has_earlier: true`. Yuqoriga
aylantirilganda: `GET /assistant/threads/{id}/messages?before=<ro'yxatdagi eng
birinchi xabar id>` → `{ "messages": [...50 tagacha, eskidan yangiga], "has_earlier" }`.
Ro'yxat boshiga qo'shing. `replies` faqat eng oxirgi javobda keladi, eski
sahifalarda doim bo'sh.

**Nomini o'zgartirish.** Bo'sh nom — 422. 60 belgidan uzuni kesiladi.

**O'chirish.** Suhbat va undagi xabarlar butunlay o'chadi. `support: true` bo'lgan
suhbatni (Support bilan yozishma bor) o'chirib bo'lmaydi — 409,
`code: "assistant_thread_has_support"`. Bunday suhbatda "O'chirish" tugmasini
ko'rsatmang. Nomini o'zgartirish mumkin.

## 7. Javobni to'xtatish

### `POST /assistant/stop/{turn_id}`
Javob: `{ "stopped": true }`. `false` bo'lsa — to'xtatadigan narsa yo'q (javob
tugagan yoki boshqa mijozniki).

- To'xtatilgandan keyin SSE'ning keyingi freymi oxirgisi bo'ladi:
  `done: true, stopped: true`. `html` — ko'rsatilgan joygacha.
- Xabar shu holatda saqlanadi (`meta.stopped: true`, tugmalarsiz). Sahifa
  yangilanganda ham xuddi shunday ko'rinadi.
- AI yozishni boshlab ulgurgan bo'lsa, savol limitdan **hisoblanadi**. Boshlamasdan
  to'xtatilgan bo'lsa — **hisoblanmaydi**.
- Mehmon ham tokensiz to'xtata oladi.
- Frontenddagi soxta to'xtatishni shu bilan almashtiring.

## 8. Mehmon (login qilmagan)

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

## 9. Ofis: yechimlar bazasi (Support va Owner)

AI muammo yechimini shu maqolalardan oladi.

**Kimga ochiq:** faqat **Support** va **Owner** rollari (Support chatga javob
beradiganlar). Boshqa rollarga 404 qaytadi (ofisdagi boshqa yopiq ekranlardagidek). Menyuda ko'rsatish uchun
`GET /api/v1/office/me` dagi **`can.answer_support`** ga qarang. Bu bayroq
Support chat (`chat`) bo'limini ham ochadi. **Joyi:** menyuda «Support chat»
ostida, «Yechimlar bazasi» nomli bo'lim sifatida. Alohida `sections` kodi
qo'shilmadi, mavjud ofis API'si o'zgarmadi.

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
