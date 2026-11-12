# Sahifa + reklama akkaunti: faqat sahifa portfoliosidagi akkauntlar

Backend o'zgardi (2026-11-12, branch `feat/page-portfolio`, migratsiya `0051`).
Bu hujjat frontend uchun: nima keladi va qayerda nimani o'zgartirish kerak.

## Muammo nima edi

Sahifa tanlanganda akkaunt ro'yxatida Facebook profilining **hamma** reklama
akkauntlari chiqardi. A sahifaning portfoliosida n ta, B sahifaniki m ta akkaunt
bo'lsa, A uchun n + m ta akkaunt taklif qilinardi.

## Qoida (backend tekshiradi)

Faqat **yangi** juftlik tuzilganda tekshiriladi. Avval tuzilgan juftliklarga
tegilmaydi.

| Sahifa | Qaysi akkauntlarni tanlash mumkin |
|---|---|
| Biznes portfoliosida (`business`) | Faqat shu portfolioning akkauntlari: portfolioning o'zinikilar va unga ulashilganlar |
| Shaxsiy (`personal`) | Faqat shaxsiy akkauntlar (hech qaysi portfolioda emas) |
| Noma'lum (`unknown`) | Hech qaysi. Sahifada admin huquqi kerak |
| Hali o'qilmagan (`""`) | Hech qaysi. Backend o'zi o'qiydi, 1-2 daqiqadan so'ng yangilang |

Mos kelmagan akkaunt yuborilsa, backend `400` va `code: "account_not_for_page"`
qaytaradi. `detail`ni foydalanuvchiga shundayligicha ko'rsating.

## 1. Har bir sahifa uchun javob: `page_fits`

Uchta javobda keladi:

- `GET /api/v1/connections` → `page_fits`
- `GET /api/v1/connections/cabinet` → `page_fits`
- `GET /api/v1/start` → `page_fits`

```json
"page_fits": [
  {
    "page": "1234567890",
    "business_state": "business",
    "business_id": "1024312379779696",
    "business_name": "Targetolog AI",
    "allowed_ad_accounts": ["act_991464609479834", "act_2476855969492902"],
    "blocked_reason": "",
    "blocked_text": "",
    "may_create_account": true
  }
]
```

| Maydon | Ma'nosi |
|---|---|
| `page` | Sahifaning `external_id`si |
| `business_state` | `business` / `personal` / `unknown` / `""` |
| `business_name` | Portfolio nomi. Ro'yxat sarlavhasida ko'rsating: «Targetolog AI portfoliosi» |
| `allowed_ad_accounts` | Tanlash mumkin bo'lgan akkauntlarning `external_id`lari |
| `blocked_reason` | `page_unknown` yoki `page_unchecked` bo'lsa, bu sahifaga hech qaysi akkaunt tanlanmaydi |
| `blocked_text` | Shu holatda ko'rsatiladigan tayyor matn |
| `may_create_account` | `true` bo'lsa, «Yangi akkaunt yaratish» tugmasini ko'rsating |

Sahifa qatorlarida (`PageOut`) ham `business_state`, `business_name` va
`business_external_id` keladi. Akkaunt qatorlarida (`AdAccountOut`)
`business_external_id` va `business_ids` keladi. Guruhlash uchun kerak emas,
faqat ma'lumot uchun.

## 2. Akkaunt tanlagich

Sahifa tanlangandan keyin:

1. `page_fits` dan shu sahifaning qatorini toping.
2. `blocked_reason` bo'sh bo'lmasa, akkaunt ro'yxati o'rniga `blocked_text`ni
   ko'rsating. `page_unchecked` bo'lsa, «Yangilash» tugmasi qo'ying: u
   `GET /connections`ni qayta chaqiradi.
3. Aks holda ro'yxatda **faqat** `allowed_ad_accounts`dagi akkauntlar
   tanlanadigan bo'lsin. Qolganlarini yashiring.
4. `may_create_account` true bo'lsa, ro'yxat ostida «+ Yangi reklama akkaunti
   yaratish» tugmasi bo'lsin (3-bo'lim).
5. Ro'yxat bo'sh, lekin `may_create_account` true bo'lsa: «Bu portfolioda reklama
   akkaunti yo'q. Yangisini yarating.»

### `payer.options` (sahifa qo'shish va juftlik oynalari)

`add_page.payer.options`, `add_page.pairs[].options` va cabinet
`pair_prompt.options` dagi har bir variantga ikki maydon qo'shildi:

```json
{ "account": {...}, "recommended": false, "unusable": true,
  "not_for_page": "other_portfolio",
  "not_for_page_text": "Bu akkaunt sahifa turgan biznes portfoliosida emas." }
```

`not_for_page` bo'sh bo'lmasa, `unusable` ham `true` bo'ladi. Bunday
variantlarni ro'yxatdan olib tashlang. `add_page.payer`da sahifa hali
tanlanmagan, shuning uchun u yerdagi filtr `page_fits` orqali qilinadi
(yuqoridagi 2-bo'lim).

Kodlar: `other_portfolio`, `not_personal`, `page_unknown`, `page_unchecked`.

## 3. Yangi akkaunt yaratish

`POST /api/v1/connections/meta/page/ad-account`

```json
{ "page": "1234567890", "name": "Gradatsiya school", "currency": "USD" }
```

- `name` ixtiyoriy, bo'sh bo'lsa sahifa nomi olinadi.
- `currency` ixtiyoriy, standart `USD`. UZS'ni Meta qabul qilmaydi, shuning
  uchun tanlovda bo'lmasin. Taklif: USD, EUR, RUB.
- Vaqt zonasi doim Toshkent, so'ralmaydi.
- Sahifa avval qo'shilgan (yoqilgan) bo'lishi kerak.

Muvaffaqiyatli bo'lsa, `200 {"detail": "..."}` qaytadi. Akkaunt sahifaning
portfoliosida ochiladi va darhol shu sahifa bilan juftlik bo'ladi. `detail`da
Meta billing havolasi bor: yangi akkauntda karta yo'q, karta qo'shilmaguncha
reklama ko'rsatilmaydi. Matnni ko'rsating va `GET /connections`ni qayta oling.

Xatolar (`400`, `detail`ni ko'rsating):

| `code` | Qachon |
|---|---|
| `ad_account_no_portfolio` | Sahifa shaxsiy yoki portfoliosi noma'lum |
| `ad_account_limit` | Portfolioda akkauntlar chegarasi tugagan (Meta 3979) |
| `ad_account_bad_standing` | Portfoliodagi biror akkaunt bloklangan (Meta 3980) |
| `ad_account_two_factor` | Facebook'da ikki bosqichli tasdiqlash kerak (Meta 415) |
| `ad_account_not_allowed` | Portfolioda admin emas (Meta 200) |
| `ad_account_not_created` | Boshqa xato, keyinroq urinish |
| `ad_account_rehearsed` | Sinov rejimi (staging), Meta'ga bormaydi |

## 4. Onboarding (`/start`)

`GET /api/v1/start` → `pick.options[]` (shuningdek `recommended`, `others`,
`unusable`) dagi har bir variantda endi `not_for_page` maydoni bor. Bo'sh
bo'lmasa, `unusable: true` bo'ladi. Bunday akkauntlarni ro'yxatda
ko'rsatmang.

`pick.rows[].problems` ichida yangi kod paydo bo'ldi: `account_not_for_page`.
U sahifaga ulangan akkaunt portfolioga mos kelmasligini bildiradi. Matn:
«Bu akkaunt sahifa portfoliosida emas, boshqasini tanlang».

Tanlangan akkaunt mos kelmasa, `POST /start/finish` `400 account_not_for_page`
qaytaradi. Shu holda foydalanuvchini akkaunt tanlash qadamiga qaytaring.

## 5. Ofis: mijoz kartasi

`GET /api/v1/office/customers/{id}` → `pages[]` qatorlariga qo'shildi:
`business_state`, `business_name`, `allowed_ad_accounts` va `blocked_text`.
`POST .../pages/{page_id}/account` oynasida faqat `allowed_ad_accounts`dagi
akkauntlarni taklif qiling. Boshqasi yuborilsa, backend `account_not_for_page`
qaytaradi.

## Tekshirilmagan

- Haqiqiy Meta'da `me/accounts` ichidagi `business{id,name}` maydoni hali sinalmagan.
- Haqiqiy Meta'da `POST /{business_id}/adaccount` hali sinalmagan.

Staging'da bitta haqiqiy profil bilan sinaganda `page_fits` Ads Manager'dagi
portfolio ro'yxati bilan solishtirilsin.
