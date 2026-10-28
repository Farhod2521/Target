# Ofis API

Xodimlar paneli: menyu, jurnal, mijozlar ro'yxati, mijoz kartasi va
kartadagi amallar. Sotuv doskasi alohida: `/office/sales`.

- Hamma yo'llar `/api/v1/office` ostida, `Authorization: Bearer <token>`.
- Umumiy qoidalar (xatolar, tokenlar): [FRONTEND_INTEGRATSIYA.md](FRONTEND_INTEGRATSIYA.md).
- Javob shakllari Swagger'da (`/docs`, `office` bo'limi).

---

## 1. Rollar va ruxsat

| Rol | Kod |
|---|---|
| Qo'llab-quvvatlash | `Support` |
| Moliya | `Finance` |
| Developer | `Engineer` |
| Egasi | `Owner` |
| Sotuv menejeri | `Sales` |
| Sotuv boshlig'i | `SalesLead` |

- Ruxsati yo'q xodim (yoki oddiy mijoz) so'rasa — **`404`**, `403` emas.
  Ruxsat bo'lmagan tugma chizilmaydi.
- Superuser hamma rolga ega.

### `GET /office/me`

Har ekran ochilishida. Menyu va tugmalar shundan chiziladi.

```json
{
  "user": {"id": "…", "name": "Aziz", "email": "aziz@…"},
  "roles": [{"value": "Support", "label": "Qo'llab-quvvatlash"}],
  "can": {
    "give": true,            // tarif, kun, o'rin, to'lov, referal
    "grant": false,          // pul: hamyon, to'lov bo'shatish, promo kodlar
    "owner": false,          // jamoa, jurnal, sahifa qo'shish, mijozni o'chirish
    "superuser": false,      // mijoz parolini o'rnatish
    "engineer": false,
    "answer_support": true,
    "answer_feedback": false,
    "sell": false,
    "lead_sales": false
  },
  "waiting": {"promos": 2, "asks": 0, "feedback": 0, "support": 5, "arizas": 0}
}
```

`waiting` — menyu yonidagi raqamlar. Eshigi yo'q bo'lim uchun `0`.

### `GET /office/journal?kind=&offset=` — faqat Owner

Xodimlar amallari, yangisi birinchi, 50 tadan. `kind` bo'sh bo'lsa faqat
amallar (karta ochilgani kabi o'qishlar yashirin). `kinds[]` — filtr chiplari.

---

## 2. Mijozlar ro'yxati — `GET /office/customers`

Support, Finance, Owner. Xodimlar va CRM menejer loginlari chiqmaydi.

| Parametr | Ma'nosi |
|---|---|
| `q` | Email, ism, telefon, hisob raqami (`TA-…`), reklama akkaunti yoki sahifa ID |
| `state` | `trouble`, `trial`, `active`, `expiring`, `lapsed`, `never` (`states[]`) |
| `plan` | Tarif kodi (`plans[]`) |
| `joined_from`, `joined_to` | `YYYY-MM-DD`, ofis vaqti, ikkalasi ham kiradi |
| `manager` | Sotuv menejeri ID yoki `none` (`managers[]`) |
| `sort` | bo'sh (holatga qarab), `joined`, `expires`, `last_login` (`sorts[]`) |
| `offset` | Keyingi sahifa: javobdagi `next_offset` |
| `as_of` | Keyingi sahifada birinchi javobdagi `as_of` ni qaytaring |

Qator (`rows[]`):

| Maydon | |
|---|---|
| `customer` | `id`, `name`, `email`, `phone` |
| `is_blocked`, `joined_at`, `last_login_at` | |
| `business` | `name`, `direction` |
| `term` | `state` (`trial`/`active`/`lapsed`/`never`), `label`, `plan`, `days_left`, `expires_at`, `ended_on` |
| `trouble` | Eng yomon muammo: `kind`, `label`, `what`, `urgent`, `since` yoki `null` |
| `pages` | `used` / `allowed` (`allowed` faqat aktiv tarifda) |
| `running` | Hozir ishlayotgan kampaniyalar (faqat platformada yaratilgan) |
| `spend`, `leads` | Shu oy; sarf valyuta bo'yicha `[{currency, amount_minor}]` |
| `paid_total` | Jami to'lagan, valyuta bo'yicha |
| `paid_before` | O'chirilgan akkaunt shu email bilan to'lagan — kartada eski cheklar bor |
| `sales_manager` | Ochiq sotuv kartasi menejeri yoki `null` |

Muammo turlari (`trouble.kind`): `connection` (Facebook uzilgan),
`account_blocked`, `payment_due` (Meta'da qarz), `lead_gap`, `sweep`,
`launch`, `hold`, `expiring`, `setup`. `urgent: true` — qizil.

---

## 3. Mijoz kartasi — `GET /office/customers/{id}`

Ochilishi jurnalga yoziladi (30 daqiqada bir marta). Bloklar:

| Blok | Nima |
|---|---|
| `profile` | Ism, email, telefon, til, ro'yxatdan o'tgan, oxirgi kirish, bloklanganmi, sozlash tugagan vaqt |
| `businesses[]` | Nomi, yo'nalishi, sahifasi, shahar, telefon, sayt |
| `subscription` / `lapsed` | Aktiv obuna, yo'q bo'lsa oxirgisi |
| `limits` | Sahifalar, CRM o'rinlari, ishlayotgan reklama, AI budjeti, bugungi savollar, sinovda qolgan ishga tushirishlar |
| `plan_picker` | Har tarif uchun mijoz to'laydigan summa (`due_minor`), `waits` — arzonroq tarif hozir berilmaydi |
| `meta` | Facebook ulanishi: holat, profil nomi, muddat, oxirgi xato kodi |
| `ad_accounts[]`, `pages[]`, `pixels[]` | Sahifa ichida juftliklar va Instagram akkauntlari |
| `telegram`, `agent` | Bot ulanganmi, AI agent yoqilganmi |
| `money` | Jami to'lov, oxirgi 6 hisob, oxirgi 10 obuna o'zgarishi, eski cheklar |
| `referral` | Rejim, kim taklif qilgan, nechta taklif qilgan, hamyon, oxirgi 6 to'lov |
| `sales` | Ochiq sotuv kartasi, yopilganlar soni, izohlar, qo'ng'iroq taqiqi |
| `problems[]`, `traces[]` | Mijozning barcha muammolari; ofisning oxirgi 6 amali |

Token, parol, fingerprint, karta raqami, Telegram `chat_id` **hech qachon
kelmaydi**.

### `GET /office/customers/{id}/ads?period=`

`period`: `today`, `7`, `month` (standart), `30`, `all`. Faqat platforma
yaratgan kampaniyalar. `all` dan boshqa davrda sarfi, natijasi yo'q va
to'xtagan reklamalar yashiriladi (`hidden` — nechtasi).

---

## 4. Kartadagi amallar — `POST /office/customers/{id}/…`

Hammasida `reason` (1–500 belgi) majburiy — jurnalga yoziladi (o'chirishdan
tashqari). Javob: `{"message": "…"}` — xabar qatorida ko'rsating va kartani
qayta o'qing. Rad etish — odatdagi xato javobi (`400`/`422` + `problems`).

**"Pul to'landimi?"** (`plan`, `days`, `slots`, `pages/{page_id}/add`):
`paid: true` bo'lsa `amount` (butun birlikda, masalan `"100000"`) va
`method` (`cash`, `transfer`, `card`) majburiy, `pay_reference` ixtiyoriy.
To'langan bo'lsa hisob (invoice) yoziladi va dashboard'da hisoblanadi.

| Yo'l | Rol | Body |
|---|---|---|
| `plan` | Admin | `plan` (kod), + to'lov |
| `days` | Admin | `days` (1–120), + to'lov |
| `slots` | Admin | `pages` (1–20), `take` (olib qo'yish), + to'lov (`take` bilan emas) |
| `payment` | Admin | `amount`, `method`, `pay_reference` — mavjud kirish uchun pul |
| `referral` | Admin | `mode`: `auto`, `open`, `closed` |
| `receipts` | Admin | — eski cheklarni ulaydi, hech narsa bermaydi |
| `payout` | Finance, Owner | `amount`, `currency`, `method` (`card`, `bank`, `cash`), `pay_reference` |
| `pages/{page_id}/add` | Owner | + to'lov — tarifdan tashqari bitta o'rin va sahifa |
| `pages/{page_id}/move` | Admin | `target` (sahifa ID) — o'rinni boshqa sahifaga beradi |
| `pages/{page_id}/account` | Admin | `current`, `target` (akkaunt external ID) |
| `pages/{page_id}/remove-pair` | Admin | `account` (akkaunt external ID) |
| `password` | Owner + superuser | `new_password1`, `new_password2` — mijoz hamma qurilmada chiqariladi |
| `delete` | Owner | `email` — mijoz emailini qayta yozing. Javob: `message`, `rows`, `receipts_kept` |

Admin = Support, Finance, Owner.
