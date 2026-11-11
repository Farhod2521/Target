# Sotuv chegirmasi — frontend ishlari

Backend: `main`, commit `6c3ed48`. Avval backend deploy qilinishi kerak.

## Qanday ishlaydi

Sotuv menejeri ofis kanbanida «Chegirma berish» tugmasini bosadi. Shundan keyin mijozning
**birinchi** tarif to'lovi uchun chegirma ishlaydi:

- 24 soat — 20%
- 72-soatgacha — 10%
- keyin — chegirma yo'q

Hisoblash tartibi: **asl narx → sotuv chegirmasi → promokod (qolgan summadan) → hamyon**.

Misol (Standard, 490 000 so'm, 20% va 5% promokod):
490 000 → 392 000 (−20%) → 372 400 (−5%) → hamyondagi pul ayiriladi.

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
| «−20%» belgisi | `sales_offer.percent` |

`sales_offer === null` bo'lsa, chegirma yo'q: eski ko'rinish qoladi.

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

## `sales_offer`

```json
{
  "percent": 20,
  "ends_at": "2026-11-12T10:00:00Z",
  "pay_until": "2026-11-12T10:15:00Z"
}
```

- `percent` — 20 yoki 10.
- `ends_at` — shu foiz tugaydigan vaqt.
- `pay_until` — shu foiz bilan yaratilgan hisobni shu vaqtgacha to'lash mumkin (`ends_at` + 15 daqiqa).

## O'zgarmaydi

- Ofis kanbani: ustunlar va «Chegirma berish» tugmasi backenddan keladi.
- Mijozga chegirma haqida xabar yuborilmaydi.
