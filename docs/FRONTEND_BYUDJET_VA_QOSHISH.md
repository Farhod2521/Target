# Byudjet darajasi va yangi guruh/reklama: frontni ulash

Barcha yo'llar `/api/v1` ostida, javoblar camelCase.

## 1. Launch tahriri: «Byudjet» bo'limi

`GET /launch/drafts/{id}/edit` javobiga `budget` qo'shildi:

```json
{ "budget": { "level": "campaign", "sharing": false, "locked": false } }
```

| Maydon | Ma'nosi |
|---|---|
| `level` | `campaign` (CBO, sukut bo'yicha) yoki `adset` (ABO) |
| `sharing` | Faqat `adset`da: guruhlar byudjetining 20% gacha qismini bir-biriga bera oladi |
| `locked` | `true`: launch yaratilgan, bo'lim faqat o'qiladi |

Saqlash o'sha `PUT /launch/drafts/{id}/edit` orqali. `budget` boshqa bo'limlar bilan birga yuboriladi.

- `say.budget` ham bor, hozircha bo'sh qator.
- `level: "campaign"` bilan `sharing: true` rad etiladi: UI'da `sharing` faqat `adset` tanlanganda ko'rinsin.
- `sharing` keyin yoqilmaydi: Meta ishlayotgan kampaniyada buni qabul qilmaydi, shuning uchun tanlov launch'da beriladi.
- Bo'lim tegilmasa, launch CBO bo'lib yaratiladi. Saqlangan `ad_groups`i bor eski draft ABO'da qoladi.

Launch kartasi uchun `proposal.budget`da ham `level` va `sharing` bor.

## 2. Targetolog rejimi: yangi guruh

Guruh tanlangan guruhning nusxasi: maqsad, auditoriya, joylashuv, atribusiya va bid sozlamasi ko'chadi. U doim **to'xtatilgan** holatda yaratiladi. Auditoriyani keyin mavjud `GET /campaigns/{id}/edit?group={externalId}` dialogida o'zgartirish mumkin.

`GET /campaigns/{id}/adsets/new`

```json
{
  "campaign": { "id": "...", "name": "..." },
  "network": { "...": "..." },
  "budgetAt": "adset",
  "currency": "USD",
  "minBudget": 1.0,
  "groups": [{ "externalId": "123", "name": "Guruh" }]
}
```

`POST /campaigns/{id}/adsets` javobi `202 { "actionId": "..." }`

```json
{ "name": "Yangi guruh", "source": "123", "dailyBudget": 12.5 }
```

- `source`: ixtiyoriy, bo'sh bo'lsa kampaniyaning birinchi guruhi.
- `dailyBudget`: `budgetAt: "adset"`da majburiy, `"campaign"`da yuborilmaydi.

## 3. Targetolog rejimi: yangi reklama

Reklama mavjud reklamaning nusxasi: sahifa, havola, tugma va forma ko'chadi. Doim **to'xtatilgan** holatda yaratiladi. Yangi guruhda hali reklama bo'lmasa, shu kampaniyadagi boshqa reklama asos bo'ladi.

`GET /campaigns/adsets/{externalId}/ads/new`: `GET /campaigns/ads/{id}/edit` javobi bilan bir xil shakl, yana:

| Maydon | Ma'nosi |
|---|---|
| `externalId` | Asos reklama. `POST`da `source` sifatida yuboriladi |
| `group` | Reklama tushadigan guruh |
| `name` | Taklif qilinadigan nom |
| `warnsLearning` | `true`: reklama qo'shilsa guruhning o'rganishi qayta boshlanadi, ogohlantiring |
| `canSwap` | `false`: asos reklama post asosida, faqat aynan nusxa olinadi. Matn, rasm va forma maydonlarini ko'rsatmang va yubormang |

`POST /campaigns/adsets/{externalId}/ads` javobi `202 { "actionId": "..." }`

```json
{
  "name": "Yangisi",
  "source": "456",
  "message": "Matn",
  "headline": "Sarlavha",
  "description": "",
  "picture": "library qatori id",
  "leadForm": "forms.options id"
}
```

`message`, `headline`, `description`: yuborilmasa asosdagi qator qoladi, `""` bo'lsa olib tashlanadi. `picture` va `leadForm` yuborilmasa asosdagisi qoladi.

## 4. Natijani kuzatish

Ikkala `POST` ham o'zgarishni ochadi. Holat `GET /campaigns/actions/{actionId}` orqali kuzatiladi: `pending`, `applied`, `failed`. Meta rad etsa, sabab shu javobda keladi. `action`: `create_adset` yoki `create_ad`. Yangi qator mirror'ga darhol tushadi.

| `code` | Qachon |
|---|---|
| `campaign_holds_budget` | CBO kampaniyada guruhga byudjet yuborilgan |
| `group_budget_needed` | ABO kampaniyada byudjet yuborilmagan |
| `invalid_input` | `problems.dailyBudget`: byudjet noto'g'ri yoki `minBudget`dan past |
| `campaign_finished` | Kampaniya tugagan |
| `addition_not_offered` | Tarmoq Meta emas: tugmani ko'rsatmang |
| `lifetime_budget_campaign` | `budgetAt: "lifetime"`: guruh yaratilmaydi, formani ochmang. Reklama qo'shish ishlaydi |
| `nothing_to_copy` | Kampaniyada guruh yo'q |
| `creative_not_editable` | Kampaniyada nusxa olinadigan reklama yo'q, yoki `canSwap: false` bo'lganda matn, rasm yoki forma yuborilgan |
| `change_in_flight` | Shu obyektda oldingi yaratish hali tugamagan |
