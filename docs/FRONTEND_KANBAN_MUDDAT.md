# Ofis kanbani: muddat, yangi ustunlar, qo'lda karta — frontend ishlari

Backend: `feat/boards-deadline` shoxi, migratsiya `0045`. Avval backend deploy qilinadi.
To'liq API: `docs/OFFICE_V2_API.md`. Bu yerda faqat **nima o'zgardi va frontda nima qilinadi**.

Front fayllari: `apps/office/src/pages/boards/*`, `packages/api/src/officeBoards.ts`,
`packages/api/src/live/bridges/officeBoards.ts`. OpenAPI'ni qayta generatsiya qiling.

Eski front yangi backend bilan buzilmaydi: yangi ustunlar va tugmalar o'zi chiqadi
(ular backenddan keladi). Lekin muddat so'raydigan tugmalar (`callback`, `wait`) va izoh
so'raydigan tugmalar (`release`, `resolve`) eski frontda **422** qaytaradi. Shuning uchun
1–3-bandlar majburiy.

## Nima o'zgardi (qisqa)

| # | O'zgarish |
|---|---|
| 1 | Kartada **muddat** (`due_at`): xodim o'zi qo'yadi, karta yuzida taymer sanaydi |
| 2 | Sotuvda 2 ta yangi ustun: `callback` «Qayta aloqa», `awaiting` «To'lov kutilmoqda» |
| 3 | Supportda 1 ta yangi ustun: `waiting` «Mijoz kutilmoqda» |
| 4 | Yangi tugmalar: `callback`, `will_pay`, `release`, `wait`, `reopen` |
| 5 | Qo'lda karta ochish: Sotuvga lid, Supportga zayavka |
| 6 | Filtrlar: «Faqat meniki», «Bugungi», «Muddati o'tgan», menejer, sabab |
| 7 | «Lid olish» endi eng **yangi** lidni beradi; «Ishlanmagan» ham yangisi tepada |
| 8 | Karta yuzida: chegirma foizi va vaqti, «Hisob ochgan» belgisi, urinishlar soni |

## 1. Tugmalar endi nima so'rashini o'zi aytadi

`GET /cards/{id}` → `actions[]` har bir tugmada ikkita yangi maydon:

```json
{"value": "callback", "label": "Qayta aloqa", "due": "required", "note_required": false}
```

| Maydon | Qiymat | Frontda |
|---|---|---|
| `due` | `"required"` | Tugma bosilganda muddat dialogi ochiladi, vaqtsiz yuborilmaydi |
| `due` | `"optional"` | Dialog ochiladi, vaqtni bo'sh qoldirsa ham bo'ladi |
| `due` | `""` | Vaqt so'ralmaydi |
| `note_required` | `true` | Izoh maydoni majburiy |

Tugma kodiga qarab `if` yozmang, shu ikki maydonga qarang. Hozir shunday keladi:

| Tugma | `due` | `note_required` |
|---|---|---|
| `callback` (Qayta aloqa) | required | — |
| `wait` (Mijoz kutilmoqda) | required | — |
| `no_contact` (Bog'lanilmadi) | optional | — |
| `will_pay` (To'laydi) | optional | — |
| `release` (Navbatga qaytarish / Voz kechish) | — | ha |
| `resolve` (Hal qilindi) | — | ha |
| qolganlari | — | — |

`close` avvalgidek o'z dialogiga ega (sabab). `needs_support` avvalgidek switch.

So'rov: `POST /cards/{id}/actions`

```json
{"action": "callback", "due_at": "2026-11-13T10:00:00+05:00", "note": "Ertaga qo'ng'iroq"}
```

- `due_at` — **zona bilan** ISO vaqt (`+05:00` yoki `Z`). Zonasiz yuborilsa 422 `due_invalid`.
- Xatolar: 422 `due_required`, 422 `due_past` (o'tgan vaqt), 422 `due_invalid`, 422 `note_required`.

**Qilinadi:** `CardPanel.tsx → Actions`: `due` yoki `note_required` bor tugma uchun bitta
umumiy `ActionDialog` (vaqt tanlash + izoh). Qolgan tugmalar avvalgidek darhol yuboriladi.

## 2. Muddat (timer)

### Kartada keladigan maydonlar (ro'yxatda ham, kartaning o'zida ham)

| Maydon | Ma'nosi |
|---|---|
| `due_at` | Muddat (ISO) yoki `null` |
| `overdue` | `true`: muddat o'tgan (server hisoblagan) |

### Muddatni qo'yish, o'zgartirish, olib tashlash

`PUT /api/v2/office/cards/{id}/due`

```json
{"due_at": "2026-11-13T10:00:00+05:00", "note": "Ixtiyoriy izoh"}
```

`"due_at": null` — muddatni olib tashlaydi. Javob: karta. Karta ustunidan qimirlamaydi.

- Yopilgan kartada: 409 `card_closed`.
- Support: boshqa xodim ishlayotgan kartada 409 `ticket_held`.

### Muddat dialogi (bitta komponent, ikki joyda ishlatiladi)

Tez tanlovlar va aniq vaqt:

- «1 soatdan keyin», «Bugun 18:00», «Ertaga 10:00»
- sana + vaqt tanlash (`datetime-local`)

Vaqt **Toshkent vaqti** bilan ko'rsatiladi va shu zonada yuboriladi (`+05:00`).
«Bugun 18:00» o'tib ketgan bo'lsa, tugmani yashiring.

### Karta yuzida (`Card.tsx`)

`due_at` bo'lsa, taymer chizig'i chiqadi va **har daqiqada** qayta hisoblanadi
(`due_at` dan hozirgi vaqtni ayiring; serverni so'rash shart emas):

| Holat | Ko'rinish |
|---|---|
| 24 soatdan ko'p qolgan | «13-noy 10:00» (kulrang) |
| 24 soatdan kam | «2 soat 15 daq qoldi» |
| 1 soatdan kam | «25 daq qoldi» (sariq) |
| O'tgan | «1 soat 10 daq kechikdi» (qizil), karta chetida qizil chiziq |

Ustun ichida tartibni backend beradi: **muddati eng yaqin karta tepada**, muddatsizlar
pastda. Frontda qayta saralamang.

### Karta ichida (`CardPanel.tsx`)

«Mijoz ma'lumotlari» ostida «Muddat» qatori: vaqt + taymer, «O'zgartirish» va
«Olib tashlash» tugmalari; muddat yo'q bo'lsa «Muddat qo'yish». Yopilgan kartada ko'rsatmang.

Ustunni o'zgartiradigan har qanday tugma muddatni o'chiradi (yangi muddat bilan
yuborilmasa). Tarixda `due_set` «Muddat qo'yildi», `due_cleared` «Muddat olib tashlandi»
qatorlari keladi; ular oddiy tarix qatori kabi chiziladi.

### Doska tepasida

`GET /boards/{board}` javobida yangi maydon:

```json
"due": {"overdue": 3, "today": 7}
```

Qidiruv yonida ikkita chip: «Muddati o'tgan · 3» (qizil, 0 bo'lsa kulrang),
«Bugungi · 7». Bosilsa filtr yoqiladi (3-band).

## 3. Filtrlar

`GET /boards/{board}` ga yangi parametrlar (hammasi ixtiyoriy, `q` bilan birga ishlaydi):

| Parametr | Qiymat | Ma'nosi |
|---|---|---|
| `mine` | `true` | Faqat o'zimning kartalarim |
| `manager` | xodim `id` yoki `none` | Shu xodimniki / hech kimniki emas |
| `due` | `overdue`, `today`, `set` | Muddati o'tgan / bugungi / muddati bor |
| `reason` | sabab kodi | Faqat Support: `setup`, `meta_error`, `manual`, … |

- Filtrlarni manzilga yozing (`?mine=1&due=overdue`), `q` kabi. «Yana yuklash» va 30 soniyalik
  yangilash ham shu parametrlarni yuborishi kerak (`fetchBoardColumn`, `useBoard` kaliti).
- `mine`: Sotuv menejeri uchun yashiring (u baribir faqat o'zinikini ko'radi).
- `manager`: faqat rahbar, Owner, superuser uchun; ro'yxat `GET /boards/{board}/staff` dan.
- `reason`: faqat Support doskasida; variantlar 6-banddagi kodlar.

## 4. Yangi ustunlar va tugmalar

Ustunlar backenddan keladi, kod o'zgartirish shart emas. Faqat rang qo'shing
(`shared.tsx → LANE_COLOR`), chegirma ustunlarining rangi ham hozir yo'q:

| `code` | Nomi | Taklif rang |
|---|---|---|
| `callback` | Qayta aloqa | `--k-view` |
| `awaiting` | To'lov kutilmoqda | `--k-click` |
| `discount_20` | 20% chegirma | `--ok` |
| `discount_10` | 10% chegirma | `--warn` |
| `no_discount` | Chegirmasiz | `--k-neutral` |
| `waiting` (Support) | Mijoz kutilmoqda | `--warn` |

Sotuv ustunlari tartibi: Ishlanmagan → Yangi lead → Bog'lanilmadi → Bog'lanildi →
**Qayta aloqa** → 20% → 10% → Chegirmasiz → **To'lov kutilmoqda** → Sotildi → Yopildi.
Support: Yangi → Ishlanmoqda → **Mijoz kutilmoqda** → Hal qilindi.

Tugmalar (qaysi ustunda qaysi tugma — backend beradi, bu faqat ma'lumot uchun):

| Tugma | Nima qiladi |
|---|---|
| `callback` | → Qayta aloqa, muddat majburiy |
| `will_pay` | → To'lov kutilmoqda |
| `no_contact` | → Bog'lanilmadi; har bosishda `attempts` +1 (o'sha ustunda ham bosiladi) |
| `release` (Sotuv) | Menejer lidni navbatga qaytaradi (→ Ishlanmagan); izoh majburiy |
| `wait` | Support: → Mijoz kutilmoqda, muddat majburiy |
| `start` | Support: Yangi yoki Mijoz kutilmoqda → Ishlanmoqda |
| `release` (Support) | «Voz kechish»: zayavka «Yangi» ga qaytadi, mas'ul yo'q; izoh majburiy |
| `resolve` | → Hal qilindi; **izoh endi majburiy** (nima qilingani) |
| `reopen` | Support: Hal qilindi → Ishlanmoqda; boshqa xodim ham bosa oladi |

`release` dan keyin Sotuv menejeri kartani endi ko'rmaydi (`GET /cards/{id}` 404):
javob kelgach dialogni yoping va doskani yangilang.

Karta o'zi ko'chadigan yangi holatlar (har daqiqada, tarixda tizim nomidan):

- Mijoz tarif hisobini ochdi → «To'lov kutilmoqda» (`bill_opened`). Chegirma ustunidagi
  karta ko'chmaydi, unda faqat `has_bill` belgisi chiqadi.
- Hisob muddati o'tdi, to'lanmadi → «Qayta aloqa», muddati darhol o'tgan (`bill_unpaid`).
- Support: mijoz Yordam chatiga yozdi → «Mijoz kutilmoqda» dan «Ishlanmoqda» ga (`client_replied`).

`isStale` (`shared.tsx`) ro'yxatiga hech narsa qo'shish shart emas.

## 5. Qo'lda karta ochish

Ruxsat `GET /me → can`:

| Maydon | Kimda `true` | Tugma |
|---|---|---|
| `can.add_lead` | Sotuv rahbari, Owner, superuser | Sotuv doskasida «Lid qo'shish» |
| `can.add_ticket` | Support, Owner, superuser | Support doskasida «Zayavka ochish» |

### Mijozni qidirish

`GET /api/v2/office/boards/{board}/clients?q=` (kamida 3 belgi; ism, email, telefon)

```json
{"clients": [{"id": "…", "name": "Vali", "email": "…", "phone": "+998…", "signed_up_at": "…",
              "card": {"id": "…", "column": "contacted", "closed": false}}]}
```

Faqat saytda ro'yxatdan o'tgan mijozlar chiqadi (xodimlar va CRM loginlari yo'q).
`card` — shu doskada mijozning kartasi bor bo'lsa. Sotuvda `card` bor va `closed: false`
bo'lsa, qatorda «Kartasi bor» deb ko'rsating va bosilganda o'sha kartani oching.

### Ochish

`POST /api/v2/office/boards/{board}/cards` → **201**, javob: karta.

Sotuv:
```json
{"user_id": "…", "note": "Instagramdan yozdi", "staff_id": null}
```
- `staff_id` bo'sh: karta «Ishlanmagan» ga tushadi. Berilsa: shu menejerga, «Yangi lead» ga.
  Menejerlar ro'yxati: `GET /boards/sales/staff`.
- Yopilgan kartasi bor mijoz: o'sha karta tarixi bilan qayta ochiladi.
- 409 `card_exists` (ochiq kartasi bor), 409 `client_paid` (tarif sotib olgan), 422 `client_not_found`.

Support:
```json
{"user_id": "…", "note": "Telefon qildi: reklama to'xtab qolgan"}
```
- `note` **majburiy** (422 `note_required`): u zayavkaning sababi bo'lib kartada chiqadi.
- Mijozning zayavkasi bor bo'lsa, yangi karta ochilmaydi: sabab o'sha kartaga qo'shiladi
  («Hal qilindi» da bo'lsa, qayta ochiladi). Xato qaytmaydi.

Dialog: qidiruv → mijozni tanlash → izoh (+ Sotuvda menejer tanlash) → «Qo'shish».
Muvaffaqiyatdan keyin kartani oching (`cardUrl`).

## 6. Karta yuzidagi yangi ma'lumotlar

Ro'yxatdagi har bir kartada (`CardOut`) yangi maydonlar:

| Maydon | Frontda |
|---|---|
| `attempts` | Sotuv, > 0 bo'lsa: «3 marta bog'lanilmadi» belgisi |
| `offer` | `{percent, started_at, ends_at}` yoki `null`. `percent > 0`: «−20% · 5 soat qoldi» (`ends_at` ga taymer). `percent = 0`: ko'rsatmang |
| `has_bill` | `true`: «Hisob ochgan» belgisi |
| `reason_chips` | `[{code, label}]`: Support sabablari **tayyor nomi bilan**. `useReasonWords` o'rniga shundan chizing — `ai` («AI chatdan») va `manual` («Qo'lda ochilgan») shu yerdan keladi |
| `due_at`, `overdue` | 2-band |

`REASON_TONE` ga rang qo'shing: `ai: "--k-chat"`, `manual: "--k-neutral"`.

Kartaning ichida (`CardDetailOut`) qo'shimcha:

- `bill`: `{number, plan, amount_minor, currency, status, expires_at}` yoki `null` — mijoz ochgan,
  hali to'lasa bo'ladigan hisob. «Mijoz ma'lumotlari» ga qator: «Hisob: Standart · 490 000 so'm ·
  18:30 gacha». `amount_minor` tiyinda (100 ga bo'ling).
- `offer` endi ro'yxatda ham keladi; kartaning ichida ham ko'rsating (hozir ko'rsatilmayapti):
  «Chegirma: 20% · 13-noy 14:00 gacha».

## 7. «Lid olish»

So'rov o'zgarmagan (`POST /sales/take`). Faqat tartib o'zgardi: eng **yangi** ro'yxatdan
o'tgan lid beriladi. Frontda o'zgarish yo'q.

## 8. Tekshirish ro'yxati

- [ ] `callback` va `wait`: vaqtsiz yuborib bo'lmaydi; vaqt bilan karta ko'chadi va taymer chiqadi
- [ ] `release`, `resolve`: izohsiz yuborib bo'lmaydi
- [ ] Muddat qo'yish / o'zgartirish / olib tashlash karta ichidan ishlaydi
- [ ] Taymer daqiqada yangilanadi; o'tgan karta qizil va ustun tepasida
- [ ] «Muddati o'tgan» va «Bugungi» chiplari soni to'g'ri, bosilganda filtr ishlaydi
- [ ] Filtr yoqilganda «Yana yuklash» va 30 soniyalik yangilash filtrni saqlaydi
- [ ] «Lid qo'shish» faqat `can.add_lead`, «Zayavka ochish» faqat `can.add_ticket` da ko'rinadi
- [ ] Supportda `ai` va `manual` sabablari nomi bilan chiqadi
- [ ] Chegirma ustunidagi kartada foiz va qolgan vaqt ko'rinadi
- [ ] Sotuv menejeri `release` bosgach dialog yopiladi, karta doskadan yo'qoladi
