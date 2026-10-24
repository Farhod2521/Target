# paykit — o'zgarishlar tarixi

Semantik versiyalash.

## 0.2.0 — 2026-09-19

Payme sandbox testlari talab qiladigan ikki javob.

### Qo'shildi
- `INVOICE_HELD` rad etishi — hisobni boshqa tranzaksiya band qilgan.
  Payme uni `-31008` bilan beradi (sandbox shuni kutadi, `-31051` emas),
  `data` maydonisiz. Click (`-4`) va Paynet (`411`) javobi o'zgarmadi.

### Tuzatildi
- Payme: har `Settled` javobida `reason` bor. `CheckTransaction` uni
  majburiy qiladi — bekor qilinmagan bo'lsa `null`, bo'lsa sabab kodi.

## 0.1.0 — 2026-08-29

Birinchi versiya. Bitta port, uchta adapter, HTTP klient yo'q.

### Qo'shildi
- `PaymentPort` — olti metod. Yo'nalish reklama portlaridan **teskari**:
  to'lov provayderi bizga so'rov yuboradi, biz javob tanasini yozamiz.
  Shu sababli `authenticate` / `parse` / `render` bor va klient yo'q.
- Buyruqlar: `check`, `create`, `perform`, `cancel`, `status`,
  `statement`. Payme oltita JSON-RPC metodi, Click ikkita imzolangan
  forma bilan gapiradi; ikkalasi ham shu oltitaga tushadi.
- Rad etish sabablari domen so'zi bilan (`invoice_not_found`,
  `amount_mismatch`, `state_not_allowed` …). Raqamni adapter tanlaydi:
  `-31050`, `-5` va `302` uchta kompaniyada bir xil narsani anglatadi.
- `TransactionState` da to'rtta holat, uchta emas. `refunded` — pul
  olingandan **keyin** bekor qilingani; xizmatni qaytarib olish shundan
  hisoblanadi.
- `Checkout` ikki shaklda: `redirect` (karta shlyuzi) va `reference`
  (agent tarmog'i — kassada naqd to'lanadi, yo'naltiriladigan sahifa
  yo'q). Ikkinchi port o'rniga bitta DTO, chunki farq ekranda, domenda
  emas.
- `payme` — Merchant API (JSON-RPC, Basic auth, tiyin = minor unit).
- `click` — SHOP-API (Prepare/Complete, MD5 imzo, butun valyutada summa).
- `paynet` — shartnoma imzolanmagan. Konvert, kredensial va o'qish
  tayyor; metod nomlari va xato raqamlari `paynet/codes.py` da va
  **vaqtinchalik** deb belgilangan.

### Qaror
- `httpx` **yo'q**. Har uchala provayder ham bizga so'rov yuboradi, va
  checkout havolasi merchant ID bilan summadan mahalliy quriladi —
  klient tekinga olinadigan bog'liqlik bo'lardi.
- `adskit` **yo'q**. Obuna to'lovi reklamaga bog'liq emas; kontrakt
  paketiga bog'lansa to'lov relizi reklama platformasiga bog'lanardi.
