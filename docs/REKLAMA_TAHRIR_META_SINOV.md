# Ishlab turgan reklamani tahrirlash — real Meta'da sinov ro'yxati

Tahrir imkoniyatlari (1–4 va 6-bosqich) soxta Meta javoblari bilan
testlangan. Bu ro'yxat ularni **bitta to'xtatilgan test reklamasida** haqiqiy
Meta'da tekshirish uchun. Har qatorda: nima yuboriladi, Ads Manager'da nima
ko'rinishi kerak, qanday qaytariladi.

## Tayyorgarlik

- Backend shu o'zgarishlar bilan deploy qilingan, `ADS_DRY_RUN=false`.
- O'zimizning test akkauntimizda bitta kampaniya: **lid formali**, byudjet
  **guruhda** (ABO), bitta guruh, bitta reklama (rasm, post asosida emas).
  Hammasi **to'xtatilgan** — pul sarflanmaydi.
- Ikkinchi test uchun: **saytga olib boradigan** reklama (havola va UTM uchun)
  va agar bo'lsa **karusel** reklama.
- Ads Manager shu kampaniyada ochiq turadi: har qadamdan keyin sahifa yangilanadi.
- Har qadamdan keyin `GET /campaigns/actions/{actionId}` yoki
  `ControlState` `pending: false` bo'lguncha kuting. `failure` / `refused`
  chiqsa — Meta matnini yozib oling va to'xtang.

Belgilar: `{c}` — kampaniya id (bizniki), `{s}` — guruhning Meta id'si,
`{a}` — reklamaning Meta id'si.

## 1-bosqich. Joylashuv va Advantage+ auditoriya

| # | So'rov | Ads Manager'da | Qaytarish |
|---|---|---|---|
| 1.1 | `GET /campaigns/{c}/edit` | `placement.apps` va `advantage.on` Ads Manager'dagi bilan bir xil | — |
| 1.2 | `PATCH /campaigns/{c}` `apps: "fbig"`, `positions: {instagram: ["stream","story"], facebook: ["feed"]}` | Placements: Manual, faqat shu uchta joy | «Qaytarish» |
| 1.3 | `apps: "instagram"` + `positions.instagram: ["stream","ig_search"]` | Instagram feed va search. **Lid maqsadida Meta `ig_search`ni tashlab yuborishi mumkin**: tarixda `dropped` bormi, forma qaytadan o'qilganda nima ko'rsatadi | «Qaytarish» |
| 1.4 | `apps: "auto"` | Advantage+ placements | — |
| 1.5 | `advantage: true` | Advantage+ audience yoqilgan; yuqori yosh chegarasi yo'q | — |
| 1.6 | `advantage: false` | Original audience; yosh oralig'i saqlangan | — |
| 1.7 | 1.2 dan keyin «Qaytarish» | Joylashuv 1.2 dan oldingi holatga qaytgan | — |

**Tekshiriladigan noaniqlik:** ishlab turgan guruhda `targeting_automation`
va `publisher_platforms`ni almashtirishni Meta qabul qiladimi.

## 2-bosqich. Reklamaning o'zi

Har biri yangi kreativ yaratadi. Avval `inPlace: false` (yangi reklama),
keyin bittasini `inPlace: true` bilan sinang.

| # | So'rov (`POST /campaigns/ads/{a}/edit`) | Ads Manager'da | Qaytarish |
|---|---|---|---|
| 2.1 | `GET /campaigns/ads/{a}/edit` (saytli reklama) | `link`, `button`, `urlTags.value` Ads Manager'dagi bilan bir xil. **`urlTags.value` `null` emasligi** | — |
| 2.2 | `button: "SHOP_NOW"` | Yangi reklama, tugmasi «Shop now»; eskisi to'xtagan | Yangi reklamani o'chirish |
| 2.3 | `link: "https://…/boshqa"` | Website URL yangi; tugma ham shu manzilga olib boradi | Yangi reklamani o'chirish |
| 2.4 | faqat `message` o'zgartirish | **URL parameters eski reklamadagidek saqlangan** (asosiy tuzatish) | — |
| 2.5 | `urlTags: "utm_source=meta&utm_medium=test"` | URL parameters aynan shu | — |
| 2.6 | `urlTags: ""` | URL parameters bo'sh | — |
| 2.7 | karusel: `cards` tartibini almashtirish + bitta sarlavha | Kartalar yangi tartibda, sarlavha o'zgargan, rasmlar o'z joyida | Yangi reklamani o'chirish |
| 2.8 | karusel: yangi karta (`picture`) qo'shish, bittasini olib tashlash | Kartalar soni va rasmi to'g'ri; yangi karta birinchi kartaning manziliga boradi | — |
| 2.9 | `inPlace: true` bilan `headline` | O'sha reklama id'si, yangi kreativ, «In review» | — |
| 2.10 | Nusxa olish (`POST /campaigns/ads/{a}/copy`) va yangi reklama qo'shish | Nusxada va yangi reklamada URL parameters saqlangan | Nusxani o'chirish |

**Tekshiriladigan noaniqlik:** `GET /{creative}?fields=url_tags` haqiqatan
qiymatni qaytaradimi; kreativga `url_tags` bilan `object_story_spec` birga
yuborilganda qabul qilinadimi.

## 3-bosqich. Narx chegarasi, attribution, chastota

| # | So'rov | Ads Manager'da | Qaytarish |
|---|---|---|---|
| 3.1 | `GET /campaigns/adsets/{s}/delivery` | `readable: true`; `costCap.value` Ads Manager'dagi bilan bir xil (yo'q bo'lsa `null`) | — |
| 3.2 | `POST …/delivery` `{"costCap": <kunlik byudjetning 1/4 qismi>}` | Bid strategy: Cost per result goal, summa to'g'ri | — |
| 3.3 | `{"costCap": null}` | Bid strategy: Highest volume (chegara yo'q) | — |
| 3.4 | Saytdagi konversiya guruhida `{"attribution": "click_1_view_1"}` | Attribution setting: 1-day click, 1-day view | «Qaytarish» |
| 3.5 | Reach guruhida `{"frequency": {"times": 2, "days": 7}}` | Frequency cap: 2 impressions every 7 days | — |
| 3.6 | Reach guruhida `{"frequency": null}` | Frequency cap olib tashlangan. **Meta bo'sh ro'yxatni qabul qiladimi** | — |
| 3.7 | 3.2 dan keyin «Qaytarish» | Chegara yo'q holatga qaytgan | — |

Saytdagi konversiya yoki reach guruhi bo'lmasa, 3.4–3.6 qoldiriladi va
«sinalmagan» deb belgilanadi.

## 4-bosqich. Nomlar va limitlar

| # | So'rov | Ads Manager'da | Qaytarish |
|---|---|---|---|
| 4.1 | `POST /campaigns/manage/adset/{s}/name` `{"name": "Sinov guruhi"}` | Guruh nomi o'zgargan | «Qaytarish» |
| 4.2 | `POST /campaigns/manage/ad/{a}/name` | Reklama nomi o'zgargan | «Qaytarish» |
| 4.3 | `PATCH /campaigns/{c}` `endsAt: "<10 kundan keyin>"` | End date qo'yilgan | — |
| 4.4 | `PATCH /campaigns/{c}` `endsAt: null` | End date yo'q («Run continuously»). **`end_time=0` qabul qilinadimi** | — |
| 4.5 | Ads Manager'da yaratilgan (bizniki emas) kampaniyada `limit: 500`, keyin `limit: null` | Campaign spending limit qo'yilgan, keyin olib tashlangan. **`922337203685478` qiymati ishlaydimi** | — |

## 6-bosqich. AI chat

Chatda yozing va tugma chiqishini, bosilgach Meta'da o'zgarishni tekshiring:

| # | Chatga | Kutiladi |
|---|---|---|
| 6.1 | «[guruh nomi] guruhini "Yoshlar" deb nomla» | `rename` tugmasi, oldin → keyin to'g'ri; bosilgach nom o'zgaradi |
| 6.2 | «Shu guruhni faqat 18–30 yoshli ayollarga ko'rsat» | `audience` tugmasi; yosh va jins to'g'ri, boshqa sozlamalar saqlangan |
| 6.3 | «Reklamani faqat Instagram'da ko'rsat» | `placement` tugmasi; lid reklamada AI ogohlantiradimi |
| 6.4 | «Bitta lid 2 dollardan qimmat bo'lmasin» | `cost_cap` tugmasi, summa to'g'ri |
| 6.5 | «Reklama matnini "Bugun 20% chegirma" qil» | `advert_text` tugmasi; AI yangi reklama ochilishini aytadi |
| 6.6 | «Budjetni 20% oshir» | AI avval aniq summani aytadi, keyin `budget` tugmasi |
| 6.7 | «Reklamani Samarqandda ham ko'rsat» | Tugma **yo'q**; AI «Reklama sahifasida» deydi |
| 6.8 | Ikki bir xil nomli kampaniya bo'lsa: «Bahor kampaniyasini to'xtat» | AI qaysi biri ekanini so'raydi, taxmin qilmaydi |

Avtomatik tekshiruv: `python -m tools.assistant_eval`.

## Natijani yozish

Har qator uchun: **o'tdi** / **yiqildi** (Meta kodi va matni bilan) /
**sinalmadi** (nega). Yiqilgan qatorlar tuzatilguncha o'sha imkoniyat front'da
ochilmaydi.
