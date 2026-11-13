# Sotuv chegirmasi — frontend ishlari

> **2026-11-13 dan qoida o'zgardi** (branch `feat/start-discount`, migration `0053`).
> Quyidagi «Qanday ishlaydi» bo'limi yangi qoidani aytadi; front ham shu branchda qilingan.

## Qanday ishlaydi

Chegirma **o'zi boshlanadi**, «Chegirma berish» tugmasi yo'q. Ikki holat:

1. **Mijoz Start sotib oldi** — soat Start to'langan paytdan yuradi (`source: "start"`).
2. **Start olmagan lid bilan menejer gaplashdi** («Gaplashildi» bosildi) — soat shu bosilgan
   paytdan yuradi (`source: "contact"`). Har mijozga bir marta.

Start to'lovi o'z soatini yangidan boshlaydi (oldin suhbatdan chegirma bo'lgan bo'lsa ham).

- birinchi 24 soat — 20%
- keyingi 72 soat (jami 96-soatgacha) — 10%
- keyin — chegirma yo'q, ofisdagi karta «Yopildi» ga o'tadi

Chegirma mijozning **birinchi to'liq tarifiga** (Standart, Pro) tushadi.
**Start tarifiga chegirma berilmaydi** (bir martalik tariflarga ham). Batafsil: 7-band.

Hisoblash tartibi:
**asl narx → joriy tarif (Start) ning qolgan kunlari → qolgan summadan 20% (yoki 10%) →
promokod → hamyon**.

Misol (Standart 490 000 so'm, Start'ning 6 kuni qolgan = 42 000 so'm, 20%):
490 000 − 42 000 = 448 000 → 20% = 89 600 → **358 400 so'm**. Promokod va hamyon shundan
keyin ayiriladi. Chegirma butun so'mgacha pastga yaxlitlanadi.

Kartada (`cards[].offer`) va tanlangan tarifda (`chosen`) har bir qism alohida keladi:
`price_minor` (asl narx), `credit_minor` (Start qoldig'i), `offer_minor` (chegirma),
`promo_minor`, `wallet_minor`, `due_minor` (to'lanadi). Front hech narsani o'zi hisoblamaydi.

Hamma summalar **tiyinda** keladi: so'mga o'tkazish uchun 100 ga bo'ling.

## Hozirgi xato

Paywall dialogi narxni `plans[].price` dan oladi. U yerda doim asl narx turadi, shuning
uchun chegirma ko'rinmaydi. Narxni `cards[].offer` dan olish kerak.

## Qilinadigan ishlar

### 1. Paywall dialogi (kabinet, «Boshlash uchun tarifni tanlang»)

API: `GET /api/v1/billing/paywall?plan=<code>&promo=<kod>`

Har bir tarif kartasida:

| Ko'rsatiladi | Maydon |
|---|---|
| Asl narx (ustidan chiziladi) | `cards[].offer.price_minor` |
| Sotuv chegirmasi summasi | `cards[].offer.offer_minor` |
| Yangi narx | `cards[].offer.price_minor - cards[].offer.discount_minor` |
| «−20%» belgisi | `sales_offer.percent`, faqat `cards[].offer.offer_minor > 0` bo'lgan kartada |

`sales_offer === null` bo'lsa, chegirma yo'q: eski ko'rinish qoladi.
Kartada `offer_minor === 0` bo'lsa ham shu kartada eski ko'rinish qoladi (7-band).

### 2. Chegirma yozuvi va taymer

- Dialog tepasida «20% chegirma · 17:42:10 qoldi» yozuvi chiqadi, vaqt `sales_offer.ends_at` dan olinadi.
- Vaqt tugaganda paywall qayta so'raladi (refetch). Shunda narx 10% ga, keyin asl narxga o'tadi.

### 3. To'lov hisobi (tarif tanlangandan keyin)

API: o'sha `GET /api/v1/billing/paywall?plan=<code>&promo=<kod>`.
`chosen` faqat `plan` berilganda keladi.

| Qator | Maydon |
|---|---|
| Asl narx | `chosen.price_minor` |
| Sotuv chegirmasi | `chosen.offer_minor` |
| Promokod | `chosen.promo_minor` |
| Jami chegirma | `chosen.discount_minor` (= `offer_minor + promo_minor`) |
| Hamyondan | `chosen.wallet_minor` |
| **To'lanadi** | `chosen.due_minor` |

- Promokod xatosi `promo_error` maydonida keladi.
- Promokod ma'lumoti `promo_quote` da keladi. Uning `base_minor` maydoni sotuv chegirmasidan keyingi narx.
- Hamyon balansi `wallet_balance_minor` da keladi. Balans 0 dan katta bo'lsa, «Hamyondan to'lash» tanlovi chiqsin.

### 4. To'lov tugmasi

API: `POST /api/v1/billing/checkout`

```json
{ "plan": "standart", "provider": "<provayder>", "promo": "KOD", "wallet": "use" }
```

`wallet`: `"use"` — hamyondan ayirilsin, `"keep"` — ayirilmasin.

Javob:

| `kind` | Nima qilinadi |
|---|---|
| `redirect` | `url` ga o'tiladi |
| `wait` | `wait_url` ga o'tiladi |
| `covered` | hammasi hamyondan to'langan |

Hisob paywall'da ko'rsatilgan `due_minor` summasi bilan yaratiladi.

### 5. Kabinetdagi tariflar sahifasi

API: `GET /api/v1/billing?plan=<code>&promo=<kod>`

Bu sahifa ham 1–4-bandlardagi kabi ishlaydi: maydonlar bir xil (`cards`, `chosen`, `sales_offer`,
`promo_quote`, `promo_error`, `wallet_balance_minor`).

### 6. Live bridge va turlar

- `packages/api/src/live/bridges/billing.ts` dagi `toPaywallPlan` `cards[].offer` va `sales_offer` ni o'qisin.
- OpenAPI turlari qayta generatsiya qilinsin: `OfferOut.offer_minor` va `OfferOut.promo_minor` yangi maydonlar.

### 7. Start tarifiga chegirma yo'q (2026-11-12)

Backend endi Start tarifiga (va `plan.is_one_time: true` tariflarga) sotuv chegirmasini
qo'llamaydi. Bunday kartada `sales_offer` bor bo'lsa ham:

```json
"offer": { "price_minor": 9900000, "offer_minor": 0, "discount_minor": 0, "due_minor": 9900000 }
```

Hozirgi xato: front «−20%» belgisini va chizilgan narxni `sales_offer.percent` bo'yicha
hamma kartaga qo'yadi, shuning uchun Start ham «79 200» ko'rinadi.

Qilinadigan ishlar:

- Kartada chizilgan asl narx, «−20%» belgisi va yangi narx **faqat
  `cards[].offer.offer_minor > 0` bo'lsa** chiqadi. Aks holda oddiy narx: `offer.price_minor`.
- Narxni frontda foizdan hisoblamang: har doim `price_minor - discount_minor` ni oling.
- Tepadagi «20% chegirma · 23:14:42 qoldi» yozuvi o'zgarmaydi: u `sales_offer` dan olinadi.
- To'lov hisobida (`chosen`) «Sotuv chegirmasi» qatori faqat `chosen.offer_minor > 0` bo'lsa chiqadi.
- Start uchun hisob to'liq narxda yaratiladi; promokod va hamyon avvalgidek ishlaydi.

Tarif kodi yoki nomiga qarab shart yozmang: faqat `offer_minor` ga qarang.

## `sales_offer`

```json
{
  "percent": 20,
  "ends_at": "2026-11-12T10:00:00Z",
  "pay_until": "2026-11-12T10:15:00Z",
  "started_at": "2026-11-11T10:00:00Z",
  "source": "start",
  "next_percent": 10,
  "next_ends_at": "2026-11-15T10:00:00Z",
  "server_time": "2026-11-11T16:20:00Z"
}
```

- `percent` — 20 yoki 10.
- `ends_at` — shu foiz tugaydigan vaqt. Taymer faqat shunga qarab sanaydi.
- `pay_until` — shu foiz bilan yaratilgan hisobni shu vaqtgacha to'lash mumkin (`ends_at` + 15 daqiqa).
- `started_at` — chegirma boshlangan vaqt (Start to'lovi yoki suhbat).
- `source` — `start` yoki `contact`.
- `next_percent`, `next_ends_at` — keyingi bosqich (20% dan keyin 10%); 10% da `0` va `null`.
- `server_time` — javob berilgan paytdagi server vaqti. Taymer `ends_at − server_time` dan
  sanaydi, qurilma soatiga ishonmaydi.

Start egasi tarif devorini ko'rmaydi (`GET /billing/paywall` → `already_open`): unga
chegirma `GET /billing` (Tariflar) va to'lov sahifasida keladi.

## O'zgarmaydi

- Ofis kanbani: ustunlar va tugmalar backenddan keladi.
- Mijozga chegirma haqida xabar yuborilmaydi.
