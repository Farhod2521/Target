# Rahmat (Multicard) orqali to'lov

Tarif va qo'shimcha sahifalar uchun to'lov Rahmat (Multicard) orqali:
Uzcard, Humo, Visa. Karta ma'lumoti **bizning serverga ham, frontendga ham
kelmaydi** — to'lovchi Multicard'ning o'z sahifasida to'laydi.

Ikki qism:

1. [Backendni sozlash](#1-backendni-sozlash) — DevOps / backend.
2. [Frontend oqimi](#2-frontend-oqimi) — frontend.

---

## 1. Backendni sozlash

Kod tayyor (`packages/paykit/src/paykit/multicard/`). Faqat `.env`ni
to'ldirish kerak. Barcha majburiy qiymatlar to'ldirilmaguncha provayder
yoqilmaydi va `GET /billing` → `providers`da chiqmaydi.

### `.env`

```dotenv
# Multicard bergan ma'lumotlar
MULTICARD_APPLICATION_ID=          # majburiy
MULTICARD_SECRET=                  # majburiy
MULTICARD_STORE_ID=                # majburiy
MULTICARD_API_URL=https://mesh.multicard.uz
MULTICARD_CALLBACK_URL=https://<api-host>/webhooks/pay/multicard   # majburiy

# Fiskal chek (OFD). Kodlar tasnif.soliq.uz'dagi xizmat kodlari — buxgalterda bor
MULTICARD_OFD_MXIK=                # majburiy (IKPU)
MULTICARD_OFD_PACKAGE_CODE=        # majburiy
MULTICARD_OFD_NAME=TargetologAI obunasi
MULTICARD_OFD_VAT=                 # foiz; QQS to'lanmasa bo'sh
MULTICARD_OFD_TIN=                 # ixtiyoriy

# Ixtiyoriy: faqat shu IP'lardan callback qabul qilinadi
MULTICARD_ALLOWED_IPS=             # masalan 195.158.26.90

# Saytning ochiq domeni (pastdagi izohga qarang)
SITE_URL=https://targetolog.ai
```

| O'zgaruvchi | Izoh |
|---|---|
| `MULTICARD_CALLBACK_URL` | Har hisob bilan Multicard'ga yuboriladi. **Backend** domeni, `/webhooks/pay/multicard` (oxirida `/` yo'q) |
| `MULTICARD_ALLOWED_IPS` | Multicard callbacklari `195.158.26.90`dan keladi. Faqat proxy haqiqiy IP'ni `X-Real-IP` yoki `X-Forwarded-For`da uzatsa yoqing, aks holda hamma callback rad etiladi |
| `SITE_URL` | Multicard to'lovdan keyin `SITE_URL/app/billing/invoice/<number>` sahifasiga qaytaradi — bu **frontend** sahifasi. Lekin xuddi shu `SITE_URL` Meta OAuth callback (`/connections/meta/callback`) va referal havola (`/r/{code}/`) uchun ham ishlatiladi — ular **backend** yo'llari. Shuning uchun frontend va backend bitta domen ostida bo'lishi kerak: proxy `/api/`, `/webhooks/`, `/r/`, `/data-deletion/callback/` ni backendga, qolganini frontendga yuboradi |

### Test

- Test muhit: `MULTICARD_API_URL=https://dev-mesh.multicard.uz` — pul
  yechilmaydi.
- Test muhit callback'ni yubora olishi uchun backend internetdan ochiq
  bo'lishi kerak (masalan, staging yoki tunnel).
- Sozlangandan keyin `GET /api/v1/billing` → `providers` ichida
  `{"name": "multicard", "label": "Rahmat (Uzcard, Humo, Visa)"}` chiqishi
  kerak.

### Qanday ishlaydi (backend ichida)

```text
POST /billing/checkout
  → Multicard API: hisob yaratish (summa tiyinda, fiskal chek qatori, callback_url, return_url)
  ← checkout_url
  → frontendga {"kind": "redirect", "url": checkout_url}

To'lovchi kartadan to'laydi
  → Multicard: POST /webhooks/pay/multicard  (imzo: md5(store_id + invoice_id + amount + secret))
  → backend: imzo, do'kon, summa tekshiriladi → hisob "paid", obuna yoqiladi
  ← {"success": true}       (boshqa javob → Multicard pulni qaytaradi)

Multicard to'lovchini SITE_URL/app/billing/invoice/<number> ga qaytaradi
```

- To'lov faqat **so'mda** (`UZS`).
- Hisob 24 soat amal qiladi.
- Bir to'lov ikki marta hisoblanmaydi (Multicard `uuid` bo'yicha).
- Status webhook (Multicard kabinetida yoqilgan bo'lsa) qabul qilinadi,
  lekin unga qarab hech narsa qilinmaydi — uning imzosi `status`ni qamrab
  olmaydi. Hisobni faqat imzolangan to'lov callback'i yopadi.
- Karta tokeni saqlanmaydi.

---

## 2. Frontend oqimi

### 2.1. To'lov usullarini olish

```http
GET /api/v1/billing
```

Kerakli maydonlar:

```json
{
  "plans": [ /* tariflar */ ],
  "providers": [{"name": "multicard", "label": "Rahmat (Uzcard, Humo, Visa)"}],
  "payments_on": true,
  "wallet_minor": 0
}
```

- `payments_on: false` — hech qanday to'lov usuli sozlanmagan; to'lov
  tugmasini o'chiring.
- Ro'yxatda bitta usul bo'lsa, tanlov ko'rsatmasdan o'shani yuboring.

### 2.2. Hisob ochish

**Tarif:**

```http
POST /api/v1/billing/checkout
{
  "plan": "pro",
  "provider": "multicard",
  "promo": "",
  "wallet": "keep",
  "pages": "keep"
}
```

| Maydon | Izoh |
|---|---|
| `plan` | Tarif kodi (`GET /billing` → `plans[].code`) |
| `provider` | `providers[].name` |
| `promo` | Promo kod (ixtiyoriy) |
| `wallet` | `use` — referal hamyonidan ayirish, `keep` — ishlatmaslik |
| `pages` | `keep` yoki `drop` — tarif o'zgarganda ortiqcha sahifalar |

**Qo'shimcha sahifa:**

```http
POST /api/v1/billing/pages
{"count": 1, "provider": "multicard", "wallet": "keep", "add_page": "", "pay_from": ""}
```

**Javob (ikkalasida bir xil):**

```json
{
  "number": "4821930517",
  "kind": "redirect",
  "url": "https://checkout.multicard.uz/...",
  "wait_url": "/app/billing/invoice/4821930517"
}
```

| `kind` | Nima qilish |
|---|---|
| `redirect` | `window.location.href = url` — Multicard sahifasiga |
| `covered` | To'lov kerak emas (promo yoki hamyon to'liq qopladi) — darhol `wait_url`ga |
| `wait` | Multicard'da bo'lmaydi (boshqa provayderlar uchun) |

Xatolar (`400`, `detail` matnini ko'rsating):

- `"Bu tarif hozir sotuvda emas."`
- `"To'lov usulini tanlang."` — `provider` bo'sh
- Promo kod rad etilgan matnlari

### 2.3. Qaytish sahifasi — `/app/billing/invoice/[number]`

Frontendda **shu yo'lda sahifa bo'lishi shart**: Multicard to'lovdan keyin
(muvaffaqiyatli yoki yo'q) to'lovchini `SITE_URL` + shu yo'lga qaytaradi.
Query'da `add_page`, `pay_from` bo'lishi mumkin — ularni so'rovga o'tkazing.

Sahifa hisob holatini so'rab turadi:

```http
GET /api/v1/billing/invoice/{number}?tries=0
```

```json
{
  "invoice": {
    "number": "4821930517",
    "kind": "plan",
    "status": "pending",
    "plan": { /* tarif */ },
    "amount_minor": 49900000,
    "currency": "UZS",
    "expires_at": "...",
    "paid_at": null,
    "paid_via": ""
  },
  "via": "",
  "polling": true,
  "settled": false,
  "gave_up": false,
  "paid": false,
  "just_landed": false,
  "tries": 1,
  "poll_seconds": 3,
  "back_url": ""
}
```

Tartib:

```text
loop har poll_seconds (3 s):
    GET /billing/invoice/{number}?tries=<oxirgi tries>
    paid == true      → "To'lov qabul qilindi", back_url bo'lsa o'sha yerga
    settled && !paid  → status bo'yicha xabar (bekor qilingan / muddati o'tgan)
    gave_up == true   → "To'lov hali tasdiqlanmadi, keyinroq tekshiring"
    polling == false  → to'xtat
```

- Server 60 urinishdan keyin (~3 daqiqa) `gave_up: true` beradi.
- `back_url` — keyingi sahifa: `/app/start` (sozlash tugamagan bo'lsa)
  yoki `/app/connections?...` (sahifa qo'shish uchun to'langan bo'lsa).
  Bo'sh bo'lsa — tariflar yoki dashboard.
- `just_landed: true` — to'lov aynan shu kutish paytida tushdi (tabrik
  animatsiyasi uchun).

`invoice.status`:

| Qiymat | Ma'nosi |
|---|---|
| `pending` | To'lanmagan, kutilmoqda |
| `held` | Provayderda ushlangan, hali yakunlanmagan |
| `paid` | To'landi |
| `canceled` | Bekor qilindi |
| `expired` | Muddati o'tdi (24 soat) |
| `refunded` | Qaytarildi |

### 2.4. Narxni ko'rsatish (dollar)

Chet eldan kirganlarga narx dollarda ko'rsatiladi, lekin **to'lov baribir
so'mda**.

```http
GET /api/v1/billing/display     (login shart emas)
```

```json
{"country": "DE", "currency": "USD", "uzs_per_usd": "12650.00", "rate_date": "28.10.2026"}
```

`currency: "USD"` bo'lsa: `≈ $ (so'm summa / uzs_per_usd)` deb, taxminiy
belgisi bilan ko'rsating. Multicard sahifasida summa so'mda bo'ladi —
foydalanuvchini bundan oldindan ogohlantiring.

### 2.5. Tarix

`GET /api/v1/billing/history` → `invoices[]` (`paid_via: "multicard"`) va
obuna o'zgarishlari.

---

## 3. Tekshiruv ro'yxati

- [ ] `.env`da 6 ta majburiy `MULTICARD_*` to'ldirilgan
- [ ] `MULTICARD_CALLBACK_URL` backend domeniga, `/webhooks/pay/multicard`
- [ ] `SITE_URL` — ochiq domen; unda `/app/billing/invoice/...` frontendga, `/webhooks/`, `/api/` backendga yo'naltirilgan
- [ ] `GET /billing` → `providers`da `multicard` bor
- [ ] Frontendda `/app/billing/invoice/[number]` sahifasi bor va poll qiladi
- [ ] Test muhitda (`dev-mesh`) to'liq to'lov: redirect → to'lash → qaytish → `paid: true`
- [ ] `MULTICARD_ALLOWED_IPS` faqat proxy haqiqiy IP'ni uzatsa yoqilgan
- [ ] Prod'ga o'tishda `MULTICARD_API_URL=https://mesh.multicard.uz`
