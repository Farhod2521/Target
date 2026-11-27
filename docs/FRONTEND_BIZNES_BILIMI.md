# Biznes bilimi, tor yo'nalishlar va tur tavsiyalari — frontend qo'llanmasi

Backend: migratsiyalar `0089`, `0090`. Ma'lumot ko'chirish skripti yo'q, migratsiyaning o'zi
yetarli.

**Eski API o'zgarmagan.** `/api/v1`, `/api/v2` va mavjud `/api/v3/businesses` yo'llarining
hech biri, hech bir maydoni o'zgarmadi. Bu hujjatdagi hamma narsa yangi qo'shilgan.

OpenAPI'ni qayta generatsiya qiling (`pnpm api:gen`). Yangi sxemalar: `KnowledgeOut`,
`KnowledgeCatalogOut`, `ChangesIn`, `ChangeIn`, `KindIn`, `SubtypesOut`,
`KnowledgeHistoryOut`.

## 1. Nima qo'shildi

| Narsa | Qisqacha |
|---|---|
| **Biznes bilimi** | Har biznes o'zi haqida aytgan narsalar: nima qiladi, nima sotadi (takliflar), faktlar. Reklama yaratish chati ham, kabinet AI chati ham shuni o'qiydi va to'ldiradi |
| **Tor yo'nalish** | Biznes turi ostidagi aniqroq tur: «Mebel» → «Oshxona mebeli». Qo'lda kiritilmaydi, AI o'zi yaratadi |
| **Tur tavsiyasi** | Ofis har biznes turi uchun 5 ta narsa yozadi: 1-maqsad va sababi, 2-maqsad va qachon mosligi, nima deyish mumkin emasligi |
| **5 ta yangi tur** | Qishloq xo'jaligi, Mebel, IT va dasturlar, Bolalar mahsulotlari, Logistika. Endi 18 ta. Profil formasidagi mavjud `categories` ro'yxatida o'zi chiqadi, frontda ish yo'q |

Atamalar: **biznes turi** — ofisdagi «Yo'nalishlar» sahifasidagi qator (kodda `direction`).
**Tor yo'nalish** — uning ostidagi aniqroq tur (kodda `subtype`).

## 2. Umumiy qoidalar

- Avtorizatsiya avvalgidek: `Authorization: Bearer <access>`.
- **O'qish:** ega va shu biznesda ishlaydigan har bir xodim. Begonaga `404 unknown_business`.
- **Bilimni o'zgartirish:** ega va istalgan sohada `edit` ruxsati bor xodim. Boshqaga
  `403 no_access`.
- **Biznes turini o'zgartirish:** ega va reklamada (`ads`) `edit` ruxsati bor xodim.
- O'zgartiradigan har so'rov javobida **bilimning yangi to'liq holati** qaytadi
  (`KnowledgeOut`). Qayta so'rash shart emas.
- Bir sahifaga ulangan ikkinchi reklama akkaunti alohida biznes, lekin **bilimi sahifaniki
  bilan umumiy**. Javobdagi `kept_by` — bilim kimniki ekanini aytadi (`business_id` dan farq
  qilsa, umumiy).

## 3. Bilimni o'qish

`GET /api/v3/businesses/{id}/knowledge`

```json
{
  "business_id": "7c1e…",
  "kept_by": "7c1e…",
  "version": 4,
  "may_edit": true,
  "kind": {
    "direction": {"key": "education", "label": "Ta'lim markazi"},
    "label": "Ta'lim markazi",
    "state": "confirmed",
    "subtype": {"id": "a41b…", "name": "O'quv kursi", "is_checked": false}
  },
  "does": "Ingliz tili va matematika o'quv markazi",
  "about": {"text": "Ingliz tili va matematika o'quv markazi", "source": "launch_agent",
            "source_label": "Reklama yaratish chati", "at": "2026-11-27T10:00:00Z"},
  "items": [
    {"id": "a1b2c3d4", "name": "Ingliz tili", "kind": "course",
     "kind_label": "Kurs yoki yo'nalish", "price": "500 000 so'm / oy", "note": "",
     "link": "", "status": "active", "source": "assistant", "source_label": "AI chat",
     "at": "2026-11-27T11:30:00Z"}
  ],
  "facts": [
    {"key": "area", "label": "Qayerda ishlaydi", "value": "Chilonzor",
     "source": "owner", "source_label": "Biznes egasi", "at": "2026-11-27T10:00:00Z"}
  ],
  "pending": [
    {"id": "9f0e1d2c", "source": "assistant", "source_label": "AI chat",
     "why": "Suhbatda yangi narx aytildi", "at": "2026-11-27T12:00:00Z",
     "lines": ["«Ingliz tili» — narxi: 550 000 so'm / oy"],
     "changes": [{"op": "update_item", "id": "a1b2c3d4", "price": "550 000 so'm / oy"}]}
  ],
  "advice": {
    "goal_first": {"key": "leads", "label": "Ariza yig'ish (lid forma)"},
    "reason_first": "Kursga yozilish qarori qo'ng'iroqda yopiladi.",
    "goal_second": {"key": "messages", "label": "Xabar yozishsin"},
    "when_second": "Narx aniq va egasi tez javob bera olsa.",
    "never_say": "Natijani kafolatlash."
  }
}
```

Maydonlar:

- `version` — har yozishda 1 ga oshadi. Hech narsa yozilmagan biznesda `0`.
- `kind.state`:
  - `unset` — tur hali aytilmagan;
  - `guessed` — biz sahifadan taxmin qildik, biznes tasdiqlamagan. «Taxmin» belgisi bilan
    ko'rsating va tasdiqlashni so'rang;
  - `confirmed` — biznes o'zi tanlagan yoki tasdiqlagan.
- `kind.subtype.is_checked: false` — AI yaratgan, ofis hali ko'rmagan. Mijozga farqi yo'q,
  ko'rsatish shart emas.
- `does` — biznes nima qilishi: `about` bo'lsa shu, bo'lmasa eski profildagi matn.
- `items[].status` — `active` yoki `archived`. Arxivlangan taklif o'chmaydi, alohida
  (kulrang) ko'rsating yoki yashiring.
- `pending` — AI ishlab chiqqan, hali tasdiqlanmagan o'zgarishlar. `lines` tayyor matn,
  shuni ko'rsating; `changes` ni o'zingiz o'qishingiz shart emas.
- `advice` — ofis shu tur uchun tavsiya yozmagan bo'lsa `null`.

## 4. Bilimni o'zgartirish

`POST /api/v3/businesses/{id}/knowledge/changes`

```json
{
  "changes": [
    {"op": "add_item", "name": "Rus tili", "kind": "course", "price": "400 000 so'm / oy"},
    {"op": "set_fact", "key": "guarantee", "value": "Birinchi dars bepul"}
  ],
  "version": 4
}
```

Butun hujjat yuborilmaydi, faqat **kichik o'zgarishlar ro'yxati** (1–40 ta). Hammasi
qo'llanadi yoki hech biri.

| `op` | Maydonlar | Izoh |
|---|---|---|
| `set_about` | `text` | Bo'sh matn — o'chiradi |
| `add_item` | `name`, ixtiyoriy `kind`, `price`, `note`, `link` | Shu nomli taklif bor bo'lsa, yangisi ochilmaydi: o'sha yangilanadi (arxivda bo'lsa, qaytadi) |
| `update_item` | `id` va o'zgaradigan maydonlar | Kamida bitta maydon |
| `archive_item` | `id` | Endi sotilmaydi |
| `restore_item` | `id` | Yana sotiladi |
| `set_fact` | `key`, `value` | `key` — katalogdagi ro'yxatdan |
| `clear_fact` | `key` | |

`version`:
- **Tahrirlash formasi** (o'qilgan narsani o'zgartiradi) — o'qilgan `version` ni yuboring.
  O'rtada boshqa joydan o'zgargan bo'lsa `409 knowledge_moved` keladi: yangisini o'qib,
  foydalanuvchiga ko'rsating.
- **Faqat qo'shadigan** so'rov (masalan «taklif qo'shish» tugmasi) — `version` yubormang.

Nomlar solishtirilganda katta-kichik harf, apostrof turi va ortiqcha bo'shliq farq
qilmaydi: «Ingliz tili» va «ingliz  TILI» bitta taklif.

## 5. AI taklif qilgan o'zgarishga javob

- `POST /api/v3/businesses/{id}/knowledge/proposals/{proposal_id}/confirm` — ha: qo'llanadi.
- `POST /api/v3/businesses/{id}/knowledge/proposals/{proposal_id}/reject` — yo'q: olib
  tashlanadi.

Ikkalasi ham `KnowledgeOut` qaytaradi. Taklif endi bo'lmasa `404 unknown_proposal`.
Tasdiqlash paytida taklif qo'llanib bo'lmasa (masalan o'sha taklif allaqachon yo'q),
xato qaytadi va taklif ro'yxatda qoladi: uni rad etish mumkin.

Kutayotgan takliflar 20 tadan oshmaydi: undan ko'p bo'lsa eng eskisi o'zi tushib qoladi.

## 6. Biznes turi va tor yo'nalish

`PUT /api/v3/businesses/{id}/kind`

```json
{"direction": "education", "subtype": "O'quv kursi"}
```

- `direction` — tur kaliti (katalogdagi `directions` dan). Majburiy.
- Tor yo'nalish ixtiyoriy, ikki usuldan biri:
  - `subtype_id` — mavjudini tanlash (6.1 dagi ro'yxatdan);
  - `subtype` — nomi bilan. Shu tur ostida bor bo'lsa o'sha olinadi, bo'lmasa **yaratiladi**.
- Javob: `KnowledgeOut`, `kind.state` = `confirmed`.

Bu so'rov eski profildagi turni ham yangilaydi (`GET /api/v1/business` dagi `category`).
Profilda qo'lda yozilgan «Boshqa» nomi bo'lsa, u olib tashlanadi.

### 6.1 Tanlash uchun ro'yxat

`GET /api/v3/businesses/{id}/knowledge/subtypes`

```json
{"direction": {"key": "education", "label": "Ta'lim markazi"},
 "subtypes": [{"id": "a41b…", "name": "O'quv kursi", "is_checked": true}]}
```

Biznesning hozirgi turi ostidagi faol tor yo'nalishlar, alifbo tartibida. Turi yo'q
biznesda `direction: null`, ro'yxat bo'sh.

## 7. Katalog (formalar uchun ro'yxatlar)

`GET /api/v3/businesses/knowledge/catalog`

```json
{
  "directions": [{"key": "furniture", "label": "Mebel"}],
  "item_kinds": [{"key": "product", "label": "Mahsulot"}, {"key": "service", "label": "Xizmat"},
                 {"key": "course", "label": "Kurs yoki yo'nalish"}, {"key": "other", "label": "Boshqa"}],
  "fact_keys": [{"key": "customers", "label": "Mijozlari kim"}, {"key": "area", "label": "Qayerda ishlaydi"}],
  "sources": [{"key": "launch_agent", "label": "Reklama yaratish chati"}],
  "goals": [{"key": "leads", "label": "Ariza yig'ish (lid forma)"}],
  "ops": ["set_about", "add_item", "update_item", "archive_item", "restore_item", "set_fact", "clear_fact"],
  "limits": {"items": 60, "about": 600, "item_name": 80, "item_price": 60,
             "item_note": 300, "item_link": 300, "fact": 400}
}
```

Faktlar kalitlari (12 ta): `customers`, `area`, `delivery`, `guarantee`, `payment`, `prices`,
`hours`, `address`, `contacts`, `advantages`, `answers`, `other`. Ro'yxat yopiq: ikki chat
bir narsani bir nom ostida yozishi uchun.

`limits` — maydon uzunliklari. Formada shu chegaralarni qo'ying.

## 8. Tarix

`GET /api/v3/businesses/{id}/knowledge/history?limit=100`

```json
{"items": [
  {"id": "…", "at": "2026-11-27T12:05:00Z", "kind": "knowledge_changed",
   "label": "Biznes haqidagi ma'lumot o'zgardi", "via": "apply", "source": "owner",
   "source_label": "Biznes egasi", "by_name": "Aziz",
   "lines": ["Yangi taklif: Rus tili — 400 000 so'm / oy", "Kafolat: Birinchi dars bepul"]},
  {"id": "…", "at": "2026-11-27T10:00:00Z", "kind": "type_set", "label": "Biznes turi belgilandi",
   "via": "", "source": "owner", "source_label": "Biznes egasi", "by_name": "Aziz",
   "lines": ["Biznes turi: Ta'lim markazi → O'quv kursi"]}
]}
```

Eng yangisi tepada. `lines` tayyor matn. `via`: `apply` (to'g'ridan-to'g'ri), `propose`
(AI taklif qildi), `confirm`, `reject`.

## 9. Xato kodlari

| Kod | HTTP | Qachon |
|---|---|---|
| `unknown_business` | 404 | Biznes yo'q yoki sizniki emas |
| `no_access` | 403 | O'zgartirishga ruxsat yo'q |
| `bad_knowledge_change` | 400 | O'zgarish noto'g'ri yozilgan; `detail` da nima xatoligi |
| `unknown_item` | 404 | `id` li taklif yo'q |
| `unknown_proposal` | 404 | Taklif allaqachon tasdiqlangan yoki rad etilgan |
| `knowledge_moved` | 409 | `version` eskirgan |
| `knowledge_full` | 409 | Takliflar ro'yxati to'la (60 ta) |
| `unknown_direction` | 404 | Bunday tur yo'q yoki o'chirilgan |
| `unknown_subtype` | 404 | `subtype_id` topilmadi |
| `bad_subtype` | 400 | Tor yo'nalish boshqa turga tegishli yoki nomi noto'g'ri |

## 10. Ofis: tur tavsiyalari va tor yo'nalishlar

Kimga ochiq: **Owner** va **Engineer** (va superuser). Boshqaga `404`.

### 10.1 Turlar ro'yxati

`GET /api/v1/office/business-types`

```json
{"rows": [{
  "id": "…", "key": "services", "label": "Xizmatlar", "is_active": true,
  "businesses": 68, "subtypes": 12, "unchecked_subtypes": 5, "is_advised": true,
  "rule": {
    "goal_first": {"key": "leads", "label": "Ariza yig'ish (lid forma)"},
    "reason_first": "Xizmat narxi ishni ko'rgandan keyin aytiladi.",
    "goal_second": {"key": "messages", "label": "Xabar yozishsin"},
    "when_second": "Narx oldindan aniq bo'lsa.",
    "never_say": "Natijani kafolatlash.",
    "updated_at": "2026-11-27T09:00:00Z"
  },
  "goals": [{"value": "leads", "label": "Ariza yig'ish (lid forma)"}]
}]}
```

- `goals` — shu turga tavsiya qilsa bo'ladigan maqsadlar (tanlov ro'yxati uchun).
- `is_advised: false` — tavsiya yozilmagan; `rule` dagi maqsadlar `null`.
- `unchecked_subtypes` — AI yaratgan, hali ko'rilmagan tor yo'nalishlar soni. Belgi (badge)
  qilib ko'rsating.

### 10.2 Tavsiyani yozish

`PUT /api/v1/office/business-types/{direction_id}/rule`

```json
{"goal_first": "leads", "reason_first": "…", "goal_second": "messages",
 "when_second": "…", "never_say": "…"}
```

Qoidalar (buzilsa `400 bad_advice`, `detail` da sababi):
- maqsad shu turning `goals` ro'yxatidan bo'lsin;
- 1-maqsad bo'lsa sababi majburiy (mijoz chatda aynan shu matnni o'qiydi);
- 2-maqsad bo'lsa «qachon mos» majburiy; 2-maqsad 1-sidan boshqa bo'lsin;
- sabab va «qachon mos» 500 belgigacha, cheklovlar 1500 belgigacha.

1-maqsad bo'sh yuborilsa, tavsiya olib tashlanadi.

### 10.3 Tor yo'nalishlar

- `GET /api/v1/office/business-types/{direction_id}/subtypes` — ko'rilmaganlar tepada.
  `?merged=true` birlashtirib yuborilganlarni ham qo'shadi.
- `POST /api/v1/office/business-types/{direction_id}/subtypes` —
  `{"name": "…", "synonyms": ["…"]}`. Shu nom (yoki sinonim) bor bo'lsa yangisi ochilmaydi:
  javobda `created: false` va mavjud qator.
- `PATCH /api/v1/office/business-subtypes/{id}` — `name`, `synonyms`, `is_checked`,
  `is_active` (faqat yuborilgani o'zgaradi). Band nom — `409 subtype_name_taken`.
- `POST /api/v1/office/business-subtypes/{id}/merge` — `{"into_id": "…"}`. Bu qator
  ikkinchisiga qo'shiladi: bizneslari ko'chadi, nomi sinonimga aylanadi. Faqat bitta tur
  ichida.

Qator:

```json
{"id": "…", "direction_id": "…", "name": "Oshxona mebeli", "synonyms": ["kuxnya"],
 "origin": "ai", "is_checked": false, "is_active": true, "merged_into_id": null,
 "businesses": 3, "created_at": "…"}
```

`origin`: `ai` (AI yaratgan) yoki `staff` (ofisda yozilgan).

## 11. AI chat: «Eslab qolish» tugmasi

Kabinet AI chati (`/api/v2/assistant`) endi foydalanuvchi o'z biznesi haqida aytgan
narsani (mahsulot, narx, yetkazib berish, kafolat va h.k.) eslab qolishni taklif qiladi.
Hech narsa o'zi saqlanmaydi: javob ostida yangi turdagi tugma keladi.

Javobning `buttons` ro'yxatida:

```json
{"kind": "knowledge", "key": "K1", "label": "Eslab qolish", "state": "open",
 "state_text": "", "target": "Texno",
 "lines": ["Yangi taklif: Dazmol — 390 000 so'm", "Kafolat: 1 yil kafolat"],
 "business_id": "…", "proposal_id": "…"}
```

- Chizish: `target` (biznes nomi) sarlavha, `lines` — nima saqlanishi ro'yxati, ostida
  ikkita tugma: `label` («Eslab qolish») va «Kerak emas». `change` tugmasining kartasiga
  o'xshash ko'rinish mos keladi.
- Bosish: mavjud `POST /api/v2/assistant/buttons/{message_id}/{key}`. Javob:
  `state: "done"`, `text: "Saqlandi. Keyingi reklamalarda shundan foydalanamiz."`
- Rad etish: mavjud `POST /api/v2/assistant/buttons/{message_id}/{key}/dismiss` →
  `state: "dismissed"`.
- Boshqa holatlar: `gone` (taklif boshqa joyda javob olgan — 5-bo'limdagi API orqali),
  `refused` (`text` da sababi).
- Kutish (`working`) holati yo'q: natija darhol keladi, so'rab turish shart emas.
- Shu taklif 3-bo'limdagi `pending` ro'yxatida ham ko'rinadi (`id` = `proposal_id`);
  qaysi joyda javob berilsa, ikkinchisida `gone` bo'ladi.

Hozirgi kabinet kodi noma'lum `kind` ni oddiy tugma qilib chizadi, shuning uchun eski
front bilan ham ishlaydi: faqat `lines` ko'rinmaydi va «Kerak emas» bo'lmaydi.

## 12. Tayyorgarlikdan (setup) «Biznes ma'lumotlari» qadami olib tashlandi

To'lovdan keyingi tayyorgarlikda foydalanuvchidan biznes ma'lumoti endi so'ralmaydi.

**Backend nima qiladi:**

- Sahifa + reklama akkaunti juftligi yaratilganda (yoki «Yakunlash» bosilganda) sahifa
  uchun biznes profili o'zi yoziladi: nomi sahifa nomidan, shahri sahifadan.
- Bir-ikki daqiqadan keyin AI sahifa nomi va Instagram bio'sidan biznes turini, tor
  yo'nalishini va toza nomini taxmin qiladi. Bu **taxmin** bo'lib saqlanadi
  (`kind.state = "guessed"`), foydalanuvchi tasdiqlagunga qadar.
- AI aniqlay olmasa `kind.state = "unset"` bo'lib qoladi.

**`GET /api/v1/start` o'zgarishi:**

- `setup.steps` va `setup.state` ichida endi `profile` yo'q. Qadamlar:
  `connect`, `page`, `ad_account`, `leads` (+ `telegram`, `pixel`).
- `setup.total` endi 3 (oldin 4 edi).
- `setup.blocked_on` va `next_action` hech qachon `"profile"` bo'lmaydi.
- `setup.facts.has_profile` / `has_category` qoldi, lekin hech narsani to'smaydi.

**Frontda nima qilish kerak:**

1. Tayyorgarlik sahifasidan «Biznes ma'lumotlari» qadami va uning formasini olib
   tashlang; `blocked_on === "profile"` holatiga bog'langan yo'naltirishni ham.
2. Eski profil API lari (`GET/PUT /api/v1/business…`) o'zgarmagan: «Biznes» sahifasidagi
   tahrirlash formasi avvalgidek ishlaydi.
3. Turni tasdiqlash ikki joyda bo'ladi, ikkalasi ham bir xil natija beradi:
   - **AI chatda** — 13-bo'lim (tugma);
   - **«Biznes» sahifasida** — 3-bo'limdagi `kind.state` `guessed` yoki `unset` bo'lsa,
     «Biznes turi: … — to'g'rimi?» kartasini ko'rsating; tasdiq 6-bo'limdagi
     `PUT /api/v3/businesses/{id}/kind` orqali.

## 13. AI chat: biznes turini tasdiqlash tugmasi

Biznes turi taxmin yoki noma'lum bo'lsa, AI chat suhbat orasida bir marta so'raydi va
foydalanuvchi javob bergach tugma tayyorlaydi:

```json
{"kind": "business_kind", "key": "B1", "label": "Tasdiqlash", "state": "open",
 "state_text": "", "target": "Zukko Academy",
 "lines": ["Biznes turi: Ta'lim → ingliz tili kurslari", "Nomi: Zukko"],
 "business_id": "…", "direction_id": "…", "subtype": "ingliz tili kurslari",
 "name": "Zukko"}
```

- Chizish va API lari 11-bo'limdagi `knowledge` tugmasi bilan bir xil: `lines` ro'yxati,
  `label` tugmasi va «Kerak emas».
- Bosilganda: `state: "done"`,
  `text: "Saqlandi. Reklamalar shu yo'nalishga moslab tayyorlanadi."` Shundan keyin
  `kind.state = "confirmed"`; tor yo'nalish bazada bo'lmasa, o'zi yaratiladi.
- `name` bo'sh bo'lmasa, biznes nomi ham shunga o'zgaradi.

## 14. Hali yo'q narsalar

- Reklama yaratish chati — alohida qo'llanma bo'ladi.
