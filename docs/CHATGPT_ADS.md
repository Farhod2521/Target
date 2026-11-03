# ChatGPT Ads — frontend uchun API

Barcha yo'llar `/api/v1/chatgpt` ostida, `Authorization: Bearer <access>` bilan.
Kalitlar camelCase, pul har doim `Money` shaklida:

```json
{"minor": 1250, "currency": "USD", "exponent": 2}   // = 12.50 USD
```

## Qanday ishlaydi

Meta va Google OAuth orqali ulanadi. ChatGPT Ads'da esa mijoz **API kalitni**
o'zi beradi:

1. Mijoz [ads.openai.com/settings](https://ads.openai.com/settings) sahifasida
   kalit yaratadi. Bitta kalit bitta reklama akkauntiga tegishli.
2. Kalitni bizning formaga qo'yadi: `POST /chatgpt/connect`.
3. Backend kalitni OpenAI'da tekshiradi va shifrlab saqlaydi.

Ma'lumot har so'rovda OpenAI'dan **jonli** o'qiladi: bazaga kampaniya yozilmaydi.
Har bir tugma (to'xtatish, byudjet, arxiv, yaratish) bosilganda so'rov OpenAI'ga
darhol ketadi va javob kutiladi.

Sahifalar tartibi:

```
/card ──(ulanmagan)──▶ kalit formasi ──▶ POST /connect
  │
  └─(ulangan)──▶ GET /screen ──▶ GET /campaigns/{id}
                    │
                    └─ «Reklama berish» ──▶ [POST /draft] [GET /places] [POST /images]
                                              └──▶ POST /campaigns
```

## Endpointlar

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/chatgpt/card` | Bo'lim yoqilganmi, akkaunt ulanganmi |
| POST | `/chatgpt/connect` | API kalitni ulash yoki almashtirish |
| POST | `/chatgpt/disconnect` | Kalitni o'chirish |
| GET | `/chatgpt/screen?period=7` | Akkaunt, kampaniyalar, raqamlar |
| GET | `/chatgpt/campaigns/{id}?period=7` | Bitta kampaniya: guruhlar va reklamalar |
| POST | `/chatgpt/switch` | To'xtatish yoki yoqish |
| POST | `/chatgpt/budget` | Kampaniyaning kunlik byudjeti |
| POST | `/chatgpt/archive` | Butunlay to'xtatish (qaytarib bo'lmaydi) |
| GET | `/chatgpt/places?q=tosh` | Hudud qidirish |
| POST | `/chatgpt/images` | Reklama rasmini yuklash (multipart) |
| POST | `/chatgpt/draft` | AI sarlavha, matn va mavzu variantlari |
| POST | `/chatgpt/campaigns` | Yangi kampaniya yaratish |

`period`: `today`, `7` yoki `30`. Default `7`. Kunlar akkaunt vaqt zonasida
hisoblanadi.

### `GET /chatgpt/card`

Har doim `200` qaytaradi. Sidebar'da bo'limni ko'rsatish yoki yashirish shu
javobga qarab hal qilinadi.

```json
{
  "available": true,
  "connected": true,
  "account": {"id": "adacct_1", "name": "Gul do'koni", "currency": "USD", "timezone": "Asia/Tashkent"},
  "dryRun": false,
  "keyHelpUrl": "https://ads.openai.com/settings"
}
```

- `available: false` bo'lsa, bo'limni ko'rsatmang. Qolgan barcha endpointlar
  `404` va `chatgpt_ads_unavailable` qaytaradi.
- `dryRun: true` bo'lsa, sinov rejimi yoqilgan: hech narsa OpenAI'ga
  yuborilmaydi. Ekranda ogohlantirish ko'rsating.

### `POST /chatgpt/connect`

```json
{"apiKey": "sk-..."}
```

Javob `/card` bilan bir xil shaklda. Xatolar:

| Status | `code` | Holat |
|---|---|---|
| 400 | `chatgpt_key_required` | Kalit bo'sh yoki ichida bo'sh joy bor |
| 400 | `chatgpt_key_rejected` | OpenAI kalitni qabul qilmadi |
| 400 | `subscription_required` | Obuna muddati tugagan |
| 409 | `chatgpt_account_taken` | Bu akkaunt boshqa kabinetga ulangan |
| 503 | `chatgpt_unreachable` | OpenAI javob bermadi, qayta urinib ko'ring |

### `GET /chatgpt/screen`

```json
{
  "account": {
    "id": "adacct_1", "name": "Gul do'koni", "currency": "USD", "timezone": "Asia/Tashkent",
    "status": "active", "reviewStatus": "in_review", "reviewLabel": "Tekshiruvda"
  },
  "period": "7", "since": "2026-10-27", "until": "2026-11-02",
  "totals": { "spend": {...Money}, "impressions": 500, "clicks": 20, "conversions": 0, "ctr": "4.00", "cpc": {...Money} },
  "campaigns": [
    {
      "id": "cmpn_1", "name": "Gul", "delivery": "pending", "rawStatus": "active",
      "issues": [{"code": "ad_in_review", "label": "Reklama OpenAI tekshiruvida."}],
      "bidding": "clicks",
      "dailyBudget": {...Money}, "spendCap": null,
      "figures": { ...totals bilan bir xil shakl }
    }
  ],
  "dryRun": false
}
```

- `reviewStatus`: OpenAI'ning brend tekshiruvi (`in_review`, `approved`,
  `rejected`). U `approved` bo'lmaguncha birorta reklama ko'rsatilmaydi.
  Bunday holatni ekranda alohida ko'rsating.
- `delivery`: Meta va Google ekranlaridagi badge so'zlari bilan bir xil
  (`active`, `paused`, `paused_above`, `pending`, `rejected`, `finished`).
- `issues`: OpenAI aytgan sabablar. `label` o'zbekcha matn, uni tayyor holda
  ko'rsatish mumkin.
- `ctr` foizda beriladi (satr ko'rinishida, `"4.00"`). Ko'rsatish bo'lmagan
  bo'lsa `null` keladi. `cpc` — bitta bosish narxi, bosish bo'lmasa `null`.

Ulanmagan bo'lsa: `400` va `chatgpt_not_connected`.

### `GET /chatgpt/campaigns/{id}`

```json
{
  "period": "7", "since": "...", "until": "...",
  "campaign": { ...screen'dagi kampaniya shakli },
  "locations": {
    "countries": ["UZ"],
    "placeIds": ["2001959"],
    "places": [{"id": "2001959", "name": ""}]
  },
  "groups": [
    {
      "id": "adgrp_1", "name": "...", "delivery": "active", "issues": [],
      "contextHints": ["tug'ilgan kunga gul"], "strategy": "maximize_clicks",
      "figures": {...},
      "ads": [
        {
          "id": "ad_1", "name": "...", "delivery": "active", "reviewStatus": "approved",
          "issues": [], "title": "...", "body": "...", "targetUrl": "https://...",
          "imageUrl": "https://...", "figures": {...}
        }
      ]
    }
  ]
}
```

`locations` — kampaniya qayerda ko'rsatilishi. Shakli `POST /campaigns` dagi
`countries` va `placeIds` bilan bir xil, shuning uchun «Nusxa olish»da ularni
formaga to'g'ridan-to'g'ri qo'yish mumkin. `places[].name` bo'sh kelishi
mumkin: OpenAI ba'zan faqat id qaytaradi.

### «Ulanishlar» sahifasi: `GET /connections`

`/connections` javobida Google kartasi yonida `chatgpt` kartasi bor. Bu javob
snake_case'da keladi:

```json
"chatgpt": {
  "chatgpt_ads_on": true,
  "connection": {"id": "...", "provider": "chatgpt", "status": "active", ...},
  "connected": true,
  "account": {"external_id": "adacct_1", "name": "Gul do'koni", "currency": "USD", ...},
  "dry_run": false
}
```

- `chatgpt_ads_on: false` bo'lsa, kartani ko'rsatmang.
- `connection: null` bo'lsa, kalit hech qachon ulanmagan.
- `connected: false` va `connection.status` `revoked` bo'lsa, kalit uzilgan.
- Ulash va uzish tugmalari ChatGPT ekraniga olib boradi (`/chatgpt/connect`,
  `/chatgpt/disconnect`).

### Tugmalar: `/switch`, `/budget`, `/archive`

```json
POST /chatgpt/switch   {"level": "campaign", "id": "cmpn_1", "wanted": "pause"}
POST /chatgpt/budget   {"id": "cmpn_1", "budget": {"minor": 2500, "currency": "USD", "exponent": 2}}
POST /chatgpt/archive  {"level": "ad", "id": "ad_1"}
```

- `level`: `campaign`, `adset` (ad group) yoki `ad`. `wanted`: `pause` yoki
  `resume`.
- Byudjet faqat kampaniyada turadi.
- Arxivlashni qaytarib bo'lmaydi. Bosishdan oldin tasdiqlash oynasini
  ko'rsating.

Javob:

```json
{"message": "ChatGPT Ads'ga yuborildi. To'xtatildi.", "dryRun": false}
```

Javob kelgach `/screen`ni qayta o'qing.

### `GET /chatgpt/places?q=tosh`

```json
[{"id": "3000194", "name": "Tashkent", "canonicalName": "Tashkent,Uzbekistan", "type": "city", "countryCode": "UZ"}]
```

Tanlangan joyning `id` qiymatini `POST /campaigns` dagi `placeIds` ga
qo'shing. Butun davlatni tanlash uchun `countries` ga ISO kod yuboriladi
(`UZ`, `KZ`).

### `POST /chatgpt/images`

`multipart/form-data`, maydon nomi `file`. JPEG, PNG yoki WebP, 8 MB gacha.
OpenAI kamida 640×640 o'lchamni so'raydi.

```json
{"fileId": "file_abc", "dryRun": false}
```

Sinov rejimida `fileId` bo'sh keladi. Bu holda kampaniya rasmsiz yaratiladi.
Xato bo'lsa: `400` va `chatgpt_image_refused`.

### `POST /chatgpt/draft` — «AI yozib bersin»

```json
{"targetUrl": "https://gul.uz"}
```

Matn biznes profilidan yoziladi. Javob 10–30 soniyada keladi, shu vaqt davomida
spinner ko'rsating.

```json
{"titles": ["...", "..."], "bodies": ["...", "..."], "contextHints": ["...", "..."]}
```

Har bir variant OpenAI cheklovlariga allaqachon moslangan. Mijoz bitta
sarlavha va bitta matnni tanlaydi, mavzulardan esa bir nechtasini. Xato
bo'lsa: `503` va `chatgpt_draft_failed`. Bu holda mijoz matnni o'zi yozishi
mumkin.

### `POST /chatgpt/campaigns`

```json
{
  "name": "Gul yetkazib berish",
  "dailyBudget": {"minor": 1000, "currency": "USD", "exponent": 2},
  "title": "Toshkentda gul yetkazish",
  "body": "Bir soatda eshigingizgacha. Buyurtma bering.",
  "targetUrl": "https://gul.uz",
  "countries": ["UZ"],
  "placeIds": [],
  "contextHints": ["tug'ilgan kunga gul sovg'a"],
  "maxBid": null,
  "fileId": "file_abc",
  "imageUrl": "",
  "startActive": true,
  "requestId": "9b2f0c7e-..."
}
```

| Maydon | Qoida |
|---|---|
| `title` | 3–50 belgi |
| `body` | 1–100 belgi |
| `targetUrl` | `https://` bilan boshlanadi. OpenAI saytni ocha olishi kerak |
| `countries` / `placeIds` | Kamida bittasi bo'lishi shart |
| `contextHints` | 20 tagacha, har biri 300 belgigacha |
| `dailyBudget` | Kamida 1 birlik (masalan, 1 USD) |
| `maxBid` | Ixtiyoriy. Bo'sh bo'lsa, narxni OpenAI o'zi tanlaydi (maximize clicks) |
| `requestId` | Har bir forma uchun bitta UUID yarating. Tugma qayta bosilsa ham ikkinchi kampaniya yaratilmaydi |

Javob (`201`):

```json
{
  "message": "Kampaniya yaratildi. Reklama OpenAI tekshiruvidan o'tgach ko'rsatiladi.",
  "dryRun": false, "campaignId": "cmpn_9", "adGroupId": "adgrp_9", "adId": "ad_9",
  "reviewStatus": "in_review", "active": true, "sent": {}
}
```

Sinov rejimida `dryRun: true` keladi, `sent` maydonida esa OpenAI'ga nima
yuborilishi kerak bo'lgani ko'rsatiladi.

Maydon xatosi (`422`, `invalid_input`):

```json
{"detail": "Sarlavha 3-50 belgi bo'lsin.", "code": "invalid_input", "problems": {"title": "Sarlavha 3-50 belgi bo'lsin."}}
```

`problems` kalitlari: `name`, `dailyBudget`, `title`, `body`, `targetUrl`,
`countries`, `contextHints`, `maxBid`.

## OpenAI rad etganda

Har bir tugma va o'qish uchun javob shakli bir xil: `422`,
`code: "provider_refused"` va ichida `refusal` dialogi. Bu Meta tugmalaridagi
rad etish oynasi bilan bir xil shakl, shuning uchun o'sha komponentni qayta
ishlatsa bo'ladi.

```json
{
  "detail": "...", "code": "provider_refused",
  "refusal": {
    "key": "chatgpt:404", "retryable": false,
    "title": "ChatGPT Ads o'chirishni rad etdi",
    "cause": "Bu obyekt ChatGPT Ads'da topilmadi...",
    "steps": ["Sahifani yangilang."],
    "providerWords": "OpenAI'ning o'z izohi",
    "retryAfterSeconds": null
  }
}
```

`retryable: true` bo'lsa, so'rovlar soni chegaradan oshgan bo'ladi.
`retryAfterSeconds` soniya kutib, qayta urinib ko'ring.
