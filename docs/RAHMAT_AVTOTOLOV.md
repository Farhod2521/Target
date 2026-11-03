# Rahmat (Multicard) — avtomatik to'lov

Mijoz kartasini **bir marta** bog'laydi. Keyin obuna muddati tugashidan bir kun
oldin shu tarif uchun pul kartadan o'zi yechiladi. Karta raqami bizga kelmaydi:
karta Multicard sahifasida qo'shiladi, bizda faqat Multicard bergan **token**
shifrlangan holda saqlanadi.

## 1. Server sozlamasi

Oddiy Rahmat to'lovi ([RAHMAT_TOLOV.md](RAHMAT_TOLOV.md)) allaqachon ishlayotgan
bo'lishi kerak. Qo'shimcha:

```dotenv
MULTICARD_AUTOPAY_ENABLED=true
MULTICARD_CARD_CALLBACK_URL=https://api.targetolog.ai/webhooks/cards/multicard
```

Multicard'dan quyidagilarni so'rang:

- Do'konimiz uchun **SMS kodsiz yechish** («безакцептное списание») yoqilsin.
  Yoqilmasa, har bir avtomatik urinish `needs_code` bilan to'xtaydi va mijoz
  qo'lda to'lashi kerak bo'ladi.
- Karta bog'lash (`/payment/card/bind`) va token bilan to'lash (`/payment`)
  bizning ilovamiz uchun ochiq bo'lsin.

Deploy'dan keyin migratsiyani ishga tushiring, u `saved_cards` jadvalini
yaratadi. Konteyner ishga tushganda migratsiya o'zi bajarilmaydi:

```bash
docker compose run --rm api alembic upgrade head
```

## 2. Qanday ishlaydi

```text
Mijoz «Kartani bog'lash» → POST /billing/card/bind
  ← form_url (Multicard sahifasi, 15 daqiqa amal qiladi)
Mijoz kartani qo'shadi, SMS kodni kiritadi
  → Multicard: POST /webhooks/cards/multicard   (imzosiz)
  → backend kartani Multicard'dan qayta o'qiydi va tokenni saqlaydi
Multicard mijozni SITE_URL/app/billing?card=bound ga qaytaradi

Har soatda (UTC :25):
  obunasi 1 kun ichida tugaydigan va kartasi bog'langan mijozlar uchun
  → shu tarif uchun hisob ochiladi
  → POST /payment (token bilan) → PUT /payment/{uuid} (bo'sh tana)
  → Multicard odatdagi imzolangan to'lov callback'ini yuboradi
  → hisob «paid», obuna 1 muddatga uzayadi
```

- Urinishlar: tugashdan **1 kun oldin** boshlanadi, kuniga ko'pi bilan 1 marta,
  bir muddat uchun ko'pi bilan **3 marta**. Tugaganidan keyin 2 kungacha davom etadi.
- Faqat pullik, bir martalik bo'lmagan va bekor qilinmagan obuna yangilanadi.
- Qo'shimcha sahifalar va CRM o'rinlari avtomatik yangilanmaydi, faqat tarif.
- Javobi noma'lum to'lov (`pending`) qayta yechilmaydi: keyingi urinishda
  uning holati Multicard'dan so'raladi.

## 3. Frontend

Barcha yo'llar `Authorization: Bearer <access>` bilan. Javoblar snake_case.

### Karta holati — `GET /api/v1/billing/card`

```json
{
  "available": true,
  "card": {
    "pan": "986027******1519",
    "ps": "humo",
    "holder": "ALI VALIYEV",
    "bound_at": "2026-11-03T10:00:00Z"
  },
  "autopay": true,
  "pending": false,
  "next_charge_at": "2026-12-02T10:00:00Z",
  "last_charge": {
    "at": "2026-11-02T10:25:00Z",
    "outcome": "declined",
    "error": "Kartada mablag' yetarli emas."
  }
}
```

| Maydon | Ma'nosi |
|---|---|
| `available` | `false` bo'lsa, bu bo'limni ko'rsatmang |
| `card` | `null` — karta bog'lanmagan. «Kartani bog'lash» tugmasi |
| `autopay` | Avtomatik yechish yoqilganmi |
| `next_charge_at` | Taxminiy keyingi yechish vaqti. Obuna yoki autopay bo'lmasa `null` |
| `last_charge.outcome` | `charged`, `pending`, `declined`, `needs_code` |
| `last_charge.error` | Tayyor o'zbekcha sabab. Bo'sh bo'lsa xato yo'q |

### Kartani bog'lash — `POST /api/v1/billing/card/bind`

```json
{ "consent": true, "phone": "998901234567" }
```

- `consent` — majburiy `true`. Ekranda checkbox: «Obuna har muddatda shu
  kartadan avtomatik to'lansin». Belgilanmasa `400 autopay_consent_required`.
- `phone` — karta egasining telefoni (Humo uchun majburiy). Bo'sh bo'lsa,
  akkauntdagi telefon olinadi. Noto'g'ri bo'lsa `400 autopay_phone_required`.

Javob:

```json
{ "session_id": "67f8dd24e9800", "form_url": "https://checkout.multicard.uz/card/67f8dd24e9800" }
```

`form_url` ni oching (yo'naltiring yoki WebView). `session_id` ni saqlab qo'ying.

### Qaytgandan keyin — `POST /api/v1/billing/card/bind/{session_id}/check`

Multicard mijozni `/app/billing?card=bound` (yoki `?card=declined`) ga
qaytaradi. Shu sahifada bir marta chaqiring. Javob `GET /billing/card` bilan
bir xil. `pending: true` bo'lsa, karta hali kelmagan: 2–3 soniyadan keyin
yana so'rang (ko'pi bilan 5 marta).

### Yoqish yoki o'chirish — `POST /api/v1/billing/card/autopay`

```json
{ "enabled": false }
```

Karta saqlanib qoladi, faqat avtomatik yechish to'xtaydi.

### Kartani uzish — `DELETE /api/v1/billing/card`

Karta bizdan o'chiriladi, Multicard'da token bekor qilinadi. Javob
`card: null` bilan.

### Xatolar

| Status | `code` | Holat |
|---|---|---|
| 404 | `autopay_unavailable` | Serverda avtomatik to'lov yoqilmagan |
| 400 | `autopay_consent_required` | Rozilik belgilanmagan |
| 400 | `autopay_phone_required` | Telefon raqami noto'g'ri |
| 404 | `autopay_card_not_found` | Karta yoki sessiya topilmadi |
| 503 | `autopay_unreachable` | Rahmat javob bermadi |

Hamma xatoda `detail` — tayyor o'zbekcha matn.
