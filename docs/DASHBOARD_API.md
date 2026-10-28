# Dashboard API

Foydalanuvchi kirgandan keyin ochiladigan asosiy sahifa (Django'dagi `/app/`)
uchun kerakli endpointlar.

- Hamma yo'llar `/api/v1` ostida.
- Har so'rovga `Authorization: Bearer <access_token>` kerak.
- Javoblardagi pul va raqamlar (`spend`, `cpl`, `display`, ...) server
  tomonidan **tayyor formatlangan matn**. Hisoblash uchun `*_minor` (butun
  son, tiyin/sent) maydonlari bor.
- **CPQL ko'rsatilmaydi** (mahsulot qoidasi): ekranga `cpl` chiqadi, `cpql`
  va `qualified` hozircha ishlatilmaydi.

## Qisqacha

| # | Endpoint | Nima uchun |
|---|---|---|
| 1 | `GET /metrics/numbers` | Dashboardning barcha raqamlari |
| 2 | `POST /metrics/numbers/refresh` | Raqamlarni Meta'dan yangilash |
| 3 | `GET /metrics/numbers/poll` | Yangilanish tugaguncha so'rab turish |
| 4 | `GET /metrics/cards` | Qaysi kartalar ko'rsatiladi |
| 5 | `POST /metrics/cards` | Kartalar tanlovini saqlash |
| 6 | `GET /business` | Biznes nomi va profili |
| 7 | `GET /billing` → `promo_announcement` | Promo kod e'loni |
| 8 | `POST /billing/promo/seen` | E'lonni ko'rildi deb belgilash |
| 9 | `GET /referrals/invite` | Do'st taklif qilish banneri |

> **Sozlash qadamlari bloki** (biznes profili, Meta ulanishi, sahifa, lid
> obunasi) `GET /metrics/numbers` javobidagi `setup` maydonidan chiziladi —
> faqat `setup.ready == false` bo'lsa. Batafsil ekran: `GET /start`.

---

## 1. `GET /metrics/numbers`

Dashboardning asosiy so'rovi. Sahifa ochilganda bir marta chaqiriladi.

### Parametrlar (query)

| Nomi | Turi | Izoh |
|---|---|---|
| `period` | `today` \| `7` \| `30` \| `90` | Tayyor oraliq. Standart — `30` |
| `start` | `YYYY-MM-DD` | O'zi tanlagan oraliq boshi (eng ko'pi 90 kun orqaga) |
| `end` | `YYYY-MM-DD` | O'zi tanlagan oraliq oxiri (bugundan keyin emas) |

- `start` va `end` ikkalasi berilsa, `period` e'tiborga olinmaydi.
- Hech biri berilmasa, foydalanuvchi **oxirgi tanlagan oraliq** qaytadi
  (server 90 kun eslab qoladi).

### Javob

```json
{
  "crm_qualified": 12,
  "dashboard": { "...": "pastda" },
  "filters": {
    "key": "30",
    "since": "2026-09-29",
    "until": "2026-10-28",
    "days": 30,
    "is_custom": false,
    "earliest": "2026-07-31"
  },
  "periods": [
    {"value": "today", "label": "Bugun"},
    {"value": "7", "label": "7 kun"},
    {"value": "30", "label": "30 kun"},
    {"value": "90", "label": "90 kun"}
  ],
  "page": {"name": "Mening do'konim", "key": "...", "currency": "UZS"},
  "ad_account": {"id": "uuid", "name": "...", "currency": "UZS", "timezone": "Asia/Tashkent"},
  "synced_at": "2026-10-28T09:12:00Z",
  "behind_since": null,
  "is_stale": false,
  "since": "2026-10-28T09:12:00+00:00",
  "syncing": false,
  "account_ids": ["uuid"],
  "auto_refresh": true,
  "tries": 0,
  "poll_seconds": 3
}
```

| Maydon | Izoh |
|---|---|
| `crm_qualified` | CRM sanagan sifatli lidlar. CRM o'chiq bo'lsa `null` |
| `setup` | Sozlash bloki: `steps[]` (`id`, `state`, `optional`), `done`, `total`, `ready`, `can_finish`, `blocked_on`, `page`. Faqat shu so'rovda keladi; `poll` va `refresh`da `null` |
| `dashboard` | Asosiy ma'lumot — keyingi bo'lim |
| `filters` | Qo'llangan oraliq. `earliest` — sana tanlagichda eng erta kun |
| `periods` | Oraliq tugmalari |
| `page` | Joriy sahifa va valyuta |
| `ad_account` | Joriy reklama akkaunti. Ulanmagan bo'lsa `null` |
| `synced_at` | Raqamlar oxirgi yangilangan vaqt. Hech qachon bo'lmagan bo'lsa `null` |
| `is_stale` | Raqamlar eskirgan (30 soatdan ko'p) — ogohlantirish ko'rsating |
| `behind_since` | Raqamlar kelishi to'xtagan vaqt (masalan token eskirgan) |
| `since` | Yangilashdan keyin `poll`ga yuboriladi |
| `syncing` | Hozir yangilanmoqda |
| `auto_refresh` | `true` bo'lsa — darhol `POST /metrics/numbers/refresh?on_open=true` |
| `poll_seconds` | `poll` oralig'i (soniya) |

### `dashboard` ichida

| Maydon | Izoh |
|---|---|
| `currency` | Valyuta |
| `has_run` | Reklama umuman ishlaganmi. `false` — bo'sh holat ko'rsatiladi |
| `period` | Tanlangan oraliq bo'yicha raqamlar (pastda) |
| `leads` | Oxirgi lidlar ro'yxati |
| `decisions` | Agent/foydalanuvchi qarorlari tarixi |
| `by_city` | Shaharlar bo'yicha lid ulushi |
| `by_city_source` | `by_city` qaysi manbadan |
| `by_hour` | Soatlar bo'yicha lid ulushi |
| `segments` | Auditoriya segmentlari (yosh, jins, ...) bo'yicha CPL |
| `cuts` | Natija turi bo'yicha kesim tablari |
| `elsewhere_spend` | Boshqa joyda (bizdan tashqari) sarflangan pul |
| `other_currency` | Boshqa valyutadagi akkauntlar |

#### `dashboard.period`

| Maydon | Izoh |
|---|---|
| `key`, `label`, `days` | Oraliq |
| `in_progress` | Oraliq bugunni o'z ichiga oladi (raqamlar hali o'zgaradi) |
| `spend`, `spend_minor` | Sarflangan pul |
| `leads`, `cpl` | Lidlar soni va bitta lid narxi |
| `reported_leads`, `reported_cpl` | Meta hisoboti bo'yicha (bizda yetib kelmagan lidlar bilan) |
| `shown`, `shown_total` | Ko'rsatishlar |
| `campaign_count` | Kampaniyalar soni |
| `kpis[]` | Yuqoridagi kartalar: `key`, `label`, `display`, `delta_pct`, `trend` (`up`/`down`/`flat`), `is_good`, `hint` |
| `outcomes[]` | Natija bloklari (lid, qo'ng'iroq, xabar, ...). Birinchisi — asosiy |
| `series[]` | Grafik chiziqlari: `key`, `label`, `points[]` (`x`, `y`, `label`, `display`), `peak`, `floor`, `polyline` |
| `funnel[]` | Voronka: `label`, `value`, `share_pct`, `note` |
| `campaigns[]` | Kampaniyalar jadvali: `name`, `delivery_label`, `spend`, `leads`, `cpl`, `results`, `result_label`, `result_cost`, `note` |
| `views[]` | Natija turiga qarab alohida grafik/voronka (`kind`, `label`, `series`, `funnel`) |
| `unknown_after` | Shu vaqtdan keyingi raqamlar hali noma'lum |

`trend` va `is_good` alohida: `up` har doim yaxshi emas (masalan CPL o'sishi
yomon). Rangni `is_good` bo'yicha bering.

#### Boshqa ro'yxatlar

```text
leads[]      pk, name, city, phone_masked, when, campaign, verdict
decisions[]  when, action, target, reason, actor
by_city[]    label, share_pct, leads, total_pct
by_hour[]    label, share_pct, leads, total_pct
segments[]   key, title, days, leads, min_leads, best_leads, has_forms,
             ranked[]  (label, cpl, index, compare, leads, spend, spend_share)
             barren[]  (xuddi shunday — natija bermagan segmentlar)
cuts[]       kind, tabs[] (key, label, days, block, showing[], bars[])
```

---

## 2. Yangilash oqimi

### `POST /metrics/numbers/refresh`

| Query | Izoh |
|---|---|
| `on_open=true` | Sahifa ochilganda, `auto_refresh: true` bo'lsa. Faqat eskirganini yangilaydi |
| (yo'q) | Foydalanuvchi "Yangilash" tugmasini bosdi |

Javob — `GET /metrics/numbers` bilan bir xil, `syncing: true` va (tugma
bosilganda) `"message": "Yangilanish boshlandi."`.

### `GET /metrics/numbers/poll`

| Query | Izoh |
|---|---|
| `since` | Yangilashdan **oldingi** javobdagi `since` |
| `tries` | Oxirgi javobdagi `tries` (birinchisida `0`) |

Javob — xuddi shu shakl, qo'shimcha `gave_up`.

### Tartib

```text
GET  /metrics/numbers                     → auto_refresh: true
POST /metrics/numbers/refresh?on_open=true
loop har poll_seconds (3 s):
    GET /metrics/numbers/poll?since=<eski since>&tries=<tries>
    syncing == false  → to'xtat, yangi raqamlarni chiz
    gave_up == true   → to'xtat, "raqamlar kechikmoqda" deb yoz
```

Server 20 urinishdan keyin o'zi `gave_up: true` qaytaradi.

---

## 3. Kartalar

### `GET /metrics/cards`

```json
{
  "groups": [
    {
      "key": "money",
      "label": "Pul",
      "cards": [
        {
          "key": "spend",
          "label": "Sarflandi",
          "hint": "...",
          "is_on": true,
          "is_on_row": true,
          "is_daily": false,
          "is_per_goal": false
        }
      ]
    }
  ],
  "chosen_count": 6
}
```

- `is_on` — dashboardda ko'rsatiladi.
- `is_on_row` — kampaniyalar ro'yxati qatorida ham chiqadi.
- `is_daily` — kunlik o'rtacha.
- `is_per_goal` — natija turiga bog'liq.

### `POST /metrics/cards`

```json
{"cards": ["spend", "leads", "cpl"]}
```

Javob: `{"message": "Saqlandi.", "chosen": ["spend", "leads", "cpl"]}`.
Saqlangandan keyin `GET /metrics/numbers` qayta so'raladi.

---

## 4. Qo'shimcha bloklar

### Biznes — `GET /business`

Sarlavhadagi biznes nomi va profil uchun.

### Promo e'loni — `GET /billing`

Javobdagi `promo_announcement`. `null` bo'lsa — blok yo'q.

```json
"promo_announcement": {
  "redemption": { "id": "uuid", "...": "..." },
  "free_slots": 1,
  "choices": [ ],
  "can_choose": true
}
```

Yopilganda:

```http
POST /billing/promo/seen
{"redemption": "<redemption.id>"}
```

Bepul sahifani tanlash: `POST /billing/promo/page`.

### Taklif banneri — `GET /referrals/invite`

`null` — banner ko'rsatilmaydi.

```json
{
  "link": "https://.../r/ABC123/",
  "share_url": "https://t.me/share/url?...",
  "percent": 10,
  "top_bonus": null
}
```

"Yopish" holati serverda saqlanmaydi — frontend o'zi eslab qoladi
(`sessionStorage`).

---

## 5. Sahifa ochilganda so'rovlar

```text
parallel:
  GET /metrics/numbers
  GET /business
  GET /billing            (faqat promo_announcement uchun)
  GET /referrals/invite
keyin:
  auto_refresh == true → POST /metrics/numbers/refresh?on_open=true → poll
```

Oraliq o'zgarganda faqat `GET /metrics/numbers?period=...` qayta so'raladi.

---

## 6. Xatolar

| Kod | Qachon |
|---|---|
| `401` | Token yo'q yoki eskirgan → `POST /auth/refresh` |
| `403` | CRM menejeri kirgan (`"Faqat CRM doskasi."`) — dashboard unga yopiq |
| `422` | Noto'g'ri sana formati |

Noto'g'ri `period` yoki chegaradan tashqari sana xato bermaydi — server
standart oraliqqa (`30`) yoki chegaraga moslaydi.
