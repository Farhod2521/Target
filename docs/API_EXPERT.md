# Expert mode: Reklama jadvali API

Expert mode'dagi Reklama jadvali uchun. Hamma metrika backendda,
`core/metrics/catalogue` da hisoblanadi. Front hech narsani hisoblamaydi:
qiymatni formatlaydi, `missing` bo'lsa `–` va sababini ko'rsatadi.

Avtorizatsiya: `Authorization: Bearer <access_token>`.

## Endpoint'lar

| So'rov | Nima qaytaradi |
|---|---|
| `GET /api/v2/campaigns/expert` | 3 daraja qatorlari va kataklari, har daraja uchun Jami, davr, yangilanish vaqti, attribution |
| `GET /api/v2/campaigns/expert/columns?network=meta` | Har daraja ustunlari, tanlangan ustunlar, tayyor to'plamlar, `missing` sabablarining matni |
| `PUT /api/v2/campaigns/expert/columns` | `{"chosen": ["spend", "cpm", ...]}` tanlovni va tartibni saqlaydi, javobi `GET` bilan bir xil |

`/expert` ning query parametrlari `/manager` niki bilan bir xil: `period`
(`today`, `7d`, `30d`, `90d`, `custom`), `since`, `until`, `status`, `source`,
`network`.

## `GET /api/v2/campaigns/expert`

```json
{
  "campaigns": [ExpertRow],
  "adsets": [ExpertRow],
  "ads": [ExpertRow],
  "totals": {
    "campaigns": {"count": 4, "currency": "USD", "cells": {...}},
    "adsets": {...},
    "ads": {...}
  },
  "range": {"since": "2026-10-30", "until": "2026-11-05"},
  "syncedAt": "2026-11-05T09:40:12Z",
  "attribution": {"asked": "7d_click_1d_view", "differs": false}
}
```

**ExpertRow:** `/manager` qatoridagi maydonlarning o'zi (`level`, `id`,
`campaignId`, `name`, `status`, `budget`, `controls`, `problem`, `refusal`,
`rejection` va boshqalar), lekin eski raqamlarsiz (`results`, `unitCost`,
`spent`, `impressions`, `reach`, `clicks` yo'q). Ularning o'rniga:

- `outcome`: kampaniya maqsadi (`lead`, `site_lead`, `chat`, `call`,
  `click`, `view`, `recall`, `profile`, `none`).
- `currency`: pul kataklarining valyutasi.
- `cells`: metrika kaliti bo'yicha `{"value": ..., "missing": ...}`.

**Katak qiymati** ustunning `unit` iga qarab:

| `unit` | `value` | Misol |
|---|---|---|
| `money` | Valyutaning minor birligi (tiyin, sent) | `8870` → 88.70 USD |
| `count` | Butun son | `64987` |
| `percent` | Foiz, 2 xona | `8.44` → 8.44% |
| `ratio` | Nisbat, 2 xona | `1.62` (Chastota, ROAS) |
| `ranking` | Meta so'zi | `below_average_20` |

`value: null` bo'lsa, `missing` da sabab turadi. Matni
`/expert/columns` dagi `missing` lug'atida.

**Darajalar:** kampaniya va guruhda bir xil ustunlar. Reklamada qo'shimcha
`hook_rate`, `hold_rate`, `quality_ranking`, `engagement_rate_ranking`,
`conversion_rate_ranking` bor. Kataklar faqat shu darajada bor ustunlar
uchun keladi.

**Jami:** yig'indilardan qayta hisoblanadi. Qamrov, noyob kliklar va
chastota bitta qatordan ortiq bo'lsa `not_asked` qaytadi, chunki odamlar
sonini qo'shib bo'lmaydi. Maqsadlar har xil bo'lsa, natijaga bog'liq ustunlar
`mixed_goals`. Valyutalar har xil bo'lsa, pul ustunlari `mixed_currency`.

**`attribution.differs: true`:** hisoblardan biri Ads Manager'da boshqa
attribution oynasiga sozlangan. Uning lid sonlari Ads Manager'dagidan farq
qiladi, jadval tepasida ogohlantirish chiqishi kerak.

## `missing` sabablari

| Kalit | Matn |
|---|---|
| `not_read` | Meta hali bu kunlarni o'qimagan |
| `not_asked` | Bu davr uchun Meta'dan hali so'ralmagan |
| `no_base` | Hisoblash uchun ma'lumot yo'q |
| `no_spend` | Bu davrda sarf yo'q |
| `no_link` | Xabar kampaniyasida havola yo'q |
| `not_video` | Rasmli reklama, video yo'q |
| `few_impressions` | Meta 500 ko'rsatishdan keyin baholaydi |
| `other_goal` | Bu kampaniya maqsadiga tegishli emas |
| `uncounted` | Bu maqsadning natijasi bu yerda sanalmaydi |
| `not_here` | Bu darajada yoki tarmoqda bunday ko'rsatkich yo'q |
| `no_crm` | CRM yoqilmagan |
| `mixed_goals` | Maqsadlari har xil, natijalarni qo'shib bo'lmaydi |
| `mixed_currency` | Valyutalari har xil, pulni qo'shib bo'lmaydi |

## `GET /api/v2/campaigns/expert/columns`

```json
{
  "levels": {
    "campaigns": [{"key": "spend", "label": "Sarflandi", "hint": "...", "group": "money",
                   "unit": "money", "lowerIsBetter": false, "norm": ""}],
    "adsets": [...],
    "ads": [...]
  },
  "chosen": ["spend", "results", "..."],
  "presets": [{"key": "general", "label": "Umumiy", "columns": ["spend", "..."]}],
  "missing": {"no_crm": "CRM yoqilmagan", "...": "..."}
}
```

- `levels.*`: ustunlar jadvaldagi tartibda.
- `chosen`: foydalanuvchi tanlagan ustunlar va tartibi. Hali saqlanmagan
  bo'lsa, hammasi.
- `presets`: Umumiy, Video, Lid sifati, Sotuv.
- `hint` va `norm`: ustun izohi uchun. Masalan, Hook rate uchun
  "25–30% va undan yuqori".
- `lowerIsBetter`: o'zgarish rangini tanlash uchun.

`Holati` ustuni katalogda yo'q: u qatorning `status` maydoni.
