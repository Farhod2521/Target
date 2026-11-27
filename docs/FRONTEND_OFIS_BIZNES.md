# Ofis: mijozning bizneslari — frontend qo'llanmasi

Mijoz kartasidagi yangi bo'lim. Har bir biznes — bitta sahifa + reklama akkaunti
juftligi va unga osilgan narsalar. Har bir qismni **alohida** olib tashlash mumkin;
«Biznesni o'chirish» esa hammasini birdan qiladi.

Hamma yo'l: `/api/v1/office/customers/{customer_id}/businesses…`
Mavjud ofis API lari o'zgarmagan. Meta'dagi reklamalarga bu amallarning hech biri tegmaydi.

## 1. Ro'yxat

`GET /api/v1/office/customers/{customer_id}/businesses` — sxema `OfficeBusinessesOut`.

```json
{
  "businesses": [
    {
      "id": "…",
      "name": "Zukko o'quv markazi",
      "pair": "1234567890:act_111",
      "page": {"id": "…", "external_id": "1234567890", "name": "Zukko", "subscribed": true},
      "networks": [
        {"provider": "meta", "kind": "meta_pair", "external_id": "1234567890:act_111", "name": "act_111"},
        {"provider": "google", "kind": "ad_account", "external_id": "123-456-7890", "name": "Zukko Google"}
      ],
      "members": 2,
      "crm": {"state": "on", "cards": 148},
      "knowledge": {"kind_state": "guessed", "by_ai": 5, "by_people": 2, "pending": 1}
    }
  ]
}
```

| Maydon | Ma'nosi |
|---|---|
| `pair` | Juftlik kaliti. Mavjud `…/crm?pair=` yo'llariga shu beriladi. Juftlik uzilgan bo'lsa bo'sh |
| `page.subscribed` | Sahifa obunada o'rin egallaganmi |
| `networks` | Biznes reklama beradigan tarmoqlar. `meta_pair` — sahifa + akkaunt, `ad_account` — boshqa tarmoq akkaunti |
| `crm.state` | `none` — hech qachon sozlanmagan, `draft` — sozlanmoqda, `on`, `off` |
| `knowledge.kind_state` | Biznes turi: `unset`, `guessed` (AI taxmini), `confirmed` |
| `knowledge.by_ai` | AI yozgan bo'laklar soni (tavsif, mahsulotlar, faktlar) — «Tozalash» shularni oladi |
| `knowledge.pending` | Egasining «ha» sini kutayotgan AI takliflari |

## 2. Amallar

Hammasi `POST`, tanada **`reason`** majburiy (1–500 belgi) — jurnalga yoziladi.
Javob: `{"message": "…"}` — matnni shundayligicha ko'rsating. Amaldan keyin ro'yxatni
qayta o'qing.

| # | Amal | Yo'l (`…/businesses/{business_id}` dan keyin) | Kim | Qo'shimcha maydon |
|---|---|---|---|---|
| 1 | AI yozgan bilimlarni tozalash | `/knowledge/clear` | Support, Finance, Owner | — |
| 2 | CRM ni to'xtatish / yoqish | `/crm/state` | Support, Finance, Owner | `on: true \| false` |
| 3 | CRM ni o'chirish (qayta sozlanadi) | `/crm/erase` | **faqat Owner** | — |
| 4 | Tarmoqni uzish | `/networks/{provider}/remove` | Support, Finance, Owner | `provider`: `meta`, `google`, `chatgpt` |
| 5 | Obunaga qo'shish | `/subscription/add` | Support, Finance, Owner | — |
| 6 | Obunadan olib tashlash | `/subscription/remove` | Support, Finance, Owner | — |
| 7 | Obunadagi o'rinni ko'chirish | `/subscription/move` | Support, Finance, Owner | `target`: boshqa biznes `id` si |
| 8 | Biznesni butunlay o'chirish | `/delete` | **faqat Owner** | `email`, `with_leads` |

### 1. AI yozgan bilimlarni tozalash

O'chadi: AI yozgan tavsif, mahsulot/xizmatlar, faktlar; tasdiq kutayotgan barcha
takliflar; hech kim tasdiqlamagan biznes turi (`guessed` → `unset`).
Qoladi: egasi, xodimi yoki ofis yozgan hamma narsa; tasdiqlangan tur.

Javobda qo'shimcha `cleared`: `{"about": 1, "items": 3, "facts": 0, "pending": 1, "kind": 1}`.
Tozalaydigan narsa bo'lmasa xato emas: «AI yozgan ma'lumot yo'q edi.»

### 2–3. CRM

- **To'xtatish / yoqish** — doska to'xtaydi, hech narsa yo'qolmaydi. Hech qachon
  sozlanmagan CRM ni ofis yoqa olmaydi: avval egasi sozlaydi.
- **O'chirish** — faqat shu biznesning CRM'i: kartalar tarixi bilan, ustunlar, rad
  sabablari, sozlama va menejerlar. **Lidlar qoladi**, boshqa bizneslar CRM'iga tegilmaydi,
  sotib olingan joylar qoladi. Boshqa joyda ishlamaydigan menejerning logini yopiladi.
  Keyin egasi CRM ni birinchi qadamdan qayta sozlaydi (`crm.state` → `none`).
  Qaytarib bo'lmaydi — tasdiq oynasi ko'rsating.

Mijozning **hamma** juftlikdagi CRM'ini o'chiradigan eski yo'l (`POST …/crm/erase`)
o'zgarmagan.

### 4. Tarmoqni uzish

- `meta` — sahifa + akkaunt juftligi uziladi. Sahifa ham, akkaunt ham ulangan holda
  qoladi; CRM va lidlar bazada qoladi. Biznesda boshqa tarmoq bo'lmasa, u ro'yxatda
  `pair: ""` bilan qoladi.
- boshqa tarmoq — akkaunt biznesdan uziladi, mijozniki bo'lib qoladi; xodimlarning shu
  tarmoqqa ruxsatlari o'chadi.

### 5–7. Obuna

Obuna hisobi o'zgarmagan: biznesning o'rni — uning **sahifasi** egallagan o'rin.

- **Qo'shish** — sahifa obunadagi bo'sh o'ringa yoqiladi. Bo'sh o'rin bo'lmasa
  `no_free_slot`: tarifdan tashqari o'rin kerak bo'lsa mavjud
  `POST …/pages/{page_id}/add` (faqat Owner, to'lov bilan) ishlatiladi.
- **Olib tashlash** — sahifa obunadan chiqadi, o'rin bo'shaydi. Biznes yiqqan narsalar
  yo'qolmaydi.
- **Ko'chirish** — bu biznesning o'rni mijozning boshqa (obunada bo'lmagan) biznesiga o'tadi.

Bitta sahifada ikkita juftlik (ikkita biznes) bo'lsa, o'rin sahifaniki: ikkalasi birga
qo'shiladi va birga chiqadi.

### 8. Biznesni butunlay o'chirish

```json
{"reason": "Mijoz so'radi", "email": "mijoz@example.com", "with_leads": false}
```

`email` — mijozning emaili, qayta teriladi (mos kelmasa `business_email_mismatch`).

O'chadi: shu biznesning CRM'i, bog'langan barcha tarmoqlar (juftlik ham), xodimlari,
biznes bilimi, sahifaning obunadagi o'rni (sahifada boshqa juftlik qolmasa) va biznes
yozuvining o'zi.
Qoladi: sahifa va reklama akkaunti ulangan holda — keyin yangi biznes sifatida qayta
juftlash mumkin; Meta'dagi reklamalar.
Lidlar: `with_leads: false` (odatiy) — bazada qoladi, hech bir biznesga bog'lanmagan
holda. `with_leads: true` — shu biznesning lidlari ham o'chadi.

Javobda qo'shimcha `deleted` — nima qancha o'chgani (jurnalga ham yoziladi).

## 3. Xato kodlari

| HTTP | `code` | Qachon |
|---|---|---|
| 404 | `unknown_business` | Bu mijozda bunday biznes yo'q |
| 409 | `business_has_no_pair` | Juftlik yo'q: CRM yoki Meta tarmog'i bilan qiladigan ish yo'q |
| 409 | `business_has_no_page` | Biznesga sahifa bog'lanmagan: obunada o'rni bo'lmaydi |
| 404 | `unknown_network` | Bu tarmoq biznesga ulanmagan |
| 400 | `business_email_mismatch` | Email mos kelmadi |
| 409 | `business_leads_held` | `with_leads: true`, lekin lidlarni o'chirib bo'lmadi; biznes o'chirilmagan |
| 400 | `no_free_slot`, `already_enabled`, `subscription_required` | Obunaga qo'shishda |
| 422 | — | `reason` yo'q |

## 4. Jurnal

Yangi yozuv turlari (`kind`), yorliqlari backenddan keladi: `business_ai_cleared`,
`business_crm_erased`, `business_network_removed`, `business_deleted`,
`business_subscribed`, `business_unsubscribed`, `business_slot_moved`.
