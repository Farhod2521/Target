# «Backend so'rovlari 18.11» — A bo'limi javoblari

A1–A4 backendda tuzatildi. Hamma yangi maydonlar qo'shimcha: eski maydonlar
o'z joyida qoldi, shuning uchun hozirgi front buzilmaydi.

---

## A1. Video reklama endi «image» bo'lib kelmaydi

`GET /campaigns/{id}` → `ads[].format` endi kreativning o'zidan aniqlanadi:
`video_data` bloki, kreativning `video_id` si yoki Meta'ning `object_type: VIDEO`.
Boost qilingan video post va reel ham `"video"` bo'ladi.

- Allaqachon video ekani ma'lum bo'lgan reklamalar migratsiyadan keyin
  darhol to'g'ri chiqadi. Boost qilingan video postlar esa akkauntning
  keyingi sync'idan keyin to'g'rilanadi (sync har 30 daqiqada).
- Frontdagi aylanma yo'lni (`creatives` hisobotida `watch` bor reklamani video
  deb olish) olib tashlasa bo'ladi.

## A2. CRM kartasida kreativ rasmi

`GET /crm/cards/{id}` → `source` ga ikki maydon qo'shildi:

| Maydon | Qiymat |
|---|---|
| `source.thumb_url` | Kreativ rasmi (Meta'ning havolasi) yoki `""` |
| `source.format` | `"image"`, `"video"` yoki `""` (kreativ hali sync bo'lmagan) |

- Rasm havolasi Meta'niki, vaqt o'tib eskirishi mumkin. Rasm yuklanmasa,
  oddiy reklama ikonkasini ko'rsating.
- Ulanmagan akkauntdagi reklama uchun `source` avvalgidek `null` keladi.
- Endi reklama nomi ustiga kelinganda `/campaigns/ads/{id}/preview` ni
  chaqirish shart emas.

## A3. «Reklama berish» doim yangi qoralama ochadi

`POST /launch/drafts`:

| `resume` | Natija |
|---|---|
| qoralama id si | O'sha qoralama ochiq bo'lsa, o'shani qaytaradi |
| `null` | `draft` statusidagi eski qoralama o'chiriladi va yangisi ochiladi |

- Tarmoqqa yuborilgan launch (`building`, `ready`, `failed`, `rolled_back`)
  o'chirilmaydi va qaytariladi — uning sahifasi launch qanday o'tganini
  ko'rsatadi. Bu frontdagi hozirgi qoida bilan bir xil.
- 24 soat tegilmagan `draft` qoralamalar har soatda serverda o'chiriladi.
- `Start.tsx` dagi `openFresh` aylanmasi (discard qilib qayta so'rash) endi
  shart emas: `startDraft(flow, null)` yetarli.

## A4. Office matnlari uchun kodlar

Har bir o'zbekcha label yonida endi barqaror kod bor. Front matnni kod
bo'yicha o'zi tarjima qiladi; o'zbek interfeysida label'ni o'zini ko'rsatsa
ham bo'ladi.

### Doska ustunlari

`GET /api/v2/office/boards/{board}/columns` va doska ko'rinishi:

| Maydon | Ma'nosi |
|---|---|
| `code` | Ustun kodi (o'zgarmaydi) |
| `name` | Ustun nomi |
| `is_default_name` | `true` — standart nom: ru/en'da `code` bo'yicha tarjima qiling. `false` — ofis nomini o'zgartirgan: `name` ni o'zgarishsiz ko'rsating |

### Allaqachon kodi bo'lgan joylar (o'zgarmadi)

| Joy | Kod | Label |
|---|---|---|
| Doska | `code` | `label` |
| Karta tarixi («Lid ochildi» va b.) | `kind` | `label` |
| Karta harakatlari | `value` | `label` |
| Qo'ng'iroq yo'nalishi («Kiruvchi») | `direction` | `direction_label` |
| Karta issiqligi | `level` | `label` |
| Sabab chiplari | `code` | `label` |

### Yangi qo'shilgan kodlar

| Javob (schema) | Yangi maydon | Label | Qiymatlar |
|---|---|---|---|
| `AdRowOut` (mijoz reklamalari ro'yxati) | `result_kind` | `result_word`, `result_cost_label` | `lead`, `site_lead`, `chat`, `call`, `click`, `view`, `recall`, `profile` |
| `AdResultOut` (`figures.result`) | `kind` | `label`, `cost_label` | o'sha; natija sanalmasa `""` |
| `AdCampaignOut` | `delivery` | `delivery_label` | `active`, `paused`, `pending`, `billing`, `rejected`, `finished`, ... |
| `AdGroupOut` | `delivery` | `delivery_label` | o'sha |
| `AdLineOut` | `delivery` | `delivery_label` | o'sha |
| `AdPostOut` (`live.ads[].post`) | `kind` | `kind_label` | `image`, `video`, `post`, `ig_image`, `ig_video`, `facebook_post` |
| `LaunchAdOut` (`settings.ads[]`) | `media_kind` | `media_kind_label` | `image`, `video`, `post`, `upload`, `ig_image`, `ig_video` |
| `FormQuestionOut` | `kind` | `kind_label` | `autofilled`, `options`, `open` |
| `FormSetupOut` | `depth` | `depth_label` | `short`, `deep` |
| `PayoutMoneyOut` (va undan olinganlar) | `method` | `method_label` | to'lov usuli kodi |
| `ClientBillOut` (mijoz kartasidagi hisoblar) | `kind` | `kind_label` | `plan`, `pages`, `seats`, ... |

### Tarjima qilinmaydigan matnlar

Bular odam yozgan yoki AI yozgan matn, kodi yo'q va bo'lmaydi:
`HistoryOut.body`, `note`, muammo tavsifi (`problem`, `what`), savol matni
(`FormQuestionOut.label`), so'rovnoma variantlari.
