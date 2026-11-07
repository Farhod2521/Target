# Rassilka — frontend uchun

Barcha manzillar `/api/v1` bilan boshlanadi va `Authorization: Bearer <token>` talab qiladi.
Faqat `image_url` havolasiga kerak emas, token havolaning o'zida.

**Xatolar**
- `422` → `problems: {maydon: "matn"}` — matnni maydon ostida ko'rsating.
- `409` → `message` ni ko'rsating.

---

## A. Office → Rassilka

Menyu: `GET /office/me` → `sections` ichida `"broadcasts"` bo'lsa, ko'rsating. Faqat superadminga keladi.

### 1. Ro'yxat

`GET /office/broadcasts?status=&offset=`

- `rows`, `total`, `has_more`, `next_offset`
- `networks: {bot, channel, site}` — qiymati `false` bo'lsa, o'sha checkbox o'chiq turadi
- `statuses`, `audiences` — filtr va select uchun (`[{value, label}]`)

### 2. Yaratish / tahrirlash

- `POST /office/broadcasts` — yaratish
- `PUT /office/broadcasts/{id}` — tahrirlash (faqat `status = draft`)

Multipart forma:

| Maydon | Qiymat |
|---|---|
| `title` | majburiy, 120 belgigacha |
| `body` | majburiy, 3800 belgigacha, oddiy matn |
| `image` | jpg / png / webp, 5 MB gacha, ixtiyoriy |
| `to_bot` | `true` / `false` |
| `to_channel` | `true` / `false` |
| `to_site` | `true` / `false` |
| `audience` | `all` (hammaga) yoki `selected` (tanlanganlarga) |
| `user_ids` | `audience=selected` bo'lsa: har bir ID alohida maydon yoki `"id1,id2"`, 1000 tagacha |
| `remove_image` | `true` — faqat `PUT` da, rasmni o'chirish uchun |

- `audience=selected` tanlanganda Kanal checkboxi o'chirilsin (kanal hammaga ochiq).
- Foydalanuvchi qidirish uchun mavjud `GET /office/customers?q=` ishlatiladi.
- Javob: `{"message": "...", "id": "uuid"}` (yaratishda).

### 3. Bitta rassilka

`GET /office/broadcasts/{id}`

```json
{
  "id": "uuid",
  "title": "...",
  "body": "...",
  "image_url": "/api/v1/news/{id}/image?t=...",
  "to_bot": true,
  "to_channel": false,
  "to_site": true,
  "audience": "all | selected",
  "audience_label": "Hammaga",
  "users": [{ "id": "uuid", "name": "...", "email": "...", "bot_linked": true }],
  "status": "draft | sending | sent | stopped",
  "status_label": "Qoralama",
  "bot": { "total": 120, "sent": 100, "blocked": 3, "failed": 1, "pending": 16 },
  "channel": { "posted": false, "error": "" },
  "created_at": "...",
  "started_at": null,
  "finished_at": null
}
```

`bot_linked: false` — bu foydalanuvchiga xabar botga bormaydi, faqat saytda ko'radi. Ro'yxatda belgilab qo'ying.

### 4. Tugmalar

| Tugma | Qachon ko'rinadi | So'rov |
|---|---|---|
| Menga test | har doim | `POST /office/broadcasts/{id}/test` — xabar superadminning o'z botiga boradi |
| Yuborish | `draft` | avval `GET /office/broadcasts/{id}/recipients` → `{"bot": N}`, tasdiq oynasi ("Botda N kishiga ... yuborilsinmi?"), keyin `POST /office/broadcasts/{id}/send` |
| To'xtatish | `sending` | `POST /office/broadcasts/{id}/stop` — tasdiq so'rang, qayta davom etmaydi |
| O'chirish | `sending` dan boshqa | `DELETE /office/broadcasts/{id}` — tasdiq: "Saytdan olib tashlanadi, bot va kanaldagi xabarlar qoladi" |

### 5. Progress

Status `sending` bo'lsa, `GET /office/broadcasts/{id}` ni har 3–5 soniyada so'rang:

```
progress = (bot.sent + bot.blocked + bot.failed) / bot.total
```

`channel.error` bo'sh bo'lmasa, kanalga post chiqmagan — matnini ko'rsating.

### 6. Oldindan ko'rish

Telegram'dagi ko'rinish: rasm, ostida **qalin sarlavha**, bo'sh qator, keyin matn.

---

## B. Kabinet → Yangiliklar

| Amal | So'rov |
|---|---|
| Badge | `GET /news/unread` → `{"unread": 2}` |
| Ro'yxat | `GET /news?offset=` |
| Bittasi | `GET /news/{id}` |
| O'qildi | `POST /news/seen` — sahifa ochilganda |

Ro'yxat javobi: `rows`, `unread`, `total`, `has_more`, `next_offset`. Bitta qator:

```json
{ "id": "uuid", "title": "...", "body": "...", "image_url": "...", "published_at": "...", "is_unread": true }
```

`body` ni oddiy matn sifatida ko'rsating (HTML emas), qator tashlashlar saqlansin.

---

## C. Kabinet → Telegram sozlamalari

- `GET /notifications` → `preferences` ichida yangi kalit: `notify_news` — "Yangiliklar va e'lonlar".
- Saqlash: `POST /notifications/preferences` ga `{"notify_news": true | false}`. Yuborilmasa, eski qiymati o'zgarmaydi.

---

**Eslatma:** `image_url` 6 soatdan keyin eskiradi. Rasm ochilmay qolsa, ro'yxatni qayta so'rang.
