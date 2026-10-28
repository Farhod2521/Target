# CRM API

Mijozning o'z CRM doskasi: reklamadan kelgan lidlar kartaga aylanadi,
menejerlar ularni ustundan ustunga suradi va natijani belgilaydi.

- Hamma yo'llar `/api/v1/crm` ostida, `Authorization: Bearer <token>`.
- Umumiy qoidalar (xatolar, tokenlar): [FRONTEND_INTEGRATSIYA.md](FRONTEND_INTEGRATSIYA.md).

---

## 1. Asosiy tushunchalar

### Juftlik (pair)

CRM **har bir sahifa + reklama akkaunti juftligi uchun alohida**. Har
juftlikning o'z ustunlari, menejerlari, sozlamalari va kartalari bor.

- Juftlik kaliti: `"<page external_id>:<ad account external_id>"`.
- Har endpoint `?pair=<kalit>` qabul qiladi. Bo'sh yoki noma'lum bo'lsa —
  kabinetning joriy juftligi.
- Javoblarda `pair` (joriysi) va `pairs[]` (`key`, `page`, `account`) keladi.
  Ega uchun juftlik tanlagichi shu ro'yxatdan chiziladi. Menejerga `pairs`
  bo'sh keladi.

### Kim ko'radi

| Rol | Kim | Nima qila oladi |
|---|---|---|
| **Ega** | Akkaunt egasi | Hammasi: sozlash, menejerlar, ustunlar, kartalar, istalgan juftlik |
| **Menejer** | Ega qo'shgan xodim | Faqat o'z juftligi doskasi va kartalari. Sozlamalar `404` |

Menejer alohida login bilan kiradi (`POST /auth/login`), unga faqat `/crm`,
`/auth`, `/account/language` ochiq.

### Menejer o'rni (seat)

- Pullik tarifda **har sahifaga 1 ta bepul o'rin**. Sinov (trial) davrida
  bepul o'rin yo'q.
- Qo'shimcha o'rinlar sotib olinadi (⚠️ sotib olish endpointi FastAPI'da
  hali yo'q).
- O'ringa sig'magan menejer `seated: false` — u kira olmaydi va unga lid
  berilmaydi.
- Bitta juftlikda ko'pi bilan **10 ta** faol menejer.

### Ustun turlari (`stage.kind`)

| `kind` | Ma'nosi | Izoh |
|---|---|---|
| `new` | Yangi lid | Doim bor, o'chirilmaydi |
| `open` | Jarayonda | Qo'shiladigan/o'chiriladigan ustunlar |
| `won` | Sotildi | Doim bor. Faqat `win` orqali |
| `lost` | Rad etildi | Doim bor. Faqat `lose` orqali |

Ko'pi bilan 12 ta ustun, shundan 6 tasi o'zi yozgan.

### Sifatli lid

- Ega qaysi ustunlar "sifatli" hisoblanishini tanlaydi
  (`stage.counts_as_quality`). Faqat `open` va `won` ustunlar tanlanadi.
- Karta shunday ustunga birinchi marta tushganda `card.qualified_at`
  yoziladi va tarixga "Sifatli bo'ldi" qo'shiladi.
- Bu son dashboardda `crm_qualified` bo'lib chiqadi.
- ⚠️ Sifatli lidlarni Meta'ga yuborish backendda **hali ko'chirilmagan**
  (`quality_sent_at` hozircha doim bo'sh).

---

## 2. Kirish va holatlar

### `GET /crm/nav`

Menyudagi "CRM" bandi uchun. Har qanday foydalanuvchi chaqira oladi.

```json
{"url": "/app/crm/", "attention": 3}
```

`attention` — e'tibor kerak kartalar soni (badge). CRM yo'q bo'lsa
`url` lidlar sahifasiga ishora qiladi.

### CRM yopiq bo'lsa — `409`

Doska va karta endpointlari quyidagi holatlarda
`409 {"detail": {"crm": "<sabab>"}}` qaytaradi:

| `crm` | Kimga | Nima ko'rsatish |
|---|---|---|
| `no_pair` | Menejer | Juftligi obunadan chiqib ketgan — egaga murojaat |
| `seat` | Menejer | O'rin yo'q — ega o'rin sotib olishi kerak |
| `closed` | Menejer | Faol emas yoki egasi bloklangan |
| `password` | Menejer | Birinchi kirish — parolni almashtirish ekrani |
| `off` | Menejer | Ega CRM'ni hali yoqmagan yoki o'chirgan |
| `soon` | — | CRM umuman yopiq (hozir ishlatilmaydi) |

### Menejerning birinchi kirishi

`409 {"crm": "password"}` kelsa:

```http
POST /crm/password
{"password": "yangiParol1", "again": "yangiParol1"}
```

→ `{"ok": true}`. Keyin doskani qayta so'rang.

---

## 3. Doska

### `GET /crm`

| Query | Izoh |
|---|---|
| `pair` | Juftlik kaliti |
| `q` | Ism yoki telefon bo'yicha qidiruv |
| `m` | Faqat shu menejer kartalari (user id) |
| `ad` | Faqat shu reklamadan (Meta ad id) |
| `f` | `late` (muddati o'tgan) yoki `today` (bugun) |

Javob uch xil bo'ladi:

**a) Juftlik yo'q (sahifa ulanmagan):**

```json
{"setup_needed": false, "no_pair": true, "pair": null, "pairs": []}
```

**b) Ega, CRM sozlanmagan** — sozlash ustasini oching:

```json
{"setup_needed": true, "step": 2, "pair": "123:act_456", "pairs": [...]}
```

**c) Doska:**

```json
{
  "pair": "123:act_456",
  "pairs": [{"key": "123:act_456", "page": "Do'kon", "account": "Asosiy"}],
  "setup_needed": false,
  "no_pair": false,
  "running": true,
  "is_owner": true,
  "columns": [
    {
      "stage": {"id": "uuid", "name": "Yangi lid", "color": "#0A64E0",
                "kind": "new", "position": 0, "counts_as_quality": false},
      "cards": [ /* karta, pastda */ ],
      "total": 57,
      "won_minor": 0,
      "reasons": [],
      "start": 0,
      "hidden": 17,
      "next_start": 40
    }
  ],
  "late": 2,
  "today": 5,
  "cursor": "...",
  "filters": {"q": "", "m": "", "ad": "", "f": ""},
  "members": [ /* menejer, pastda */ ],
  "ads": [ /* filtr uchun reklamalar */ ]
}
```

- `running: false` — CRM o'chiq, doska faqat ko'rish uchun.
- Har ustunda ko'pi bilan 40 karta. `hidden > 0` bo'lsa "Yana" tugmasi.
- Yopilgan (`won`/`lost`) kartalar 30 kun doskada turadi.

### Karta (`card`)

```json
{
  "id": "uuid",
  "stage_id": "uuid",
  "assignee": {"id": "uuid", "full_name": "Vali", "email": "vali@..."},
  "due_at": "2026-10-29T10:00:00Z",
  "due_note": "Qayta qo'ng'iroq",
  "attempts": 2,
  "last_note": "Narxini so'radi",
  "last_note_at": "...",
  "returned": false,
  "qualified_at": null,
  "won_amount_minor": null,
  "currency": "UZS",
  "lost_reason_name": "",
  "closed_at": null,
  "taken_at": "...",
  "created_at": "...",
  "lead": {
    "id": "uuid",
    "full_name": "Ali",
    "phone_e164": "+998901234567",
    "email": "",
    "city": "Toshkent",
    "ad_external_id": "1202...",
    "ad_title": "Kuzgi aksiya",
    "submitted_at": "..."
  }
}
```

- `assignee: null` — hech kimga berilmagan.
- `attempts` — necha marta "javob bermadi".
- `returned: true` — mijoz qayta murojaat qilgan.

### Ustunni davom ettirish — `GET /crm/columns/{stage_id}`

`?start=<next_start>` + doskadagi filtrlar → bitta ustun (`column` shakli).

### Yangilanishni kuzatish — `GET /crm/pulse?cursor=<cursor>`

Har 20 soniyada (Django'dagi interval):

- `204` — o'zgarmagan.
- `200 {"cursor", "layout_changed"}` — o'zgargan. `GET /crm`ni qayta
  so'rang. `layout_changed: true` bo'lsa ustunlar ham o'zgargan.

---

## 4. Karta

### `GET /crm/cards/{id}`

Karta oynasi.

```json
{
  "card": { /* karta */ },
  "answers": [ /* lid formadagi javoblar */ ],
  "source": { /* qaysi reklamadan */ },
  "history": [
    {"kind": "moved", "text": "...", "actor": {...}, "created_at": "..."}
  ],
  "stages": [ /* ustunlar — "surish" menyusi uchun */ ],
  "members": [ /* "berish" menyusi uchun */ ],
  "pair": "123:act_456",
  "reasons": [{"id": "uuid", "name": "Qimmat"}],
  "currency": "UZS",
  "can_work": true
}
```

`can_work: false` — faqat ko'rish (masalan, boshqa menejerning kartasi).

`history[].kind`: `arrived`, `returned`, `assigned`, `taken`, `moved`,
`note`, `no_answer`, `due_set`, `due_done`, `qualified`, `won`, `lost`,
`reopened`, `sent_to_meta`.

### Amallar

Hammasi `POST`, javob — yangilangan karta.

| Endpoint | Body | Izoh |
|---|---|---|
| `/cards/{id}/take` | — | "Olish". Karta `new`da bo'lsa birinchi `open` ustunga o'tadi |
| `/cards/{id}/move` | `{"to": "<stage_id>"}` | Faqat `new`/`open` ustunga. `won`/`lost`ga → `use_the_dialog` xatosi |
| `/cards/{id}/note` | `{"text": "..."}` | Izoh |
| `/cards/{id}/no-answer` | — | "Javob bermadi" (`attempts` +1) |
| `/cards/{id}/due` | `{"due": "<ISO vaqt>", "note": ""}` | Muddat qo'yish. O'tgan vaqt — xato |
| `/cards/{id}/due/done` | — | Muddat bajarildi |
| `/cards/{id}/win` | `{"amount": "1500000", "note": ""}` | Sotildi. Summa majburiy |
| `/cards/{id}/lose` | `{"reason": "<reason_id>", "note": ""}` | Rad etildi. Sabab majburiy |
| `/cards/{id}/assign` | `{"assignee": "<user_id>"}` | **Faqat ega.** Bo'sh — menejerdan olish |
| `/leads/{lead_id}/add` | — | **Faqat ega.** Doskada yo'q lidni qo'shish |

Yopilgan kartani `move` bilan `open` ustunga qaytarsa — u qayta ochiladi
(summa va sabab tozalanadi).

### Karta xatolari (`400`)

| `code` | Matn |
|---|---|
| `already_taken` | Bu lidni boshqa menejer oldi. |
| `card_is_closed` | Bu karta yopilgan. Avval uni boshqa ustunga o'tkazing. |
| `use_the_dialog` | Natijani dialogda belgilang. |
| `reason_required` | Rad etish sababini tanlang. |
| `amount_required` | Sotuv summasini kiriting. |
| `due_in_past` | Muddat o'tib ketgan vaqt bo'lishi mumkin emas. |
| `empty_note` | Izoh bo'sh. |
| `unknown_card` | Karta topilmadi. Doskani yangilang. |
| `already_on_board` | Bu lid allaqachon CRM doskasida. |
| `not_on_pair` | Bu lid shu juftlik reklamasidan kelmagan. |
| `not_running` | CRM o'chiq. Avval uni yoqing. |
| `not_yours` (`403`) | Bu amal sizga ruxsat etilmagan. |

---

## 5. Sozlash ustasi (birinchi marta)

`GET /crm` → `setup_needed: true, step: N` bo'lsa ega 4 qadamdan o'tadi.
Hammasi `POST /crm/setup/{step}`, bir xil body (`SetupStepIn`) — har qadam
o'ziga keraklisini o'qiydi.

Variantlar (presetlar, ranglar, tanlovlar) `GET /crm/settings`dan olinadi.

Oldinga sakrab bo'lmaydi: joriy qadamdan kattasi →
`409 {"detail": {"step": <joriy>}}`.

Javob: `{"next": <keyingi qadam>, "placed": <doskaga qo'yilgan lidlar>, ...settings}`.

### 1-qadam: ustunlar

```json
{
  "presets": ["new", "working", "informed", "won", "lost"],
  "columns": ["new", "working", "c1", "informed", "won", "lost"],
  "custom": {"c1": ["Narx yuborildi", "#B7791F"]}
}
```

- `columns` — tartib bilan. Preset kalitlari yoki o'zingiz yozgan
  kalit (`custom`dagi).
- `presets` — belgilangan presetlar. `columns`da bo'lib, `presets`da
  bo'lmasa (va `custom`da ham bo'lmasa) — tashlab ketiladi.
- `custom` — `{kalit: [nomi, rang]}`.

Presetlar (`GET /crm/settings` → `presets`):

| `key` | Nomi | `kind` | Default | Majburiy |
|---|---|---|---|---|
| `new` | Yangi lid | new | ✅ | ✅ |
| `working` | Jarayonda | open | ✅ | |
| `informed` | Ma'lumot berildi | open | ✅ | |
| `callback` | Qayta aloqa | open | | |
| `meeting` | Uchrashuv belgilandi | open | | |
| `payment` | To'lov kutilmoqda | open | | |
| `won` | Sotildi | won | ✅ | ✅ |
| `lost` | Rad etildi | lost | ✅ | ✅ |

### 2-qadam: taqsimlash

```json
{"distribution": "round_robin"}
```

| Qiymat | Ma'nosi |
|---|---|
| `round_robin` | Navbat bilan, teng |
| `claim` | Kim birinchi «Olish» bossa |
| `manual` | Men o'zim beraman |

Menejersiz davom etish: `POST /crm/setup/skip-members` (`manual` qo'yadi
va 3-qadamga o'tkazadi) → `{"detail": "Hamma lid sizda bo'ladi. ..."}`.

Menejerlarni shu qadamda `POST /crm/settings/members` bilan qo'shish mumkin
(7-bo'lim).

### 3-qadam: qaysi lidlar tushadi

```json
{
  "since": "week",
  "day": null,
  "every_ad": true,
  "ad": [],
  "offered": [],
  "take_new_ads": false
}
```

| Maydon | Izoh |
|---|---|
| `since` | `new` (faqat yangilar), `yesterday`, `week` (hafta boshidan), `month`, `date` |
| `day` | `since: "date"` bo'lsa — sana (`YYYY-MM-DD`) |
| `every_ad` | `true` — hamma reklamalardan |
| `ad` | `every_ad: false` bo'lsa — tanlangan reklamalar (Meta ad id) |
| `offered` | Ekranda ko'rsatilgan reklamalar ro'yxati |
| `take_new_ads` | Keyin chiqadigan reklamalar ham avtomatik qo'shilsin |

`every_ad: false` va `ad` bo'sh → `no_ads_chosen` xatosi. Reklamalar
ro'yxati: `GET /crm/settings` → `ads`.

### 4-qadam: sifatli ustunlar va yoqish

```json
{"quality": ["<stage_id>", "<stage_id>"]}
```

Faqat `open` va `won` ustunlar hisobga olinadi. Bu qadam CRM'ni **yoqadi**
va 3-qadam bo'yicha lidlarni doskaga qo'yadi (`placed`).

---

## 6. Sozlamalar (faqat ega)

### `GET /crm/settings`

```json
{
  "pair": "123:act_456",
  "pairs": [...],
  "setup": {
    "state": "on",
    "step": 4,
    "since": "week",
    "leads_since": "2026-10-27T00:00:00Z",
    "every_ad": true,
    "ad_external_ids": [],
    "offered_ad_ids": [],
    "take_new_ads": false,
    "distribution": "round_robin",
    "currency": "UZS"
  },
  "stages": [...],
  "members": [...],
  "reasons": [{"id": "uuid", "name": "Qimmat"}],
  "ads": [ /* tanlash mumkin bo'lgan reklamalar */ ],
  "presets": [{"key", "label", "kind", "color", "default", "always"}],
  "colors": ["#0A64E0", "#7C6CFF", "#0891B2", "#B7791F", "#D9480F",
             "#C2255C", "#4A5878", "#0E7F5C", "#C2262E"],
  "custom_slots": 6,
  "since_choices": [{"value": "new", "label": "Faqat yangilar"}, ...],
  "distribution_choices": [{"value": "round_robin", "label": "Navbat bilan, teng"}, ...]
}
```

`setup.state`: `draft` (sozlanmagan), `on` (yoqiq), `off` (o'chiq).

### Yoqish / o'chirish

```http
POST /crm/settings/state
{"state": "on"}     // yoki "off"
```

→ `{"placed": 12}` (yoqilganda doskaga qo'yilgan lidlar).

### Ustunlar

| Endpoint | Body | Javob |
|---|---|---|
| `POST /crm/settings/stages` | `{"name": "Narx yuborildi", "color": "#B7791F"}` | ustun |
| `PUT /crm/settings/stages/{id}` | `{"name", "color"}` | ustun |
| `POST /crm/settings/stages/{id}/move` | `{"way": "right"}` yoki `"left"` | hamma ustunlar |
| `DELETE /crm/settings/stages/{id}` | — | `{"cards_moved": 4}` |

- Nomi ko'pi bilan 48 belgi.
- Faqat `open` ustun o'chiriladi (`stage_locked` aks holda). Undagi
  kartalar birinchi ustunga o'tadi.
- Chegara: `too_many_stages`.

### Taqsimlash, lid oqimi, sifat

| Endpoint | Body | Javob |
|---|---|---|
| `POST /crm/settings/distribution` | `{"distribution": "claim"}` | settings |
| `POST /crm/settings/flow` | 3-qadam body'si | settings |
| `POST /crm/settings/quality` | `{"quality": ["<stage_id>"]}` | settings |

### Rad etish sabablari

| Endpoint | Body | Javob |
|---|---|---|
| `POST /crm/settings/reasons` | `{"name": "Qimmat"}` (≤64) | `201 {"id", "name"}` |
| `DELETE /crm/settings/reasons/{id}` | — | `{"ok": true}` |

Default sabablar: Qimmat, Aloqaga chiqmadi, Boshqasini tanladi, Hozir kerak
emas, Noto'g'ri raqam, Boshqa sabab.

---

## 7. Menejerlar (faqat ega)

Menejer joriy juftlikka (`?pair=`) qo'shiladi va faqat shu juftlikda
ishlaydi.

### Qo'shish

```http
POST /crm/settings/members
{
  "name": "Vali Karimov",
  "email": "vali@example.com",
  "password": "kamida8belgi",
  "kpi_fix": "3000000",
  "kpi_percent": "5"
}
```

`201` → menejer:

```json
{
  "id": "uuid",
  "user": {"id": "uuid", "full_name": "Vali Karimov", "email": "vali@example.com"},
  "is_active": true,
  "seated": true,
  "takes_leads": true,
  "must_change_password": true,
  "kpi_fix_minor": 300000000,
  "kpi_percent": 5,
  "kpi_currency": "UZS"
}
```

- Ega email va parolni menejerga o'zi beradi. Menejer birinchi kirishda
  parolni almashtiradi (`must_change_password`).
- `seated: false` — o'ringa sig'madi, kira olmaydi (1-bo'lim).
- `kpi_fix` — oylik fiks, so'mda matn bo'lib yuboriladi; javobda
  `kpi_fix_minor` tiyinda keladi (×100). `kpi_percent` — sotuvdan foiz
  (0–100). Ikkalasi ixtiyoriy.

### Tahrirlash, parol, o'chirish

| Endpoint | Body | Javob |
|---|---|---|
| `PUT /crm/settings/members/{id}` | `{"name", "takes_leads", "kpi_fix", "kpi_percent"}` | menejer |
| `POST /crm/settings/members/{id}/password` | `{"password"}` | menejer |
| `DELETE /crm/settings/members/{id}` | — | `{"cards_released": 7}` |

- `takes_leads: false` — menejer ishlaydi, lekin unga avtomatik lid
  berilmaydi.
- O'chirilganda uning ochiq kartalari bo'shatiladi (`assignee: null`).

### Menejer xatolari

| `code` | Matn |
|---|---|
| `name_required` | Nomini kiriting. |
| `email_taken` | Bu email bilan akkaunt bor. Boshqa email kiriting. |
| `password_too_weak` | (parol talablari matni) |
| `passwords_differ` | Ikki parol bir xil emas. |
| `too_many_members` | Jamoada ko'pi bilan 10 ta menejer bo'lishi mumkin. |
| `bad_kpi` | Fix maosh va foizni raqam bilan yozing (foiz 0 dan 100 gacha). |
| `unknown_member` | Menejer topilmadi. |

---

## 8. Ekranlar bo'yicha qisqacha

| Ekran | So'rovlar |
|---|---|
| Menyu badge | `GET /crm/nav` |
| Doska | `GET /crm` → `GET /crm/pulse` har 20 s (Django'dagidek) → o'zgarsa `GET /crm` |
| "Yana" | `GET /crm/columns/{id}?start=` |
| Karta oynasi | `GET /crm/cards/{id}` + amallar |
| Sozlash ustasi | `GET /crm/settings` → `POST /crm/setup/1..4` |
| Sozlamalar | `GET /crm/settings` + `/crm/settings/*` |
| Menejer birinchi kirishi | `409 password` → `POST /crm/password` |

## 9. Hali backendda yo'q

- Qo'shimcha menejer o'rnini sotib olish.
- Sifatli lidlarni Meta'ga yuborish (`sent_to_meta` tarixda hozircha
  chiqmaydi).
- Jamoa statistikasi (menejerlar bo'yicha hisobot).
