# Reklama → Sotuv ko'rsatkichlari — frontend uchun

Backend: `feat/crm-sales-metrics` shoxi, migratsiyalar `0072`–`0073`. Avval backend deploy qilinadi.
Valyuta tanlash alohida hujjatda: [FRONTEND_CRM_VALYUTA.md](FRONTEND_CRM_VALYUTA.md).

Maqsad: marketing (sarf, lid) va sotuv (CRM) raqamlarini bitta joyda ko'rsatish —
**sarflandi, daromad, ROAS, CAC, konversiya, bitim muddati**. Hamma hisob backendda, bitta joyda.
Frontda **hech qanday formula yozilmaydi**: kelgan qiymat ko'rsatiladi, xolos.

Eski front yangi backend bilan buzilmaydi: eski maydonlar joyida, yangilari qo'shildi.

## 1. Qayerdan keladi

| Sahifa | So'rov | Maydon | Nima bor |
|---|---|---|---|
| CRM → Statistika | `GET /api/v1/crm/stats` | `sales` | jami + kesimlar (kampaniya, reklama, menejer, kun) |
| CRM → Statistika | `GET /api/v1/crm/stats` | `process` | sotuv jarayoni: har ustun hozir va kartalar unda qancha turadi |
| Dashboard (oddiy) | `GET /api/v1/metrics/numbers` | `sales` | faqat jami |
| Dashboard (Expert) | `GET /api/v1/metrics/expert` | `sales` | faqat jami |

Uch joydagi `sales.totals` **bir xil hisobdan** chiqadi: bir davr uchun raqamlar aynan teng.
Dashboardda `sales` ekrandagi juftlik (sahifa + akkaunt) uchun; juftlik yo'q bo'lsa `null`.
CRM menejeri Dashboardni ko'rmaydi, `/crm/stats` faqat egasiga ochiq (avvalgidek).

## 2. `sales` bloki

```json
{
  "state": "on",
  "currency": "UZS",
  "range": {"since": "2026-10-22", "until": "2026-11-20", "days": 30},
  "metrics": [
    {"key": "roas", "label": "ROAS", "hint": "Daromad ÷ Sarflandi. ...", "unit": "ratio", "lower_is_better": false}
  ],
  "missing_words": {"no_sales": "CRM'da hali sotuv yopilmagan", "no_crm": "CRM yoqilmagan"},
  "totals":  {"spend": {"value": 18000000, "missing": null}, "roas": {"value": 3.33, "missing": null}},
  "earlier": {"spend": {"value": 0, "missing": null}, "roas": {"value": null, "missing": "no_base"}},
  "completeness": {"level": "low", "handled_pct": 33, "closed_pct": 33, "open": 2, "note": "2 ta lid hali ko'rib chiqilmagan. ..."},
  "left_out": {"sales": 0, "spend_days": 0}
}
```

`/crm/stats` da shu blokka qo'shimcha: `campaigns[]`, `ads[]`, `managers[]`, `daily[]` (4-band).

### Katak (cell)

Har bir ko'rsatkich — katak: `{"value": ..., "missing": ...}`. Ikkisidan **bittasi** to'ladi.

- `value` bor → ko'rsating.
- `value: null` → «–» chizing, yonida/tooltipda `missing_words[missing]` matnini bering.
  **Hech qachon 0 deb chizmang**: «sotuv yopilmagan» nol daromad emas.

### Ko'rsatkichlar (`metrics[]` tartibida chizing)

| `key` | Nomi | `unit` | Izoh |
|---|---|---|---|
| `spend` | Sarflandi | `money` | CRM'ga lid beradigan reklamalar sarfi |
| `revenue` | Daromad | `money` | Shu davr lidlaridan yopilgan sotuvlar |
| `roas` | ROAS | `ratio` | Daromad ÷ Sarf |
| `cac` | Mijoz narxi (CAC) | `money` | Sarf ÷ Sotuvlar |
| `cpl` | Lid narxi | `money` | Sarf ÷ Lidlar |
| `cpql` | Sifatli lid narxi | `money` | Sarf ÷ Sifatli lidlar |
| `leads` | Lidlar | `count` | |
| `qualified` | Sifatli lidlar | `count` | |
| `sales` | Sotuvlar | `count` | |
| `conversion` | Konversiya | `percent` | Sotuvlar ÷ Lidlar |
| `qualified_share` | Sifatli lid % | `percent` | |
| `close_rate` | Yopish darajasi | `percent` | Sotuvlar ÷ Sifatli lidlar |
| `avg_deal` | O'rtacha chek | `money` | |
| `deal_time` | Bitim muddati | `minutes` | lid kelganidan sotuvgacha, mediana |
| `first_response` | Birinchi javob | `minutes` | lid kelganidan menejer olguncha, mediana |

Nom va izohni **backenddan** oling (`label`, `hint`), frontda qotirmang.

### Birliklar (`unit`)

| `unit` | Qiymat | Ko'rsatish |
|---|---|---|
| `money` | butun son, `currency` ning minor birligida (so'm uchun ÷100) | `formatMoney(value, sales.currency)` |
| `count` | butun son | |
| `percent` | ikki xonali son (`33.33`) | `33,3%` |
| `ratio` | ikki xonali son (`3.33`) | `3,33×`. Oddiy rejimda: «1 so'mga 3,33 so'm qaytdi» |
| `minutes` | butun daqiqalar | 60 dan kam — «45 daq», 48 soatgacha — «5 soat», undan ko'p — «3 kun» |

**Muhim:** bu blokdagi hamma pul `sales.currency` da (CRM valyutasi), reklama akkaunti
valyutasida emas. Dashboardning qolgan qismi akkaunt valyutasida (masalan USD) bo'lishi mumkin —
`sales` blokini o'z valyutasi bilan chizing, ikkalasini aralashtirmang.

`lower_is_better: true` (CAC, lid narxi, muddatlar) — o'sish yomon, kamayish yaxshi rangda.

### `missing` sabablari

| Kod | Qachon |
|---|---|
| `no_crm` | CRM yoqilmagan yoki sozlanmagan — hamma katak shu |
| `no_sales` | Lid bor, lekin CRM'da hali birorta sotuv yopilmagan: daromad, ROAS, CAC, o'rtacha chek, bitim muddati |
| `no_spend` | Bu davrda sarf yo'q: ROAS, CAC, lid narxlari |
| `no_base` | Bo'ladigan narsa yo'q (lid yo'q, sifatli lid yo'q) |
| `not_here` | Bu kesimda bunday ko'rsatkich yo'q: menejerning o'z sarfi bo'lmaydi |

Matnni `missing_words` dan oling.

### `state`

`on` — ishlayapti; `off` — o'chirilgan; `draft` — sozlanmagan. `on` bo'lmasa hamma katak
`no_crm`: blok o'rnida «CRM'ni yoqing» chaqirig'ini ko'rsating (`/app/crm/`).

### `completeness` — raqamlarga qanchalik ishonish mumkin

| `level` | Ma'nosi | Frontda |
|---|---|---|
| `off` | CRM yoqilmagan | CRM'ni yoqish chaqirig'i |
| `empty` | Bu davrda CRM'ga lid tushmagan | bo'sh holat |
| `low` | Lidlarning yarmidan kami ko'rib chiqilgan | **sariq ogohlantirish**: `note` matni + «CRM'ni ochish» tugmasi. Raqamlar ko'rsatiladi, lekin «to'liq emas» belgisi bilan |
| `ok` | Yetarli | `note` bo'sh bo'lmasa kichik izoh sifatida |

`handled_pct` — ko'rib chiqilgan lidlar ulushi, `closed_pct` — yopilganlari (sotildi, rad, sifatsiz),
`open` — hali ishlanayotgan lidlar soni. Uchalasini kichik progress qatori qilib ko'rsatish mumkin.

### `earlier`

Xuddi shuncha kun oldingi davr, xuddi shu hisob bilan (bir kunlik davrda `null`).
O'zgarish foizini front hisoblamaydi deb kelishilgan bo'lsa ham, bu yerda ikkala qiymat ham
katak bo'lgani uchun farqni ko'rsatish oson: ikkalasida `value` bo'lsagina solishtiring.

### `left_out`

- `sales` — boshqa valyutada yopilgan, o'sha kun kursi topilmagan sotuvlar soni (daromadga kirmagan).
- `spend_days` — sarfi kurs topilmagani uchun qo'shilmagan kunlar soni.

Ikkalasi odatda `0`. Noldan katta bo'lsa, tegishli raqam yonida izoh bering.

## 3. Hisob qoidalari (foydalanuvchiga tushuntirish uchun)

- **Bir guruh odam.** Lidlar — shu davrda kelganlari; sifatli, sotuv, daromad — **o'sha lidlarniki**,
  sotuv qachon yopilganidan qat'i nazar. 3-sanada kelgan lid 20-sanada sotilsa, u 3-sana lidining sotuvi.
  Shuning uchun oxirgi kunlar past ko'rinadi: lidlar hali ishlanmoqda (`completeness.open`).
- **Qaysi sarf.** Shu CRM'ga lid bergan kampaniyalarning reklamalari. Pul sarflab lid bermagan
  reklama ham kiradi. Xabar, qamrov kabi natijasi CRM'ga tushmaydigan kampaniyalar **kirmaydi** —
  shuning uchun bu sarf Dashboarddagi «Jami sarflandi»dan kichik bo'lishi mumkin.
- **Valyuta.** Sarf har kunning Markaziy bank kursi bilan CRM valyutasiga o'tkaziladi.
- **Kun.** Reklama akkauntining vaqt mintaqasi bo'yicha (`/crm/stats` → `range.time_zone`).
- **«Sifatli»** — sotilgan yoki sifatli ustunga o'tib hali ochiq turgan lid. Sifatli bo'lib,
  keyin rad etilgani sanalmaydi (boshqa hamma joydagi qoida bilan bir xil).

## 4. Kesimlar (`/crm/stats` → `sales`)

```json
"campaigns": [{"id": "1202...", "name": "Sahifa - Lid - 12.11", "cells": {...}}],
"ads":       [{"id": "1203...", "name": "Video 1", "cells": {...}}],
"managers":  [{"user": {"id": "...", "full_name": "Ali", "email": "..."}, "cells": {...}, "late": 2}],
"daily":     [{"day": "2026-11-20", "cells": {...}}]
```

- `cells` — 2-banddagi kataklarning o'zi, o'sha kalitlar bilan.
- `campaigns`, `ads` — eng ko'p lid keltirganlari tepada, 20 tagacha. Lid keltirmay pul sarflagan
  reklama ham ro'yxatda turadi (`leads: 0`, `cpl: no_base`) — bu foydali signal.
- `managers` — menejerda sarfga bog'liq kataklar `not_here`: ustunlarni yashiring
  (sarf, ROAS, CAC, lid narxi). `late` — muddati o'tgan ochiq kartalari.
- `daily` — davrning har kuni, bo'sh kunlar ham. Grafik uchun: sarf va daromad, yoki lidlar va sotuvlar.

## 5. Sotuv jarayoni (`/crm/stats` → `process`)

Doskaning har bir ustuni uchun bitta qator, doska tartibida:

```json
{
  "stage": {"id": "...", "name": "Jarayonda", "kind": "open", "color": "#..."},
  "now": 115, "late": 1,
  "waiting_min": 13268, "longest_wait_min": 38970,
  "stay_min": 162, "stays": 49,
  "approximate": true
}
```

| Maydon | Ma'nosi |
|---|---|
| `now` | Hozir shu ustunda turgan kartalar |
| `late` | Ulardan muddati o'tganlari |
| `waiting_min` | Hozir turgan kartalar qancha vaqtdan beri turibdi (mediana). Yopiq ustunlarda (`won`, `lost`, `junk`) `null` |
| `longest_wait_min` | Eng uzoq turgan karta |
| `stay_min` | Davr ichida shu ustundan chiqib ketgan kartalar unda qancha turgan (mediana). `stays` — nechta shunday holat |
| `approximate` | `true` — vaqtlarning bir qismi eski tarix yozuvlaridan tiklangan, aniq o'lchanmagan. Kichik «taxminan» belgisi qo'ying |

Ikki vaqtni aralashtirmang: `waiting_min` — **hozirgi** navbat («kartalar qayerda tiqilib qoldi»),
`stay_min` — ustunning **odatdagi** tezligi. Eng foydali ko'rinish: ustunlar qatori, har birida
`now` soni va `waiting_min`; `waiting_min` katta ustun qizil bilan ajratiladi.

Vaqt formatlash 2-banddagi `minutes` qoidasi bilan.

Voronka (`funnel`), rad sabablari (`reasons`), ochiq va muddati o'tgan kartalar (`totals.open`,
`totals.late`) — avvalgidek, o'zgarmadi.

## 6. Eski maydonlar

`/crm/stats` dagi `totals`, `managers`, `ads`, `daily`, `funnel`, `reasons` o'z joyida.
Farqi:

- `qualified` endi 3-banddagi qoida bilan sanaladi (rad etilgan lid sifatli hisoblanmaydi).
- Kunlar akkaunt vaqt mintaqasida; `range.time_zone` shu mintaqani qaytaradi.

Yangi dizaynda eski `totals.*` o'rniga `sales.totals` kataklaridan foydalaning.
