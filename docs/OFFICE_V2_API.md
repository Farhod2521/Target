# Ofis v2: Sotuv, Support va Uzaytirish kanbanlari

> **2026-11-13:** Support doskasining qoidalari o'zgardi (faqat o'z zayavkalari, «Zayavka olish», yangi ustunlar, mijoz tasdig'i). Support bo'yicha amaldagi hujjat: [SUPPORT_KANBAN_YANGI_QOIDALAR.md](SUPPORT_KANBAN_YANGI_QOIDALAR.md).

Ofisdagi Sotuv bo'limining yangi versiyasi. Ikkita alohida kanban bor:
**Sotuv** (`sales`) va **Support** (`support`). Hamma yo'llar `/api/v2/office/...`
da. v1 (`/api/v1/office/sales/...`) o'zgarmagan va v2 ga aralashmaydi.

Hamma so'rovlar xodim tokeni bilan yuboriladi: `Authorization: Bearer <token>`.
Ruxsati yo'q xodimga yoki mijozga hamma yo'l **404** qaytaradi.

Kanbanni har **30 soniyada** qayta so'rab turing, WebSocket yo'q.

## 1. Kim nimani ko'radi

| Rol | Ko'radi | Qila oladi |
|---|---|---|
| `Sales` (Sotuv menejeri) | Sotuv kanbani, faqat o'z kartalari | Lid olish, tugmalar, izoh |
| `SalesLead` (Sotuv rahbari) | Butun Sotuv kanbani, «Ishlanmagan» va «Yopildi» ham | Kartani menejerga berish yoki qaytarib olish |
| `Support` | Butun Support kanbani | Tugmalar, izoh |
| Superuser va `Owner` | Ikkala kanban | Hammasi: ko'chirish, ustunlar, xodimlar, so'rovnoma belgilari, «Lid olish» ham |

### `GET /api/v2/office/me`

Sahifa ochilganda birinchi shu chaqiriladi.

```json
{
  "user": {"id": "…", "name": "Ali", "email": "ali@…"},
  "roles": [{"value": "Sales", "label": "Sotuv menejeri"}],
  "is_superuser": false,
  "boards": [{"code": "sales", "label": "Sotuv", "lead": false}],
  "default_board": "sales",
  "can": {"take": true, "assign": false, "move": false, "add_lead": false, "add_ticket": false,
          "columns": false, "staff": false}
}
```

- `boards` bo'sh bo'lsa, bu xodimga kanban yo'q: menyuda ko'rsatmang.
- `default_board`: birinchi ochiladigan kanban.
- `can.take`: «Lid olish» tugmasi. `can.assign`: kartani boshqa xodimga berish.
  `can.move`, `can.columns`, `can.staff`: superuser va Egasi uchun.
- `can.add_lead`: Sotuvga qo'lda lid qo'shish (rahbar, Egasi, superuser).
  `can.add_ticket`: Supportga qo'lda zayavka ochish (Support, Egasi, superuser).

## 2. Kanban

### `GET /api/v2/office/boards/{board}`

`board`: `sales` yoki `support`. Parametrlar (hammasi ixtiyoriy):

| Parametr | Ma'nosi |
|---|---|
| `q` | Mijozning ismi, emaili yoki telefoni bo'yicha qidiruv |
| `column` | Faqat bitta ustun (keyingi sahifa uchun) |
| `offset`, `limit` | Shu ustunning sahifasi; `limit` 1–200, odatda 50 |
| `mine` | `true`: faqat o'qiyotgan xodimning kartalari |
| `manager` | Xodim `id` si yoki `none` (hech kimniki emas) |
| `due` | `overdue` (muddati o'tgan), `today` (ofis kuni bo'yicha bugungi), `set` (muddati bor) |
| `reason` | Support: sabab kodi (`setup`, `manual`, …) |

```json
{
  "board": "sales",
  "due": {"overdue": 3, "today": 7},
  "columns": [
    {
      "code": "new_lead", "name": "Yangi lead", "position": 2,
      "kind": "manual", "is_final": false, "total": 12,
      "cards": [
        {
          "id": "…", "board": "sales", "column": "new_lead",
          "client": {"id": "…", "name": "Vali", "email": "…", "phone": "+998…", "signed_up_at": "…"},
          "manager": {"id": "…", "name": "Ali", "email": "…"},
          "contact_mark": "", "attempts": 0, "needs_support": false,
          "reasons": [], "reason_chips": [],
          "due_at": "2026-11-13T05:00:00Z", "overdue": false,
          "offer": null, "has_bill": false,
          "opened_at": "…", "column_since": "…", "closed_at": null
        }
      ]
    }
  ]
}
```

- Ustunlar `position` tartibida keladi; ularning nomini va tartibini ofis o'zgartirishi mumkin.
  Mantiqni hech qachon nomga emas, **`code`** ga bog'lang.
- `total`: ustundagi kartalar soni (qidiruv bilan). Kartalar dastlab 50 tadan keladi,
  qolganini `?column=<code>&offset=50` bilan oling.
- `due`: doskadagi muddatlar soni, shu qidiruv va filtrlar bilan (`due` filtridan qat'i nazar).
- Ustun ichida **muddati eng yaqin karta tepada**, muddatsizlar pastda. «Ishlanmagan» da
  eng yangi lid tepada («Lid olish» ham shuni beradi), Support «Yangi» da eng eskisi.
- `due_at`: xodim qo'ygan muddat; `overdue`: u o'tgan. `attempts`: «Bog'lanilmadi» necha marta
  bosilgan. `offer`: berilgan chegirma (`percent` 0 bo'lsa tugagan). `has_bill`: mijoz tarif
  hisobini ochgan va hali to'lasa bo'ladi. `reason_chips`: Support sabablari nomi bilan.
- Kartani sudrab ko'chirib bo'lmaydi (drag-and-drop yo'q). Karta faqat tugma yoki
  avtomatik hodisa bilan ko'chadi.

### Ustunlar

**Sotuv:**

| `code` | Nomi | Turi | Kim ko'radi |
|---|---|---|---|
| `unworked` | Ishlanmagan | avto | Rahbar |
| `new_lead` | Yangi lead | tugma | Ega menejer, rahbar |
| `no_contact` | Bog'lanilmadi | tugma | Ega menejer, rahbar |
| `contacted` | Bog'lanildi | tugma | Ega menejer, rahbar |
| `callback` | Qayta aloqa | tugma (muddat majburiy) | Ega menejer, rahbar |
| `discount_20` | 20% chegirma | avto | Ega menejer, rahbar |
| `discount_10` | 10% chegirma | avto | Ega menejer, rahbar |
| `awaiting` | To'lov kutilmoqda | avto (mijoz hisob ochsa) | Ega menejer, rahbar |
| `sold` | Sotildi | avto, yakuniy | Ega menejer, rahbar |
| `closed` | Yopildi | tugma, yakuniy | Rahbar |

**Chegirma (2026-11-13 dan o'zi boshlanadi).** «Chegirma berish» tugmasi yo'q.
Soat ikki joydan boshlanadi: mijoz **Start sotib olsa** (to'lov payti), yoki Start olmagan
lidda menejer **«Gaplashildi»** ni bossa (bosilgan payt, har mijozga bir marta). Karta
«20% chegirma» ga tushadi: 24 soat 20%, keyin yana 72 soat 10% (96-soatgacha), keyin karta
**«Yopildi»** ga o'tadi (`close_reason: "offer_ended"`, «Chegirma tugadi»). «Chegirmasiz»
ustuni yashirilgan (migration `0053`, bo'sh bo'lsa). Bu o'tishlarni tizim har daqiqa o'zi
qiladi. Start to'lovi **sotuv emas**: karta «Sotildi» ga faqat Standart/Pro to'langanda
o'tadi; Start olgan mijozning kartasi ochiq qoladi (yopilgan bo'lsa qayta ochiladi) va
menejeri saqlanadi, menejeri yo'q bo'lsa «Lid olish» avval shularni beradi. Chegirma
ustunlarida «Gaplashildi», «Bog'lanib bo'lmadi», «Vaqt qo'yish» kartani **ko'chirmaydi** —
`contact_mark`, `attempts`, `due_at` ga belgi qo'yadi. Chegirma mijozning **birinchi to'liq**
tarif to'loviga tushadi (qo'shimcha sahifa va o'rinlarga, Start'ga emas). Tartib: asl narx →
Start'ning qolgan kunlari → qolgan summadan foiz → promokod → hamyon. Chegirma kartaning
ustuniga qaramaydi: soat to'lov yoki suhbat paytining o'zi. Shu chegirma bilan narxlangan
to'lov bosqich tugaganidan 15 daqiqa keyingacha to'lanadi. Suhbatdan boshlangan
chegirma karta yopilsa to'xtaydi; Start to'lovidan boshlangani faqat vaqti bilan tugaydi.
Kartani qo'lda boshqa ustunga ko'chirish chegirmani to'xtatmaydi.

Mijoz kabinetida: `GET /api/v1/billing` va `GET /api/v1/billing/paywall` javobida
`sales_offer: {percent, ends_at, pay_until}` (yoki `null`). Tarif kartalari
(`cards[].offer`) va `chosen` da: `price_minor` asl narx, `offer_minor` sotuv chegirmasi,
`promo_minor` promokod (faqat `chosen`), `discount_minor` = ikkalasi, `wallet_minor` hamyon,
`due_minor` to'lanadigan summa. `promo_quote.base_minor` = chegirmadan keyingi narx.
Start va bir martalik tariflarga sotuv chegirmasi berilmaydi: ularda `offer_minor` = 0.

`trial` ustuni bazada bor, lekin hozircha yashirin: kelmaydi. Bepul sinov qilinganda chiqadi.

**Support:** `new` (Yangi), `in_progress` (Ishlanmoqda), `waiting` (Mijoz kutilmoqda,
muddat majburiy), `resolved` (Hal qilindi, yakuniy).

### `GET /api/v2/office/boards/{board}/columns`

Faqat ustunlar (kartasiz) va `live_since`: kanban ishga tushgan vaqt.

## 3. Karta

### `GET /api/v2/office/cards/{id}`

Kartaning hammasi: `card` maydonlari, hamda:

```json
{
  "client": {"…": "…", "role": "business", "language": "uz", "last_login": "…",
             "plan": {"name": "Standart", "status": "active", "expires_at": "…", "setup_done": false}},
  "ticket_reasons": [{"code": "meta_error", "label": "Meta xatosi", "detail": "Reklama ishga tushmadi: …", "at": "…"}],
  "support_chat_id": "…",
  "offer": {"percent": 20, "started_at": "…", "ends_at": "…", "source": "start", "next_percent": 10, "next_ends_at": "…"},
  "close_reason": "expensive", "close_reason_label": "Qimmat", "close_note": "",
  "bill": {"number": "TA-…", "plan": "Standart", "amount_minor": 49000000, "currency": "UZS",
           "status": "pending", "expires_at": "…"},
  "actions": [{"value": "callback", "label": "Qayta aloqa", "due": "required", "note_required": false}],
  "history": [{"kind": "taken", "label": "Lid olindi", "from_column": "unworked", "to_column": "new_lead",
               "actor": {"id": "…", "name": "Ali", "email": "…"}, "body": "", "at": "…"}]
}
```

- **`actions`**: kartada ko'rsatiladigan tugmalar, tartibi bilan. Faqat shularni chizing.
  `due`: `required` (vaqt so'rang va `due_at` da yuboring), `optional` yoki bo'sh.
  `note_required`: izoh majburiy.
- `bill`: mijoz ochgan va hali to'lasa bo'ladigan tarif hisobi, yo'q bo'lsa `null`.
- `history`: eng yangisi birinchi. `actor: null` bo'lsa, buni tizim qilgan.
- `ticket_reasons`: Support kartasi nega ochilgani (eng yangisi birinchi).
- `support_chat_id`: mijozning Yordam chati bo'lsa, shu chatni ochish uchun.
- `offer`: Sotuv kartasiga chegirma berilgan bo'lsa: hozirgi foiz va u qachon tugashi.
  Chegirma tugagan yoki karta yopilgan bo'lsa `percent: 0`, `ends_at: null`. Berilmagan bo'lsa `null`.

### `GET /api/v2/office/cards/{id}/client`

Karta mijozi qisqacha, faqat o'qish uchun (`CardClientOut`): `profile`, `businesses`, `subscription`, `meta`,
`pages`, `telegram`, `bills` (oxirgi 10 ta). Kartani ko'ra olgan har bir xodim o'qiydi — Sotuv va Uzaytirish
menejeri ham; to'liq ofis kartasi (`can.client_card`) Support, Moliya va Egasida qoladi. O'qish jurnalga yoziladi.

### `POST /api/v2/office/sales/take`

«Lid olish». Body yo'q. «Ishlanmagan» dagi xodimsiz lid shu menejerga beriladi va
«Yangi lead» ga o'tadi (tartib: §11). Javob: karta (yuqoridagi shakl).
Lid qolmagan bo'lsa: **409** `nothing_to_take`. Sotuv rollarida, superuserda va `Owner` da ishlaydi.

### `POST /api/v2/office/cards/{id}/actions`

```json
{"action": "contacted", "note": "Ertaga to'laydi"}
```

| `action` | Qaysi ustunda | Nima bo'ladi |
|---|---|---|
| `contacted` («Gaplashildi») | Yangi lead, Bog'lanilmadi, Qayta aloqa, 20%, 10% | Chegirmasi hali bo'lmagan lid: → 20% chegirma, soat boshlanadi. Chegirma ustunida: belgi, karta joyida. Chegirmasi ishlatilgan lid: → Bog'lanildi |
| `no_contact` («Bog'lanib bo'lmadi») | Yangi lead, Bog'lanilmadi, Qayta aloqa, 20%, 10% | → Bog'lanilmadi (chegirma ustunida joyida), `attempts` +1; `due_at` ixtiyoriy |
| `callback` («Vaqt qo'yish») | Yangi lead, Bog'lanilmadi, Bog'lanildi, Qayta aloqa, 20%, 10%, To'lov kutilmoqda | → Qayta aloqa (chegirma ustunida joyida); `due_at` **majburiy** |
| `needs_support` | Bog'lanildi, Qayta aloqa, 20%, 10%, To'lov kutilmoqda | «Support kerak» belgisi; yoqishda `note` (sabab) **majburiy**, `"on": false` izohsiz olib tashlaydi. Mijoz to'lagan bo'lsa (Start ham) zayavka shu daqiqada ochiladi |
| `close` («Yopish») | Yopiq bo'lmagan hamma ustun (Ishlanmagandan tashqari) | → Yopildi; `reason` majburiy |
| ~~`will_pay`, `offer`, `release` (Sotuv)~~ | — | Olib tashlangan: **409** `action_not_here`. Lidni qaytarish faqat rahbar/Owner/superuser: `POST /cards/{id}/assign` `{"staff_id": null}` (chegirma ustunidagi karta joyida qoladi, menejersiz) |
| `start` | Support: Yangi, Mijoz kutilmoqda | → Ishlanmoqda; mas'uli yo'q bo'lsa, bosgan xodim mas'ul bo'ladi |
| `wait` | Support: Ishlanmoqda | → Mijoz kutilmoqda; `due_at` **majburiy** |
| `resolve` | Support: Ishlanmoqda, Mijoz kutilmoqda | → Hal qilindi; `note` **majburiy** |
| `release` | Support: Ishlanmoqda, Mijoz kutilmoqda | «Voz kechish»: → Yangi, mas'ulsiz; `note` majburiy |
| `reopen` | Support: Hal qilindi | → Ishlanmoqda, avvalgi mas'ulga (yo'q bo'lsa bosganga); har qanday Support xodimi bosa oladi |

- `close` uchun `reason`: `GET /api/v2/office/boards/sales/reasons` dagi qiymat
  (`expensive`, `not_needed`, `no_answer`, `wrong_number`, `other`). `other` bo'lsa `note` majburiy.
- `note` tarixga yoziladi. `due_at`: zona bilan ISO vaqt; kelajakda, ko'pi bilan 1 yil.
- Ustunni o'zgartiradigan tugma kartaning muddatini o'chiradi, agar yangi `due_at` berilmasa.
- 20% va 10% ustunidagi karta chegirma tugaguncha shu yerda turadi (to'lov chegirmani
  ustundan o'qiydi), shuning uchun unda ko'chiradigan tugma yo'q.
- Javob: yangilangan karta.

### `PUT /api/v2/office/cards/{id}/due`

Muddatni qo'yish, o'zgartirish yoki olib tashlash. Karta ustunida qoladi.

```json
{"due_at": "2026-11-13T10:00:00+05:00", "note": ""}
```

`"due_at": null` olib tashlaydi. Kim: kartani ko'radigan xodim (Sotuv menejeri o'zinikiga,
rahbar hammasiga; Supportda mas'ul yoki mas'ulsiz kartaga har kim; superuser va Egasi hammasiga).
Xatolar: 409 `card_closed`, 409 `ticket_held`, 422 `due_past`, 422 `due_invalid`.

### Qo'lda karta: `POST /api/v2/office/boards/{board}/cards`

```json
{"user_id": "…", "note": "Instagramdan", "staff_id": null}
```

- **Sotuv** (`can.add_lead`): to'lamagan mijoz lid bo'ladi: «Ishlanmagan» ga yoki `staff_id`
  berilsa o'sha menejerga «Yangi lead» ga. Yopilgan kartasi bo'lsa, o'sha karta qayta ochiladi.
  409 `card_exists`, 409 `client_paid`.
- **Support** (`can.add_ticket`): `note` majburiy. Mijozning zayavkasi ochiladi (sabab `manual`);
  bor bo'lsa, sabab o'sha kartaga qo'shiladi, «Hal qilindi» dagi karta qayta ochiladi.
- 422 `client_not_found`: xodim, CRM logini yoki bloklangan hisob. Javob **201**: karta.

Mijozni topish: `GET /api/v2/office/boards/{board}/clients?q=` (kamida 3 belgi) →
`{"clients": [{id, name, email, phone, signed_up_at, card: {id, column, closed} | null}]}`.

### `POST /api/v2/office/cards/{id}/notes`

```json
{"body": "Qayta qo'ng'iroq qilish kerak"}
```

### `POST /api/v2/office/cards/{id}/assign`

Rahbar (Support uchun: superuser yoki Egasi) kartani xodimga beradi:

```json
{"staff_id": "…"}
```

`"staff_id": null`: qaytarib olish (Sotuv kartasi «Ishlanmagan» ga, Support «Yangi» ga).
Kimga berish mumkinligi: `GET /api/v2/office/boards/{board}/staff`.

### `POST /api/v2/office/cards/{id}/move`

Superuser va Egasi uchun: kartani shu kanbanning istalgan ko'rinadigan ustuniga ko'chirish.

```json
{"column": "closed", "reason": "Dublikat"}
```

`reason` majburiy. Yakuniy ustunga ko'chirilsa karta yopiladi, undan chiqarilsa ochiladi.

## 4. Kartalar o'zi qachon paydo bo'ladi

Hammasi faqat **deploydan keyin** bo'lgan hodisalar uchun ishlaydi; undan oldingilari kanbanga tushmaydi.

**Sotuv** (har daqiqada):
- Ro'yxatdan o'tdi va hech qachon to'lamagan → «Ishlanmagan» da lid. Xodimlar, CRM loginlari va
  bloklanganlar tushmaydi.
- Start tarifi tugadi, to'liq tarif olinmagan va Sotuvda kartasi yo'q → «Ishlanmagan» da lid (`start_expired`), tarixda «Start tarifi tugadi».
- Start to'ladi → karta «Ishlanmagan» da (kartasi bo'lmasa ochiladi, yopilgan bo'lsa xodimsiz qayta ochiladi);
  chegirma ustuniga faqat menejer «Gaplashildi» ni bosganda o'tadi (§11).
- Mijoz tarif uchun to'ladi → istalgan ustundan «Sotildi».
- Menejeri bor mijoz tarif hisobini ochdi → «To'lov kutilmoqda» (har hisob uchun bir marta;
  20% va 10% ustunidagi karta ko'chmaydi, unda faqat `has_bill` yonadi).
- Shu hisob to'lanmay muddati o'tdi → «Qayta aloqa», muddati shu zahoti o'tgan. «To'laydi»
  tugmasi bilan qo'yilgan karta o'zi qaytmaydi.

**Support**: bitta mijozga **bitta** karta. Yangi sabab shu kartaga qo'shiladi.
Tasdiq kutayotgan (`confirming`) zayavkaga yangi sabab kelsa, u qayta ochiladi va o'sha xodimga qaytadi. To'liq yopilgan (`resolved`, `closed`) zayavkaga yangi sabab kelsa, u xodimsiz «Yangi» navbatiga tushadi (keyingi «Zayavka olish» bosganga beriladi). Mijozning o'z tugmasidagi Meta xatosi va chatdagi oddiy xabari yopilgan zayavkani ochmaydi: Meta xatosi tarixga `after_close` («Yopilgandan keyin keldi») bo'lib yoziladi. Support xodimi yopilgan zayavkani qo'lda ochsa, u o'ziga tushadi.

| `reasons` kodi | Qachon |
|---|---|
| `setup` | To'lovdan 1 soat o'tdi, sozlash tugamagan |
| `from_sales` | Sotuvda «Support kerak» belgisi bor mijoz to'ladi (darhol) |
| `meta_error` | Reklamani ishga tushirishni yoki mijozning Meta'dagi amalini Meta rad etdi va 30 daqiqada tuzalmadi (shu orada qayta urinishda yaratilgan launch yoki keyin bajarilgan xuddi shu amal zayavka ochmaydi). O'tib ketadigan xatolar (`temporary`, `already`, …), mijozning o'z sozlamasi (`site_missing`, `profile_incomplete`, …) va bizning xatolarimiz (`unknown`, `schema_error`, `stalled`, `not_applied`, …) kirmaydi. Bizning xatolarimiz Developerga boradi: `/office/faults`. Bir xil amal bir xil sabab bilan kuniga bitta sabab bo'ladi |
| `survey` | So'rovnomada «yordam kerak» deb belgilangan variantni tanladi |
| `ai` | Mijoz AI chatda «Mutaxassisga yuborish» ni bosdi |
| `manual` | Ofisda qo'lda ochildi |
| `idle` | To'lovdan 3 kun o'tib birorta reklama yoqilmagan, yoki faol reklamada 24 soat sarf 0 (soatiga bir tekshiriladi) |

«Mijoz kutilmoqda» dagi zayavka: mijoz Yordam chatiga yozsa, karta o'zi «Ishlanmoqda» ga qaytadi.

## 5. Sozlamalar (superuser va Egasi)

### Ustunlar: `PATCH /api/v2/office/boards/{board}/columns`

Hamma ko'rinadigan ustunlarni yangi tartibda va nomi bilan yuboring:

```json
{"columns": [{"code": "new", "name": "Kelgan"}, {"code": "in_progress", "name": "Jarayonda"},
             {"code": "waiting", "name": "Kutilmoqda"}, {"code": "resolved", "name": "Tayyor"}]}
```

Ro'yxat to'liq bo'lmasa: **422** `columns_mismatch`. Kodlar o'zgarmaydi.

**2026-11-23 dan: ustunlarni faqat superuser o'zgartiradi** (`me.can.edit_columns`,
javobdagi `may_edit`). Egasi sozlamalarni ochadi va o'qiydi (`can.columns`), o'zgartirsa **403**.

### Ustun qo'shish: `POST /api/v2/office/boards/{board}/columns`

```json
{"name": "Demo ko'rsatildi", "after": "contacted"}
```

`after` — qaysi ko'rinadigan ustundan keyin tursin; bo'sh bo'lsa birinchi yakuniy ustundan
(Sotildi, Hal qilindi, Uzaytirdi) oldin. Javob **201**: doskaning barcha ustunlari
(`GET .../columns` bilan bir xil). Yangi ustun: `code` = `c_` + 10 belgi, `is_custom: true`,
`kind: "manual"`, `is_final: false`.

Qoidasi: bu ustunni hech bir avtomatik qoida va hech bir tugma bilmaydi. Karta unga faqat
`POST /cards/{id}/move` bilan kiradi va chiqadi, kartada `actions` bo'sh. To'lov kelsa karta
baribir «Sotildi»ga o'tadi (u har qanday ustundan ishlaydi).

Xatolar (**422**): `column_name_required`, `column_name_taken` (shu doskada shu nom bor),
`too_many_columns` (ko'rinadigan ustun 20 tadan oshmaydi, `max_columns`), `no_such_column` (`after`).

### Ustunni olib tashlash: `DELETE /api/v2/office/boards/{board}/columns/{code}`

Faqat `is_custom` ustun. O'chirilmaydi, yashiriladi: javobning `removed` ro'yxatiga o'tadi
(karta tarixi uni nomi bilan ko'rsatishi uchun). Xatolar (**422**): `column_not_custom`
(standart ustun), `column_has_cards` (ichida karta bor, avval ko'chiring), `no_such_column`.

### Qaytarish: `POST /api/v2/office/boards/{board}/columns/{code}/restore`

Yakuniy ustunlardan oldin turadi. **422** `column_name_taken`, `too_many_columns`.

### Sabablar ro'yxatlari (2026-11-23)

Kodda qat'iy yozilgan sabablar endi bazada, superuser boshqaradi. Karta sababning `code`ini
saqlaydi: nomi o'zgarsa yoki arxivlansa ham eski kartalar va hisobotlar to'g'ri o'qiladi.

| Kanban | Ro'yxat (`purpose`) | Qachon so'raladi | Boshida |
|---|---|---|---|
| Sotuv | `close` | «Yopish» | 5 ta (eski kodlar) |
| Uzaytirish | `decline` | «Rad etdi» | 7 ta (eski kodlar) |
| Sotuv, Uzaytirish | `no_contact` | «Bog'lanib bo'lmadi» — faqat ro'yxatda sabab bo'lsa, shunda majburiy | bo'sh |
| Uchala kanban | `move` | «Ko'chirish» — ro'yxatda sabab bo'lsa tanlash majburiy, bo'sh bo'lsa matn majburiy | bo'sh |

Support «Bog'lanib bo'lmadi» o'z ro'yxatida qoladi (`contact-reasons`); uni ham endi faqat
superuser o'zgartiradi (Egasi o'qiydi, `may_edit: false`).

- `GET /boards/{board}/reasons?purpose=` → `[{value, label, note_required}]`, faqat faollari.
  `purpose` bo'sh bo'lsa asosiy ro'yxat (`sales` → `close`, `renewal` → `decline`,
  `support` → `move`). Eski `GET /boards/sales/reasons` va `/boards/renewal/reasons` shu yo'l.
- `GET /boards/{board}/reason-lists` → sozlamalar uchun: `{board, may_edit, lists: [{purpose, label, hint, rows}]}`,
  `rows` arxivdagilar bilan: `{id, code, name, position, note_required, is_archived, is_default}`.
- `POST /boards/{board}/reason-lists/{purpose}` `{name, note_required}` → **201** qator.
- `PUT /boards/{board}/reason-lists/{purpose}/{id}` `{name, position, note_required}`.
- `POST .../{id}/archive`, `POST .../{id}/restore`.

Yozish faqat superuser (Egasi **403**). Xatolar: **422** `reason_name_required`,
`reason_name_taken`, `too_many_reasons` (50); **404** `no_such_reason_list`, `no_such_reason`.

Kartada: `actions[].reason` — tugma sabab so'rasa ro'yxat nomi (`close`, `decline`,
`no_contact`; Support uchun `unreachable`), aks holda bo'sh. Tanlangan `code` `reason` da yuboriladi;
sababning `note_required` rost bo'lsa `note` majburiy (**422** `note_required`).
`POST /cards/{id}/move`: `reason_code` (ro'yxatdan) va `reason` (matn); `reason` endi bo'sh
bo'lishi mumkin, agar `reason_code` berilgan bo'lsa.

### Ustun tugmalari (2026-11-23)

Har ustun kartasida qaysi tugmalar chiqishi endi bazada (`board_buttons`), superuser sozlaydi.
Boshida hammasi kod bergandek (migratsiya 0079). Karta `actions[]` shu jadvaldan o'qiladi.

Tugma ikki xil:

- **Kod tugmasi** (`contacted`, `no_contact`, `callback`, `will_pay`, `needs_support`, `release`,
  `close`; Support: `start`, `wait`, `unreachable`, `to_developer`, `resolve`, `release`;
  Uzaytirish: `contacted`, `no_contact`, `callback`, `will_pay`, `decline`). Nima qilishi kodda
  (yopish sababi, chegirma soati, mijozdan tasdiq, dasturchiga xato). Superuser: qaysi ustunda
  chiqishini, nomini (`label`), va `movable` bo'lganlari uchun qaysi ustunga o'tkazishini belgilaydi.
  `movable`: Sotuv `no_contact`, `callback`, `will_pay`; Support `wait`; Uzaytirish `contacted`,
  `no_contact`, `callback`, `will_pay`. Qolganlari o'z qoidasi bo'yicha yuradi (`rule_note`).
- **O'z tugmasi** (`action: "go"`, kodi `b_…`): faqat kartani tanlangan ustunga o'tkazadi.
  Nomi, ustuni, vaqt so'rashi (`due`: bo'sh, `optional`, `required`) va izoh majburiyligi sozlanadi.
  Tarixda `button` («Tugma bosildi»), matni: tugma nomi va izoh.

Cheklovlar:

- Navbat (Sotuv «Ishlanmagan», Support «Yangi»), yakuniy ustunlar va Support'ning hal qilingan
  ustunlari sozlanmaydi (`configurable: false`, tugmalari `fixed` da): **422** `button_column_fixed`.
- Tugma kartani faqat ko'rinadigan, qo'lda ishlanadigan (`kind: manual`), yakuniy bo'lmagan boshqa
  ustunga o'tkazadi (`targets`): **422** `button_target_invalid`.
- Chegirma ustunlarida (`marks_only`) tugma belgi qo'yadi, karta joyida qoladi: u yerda ustun
  tanlab bo'lmaydi va o'z tugmasi qo'shilmaydi: **422** `button_target_fixed`. O'z qoidasi bor tugmaga
  ustun berilsa ham shu xato.
- Bir ustunda ko'pi bilan 10 ta tugma (`too_many_buttons`); kod tugmasi ustunda bir marta (`button_exists`).
- Tugma o'tkazadigan ustunni doskadan olib bo'lmaydi: **422** `column_has_buttons`.

Yo'llar (yozish faqat superuser, Egasi **403**; javob har doim butun `ButtonsOut`):

- `GET /boards/{board}/buttons` → `{board, may_edit, max_per_column, columns, catalog, targets}`.
- `POST /boards/{board}/buttons` `{column, action, label, to_column, due, note_required}` → **201**.
- `PUT /boards/{board}/buttons/{id}` `{label, to_column, due, note_required, position}`.
- `DELETE /boards/{board}/buttons/{id}`.
- `POST /boards/{board}/buttons/reset` `{column}` — «Standartga qaytarish»: ustun tugmalari kod
  bergandek; superuser qo'shgan ustunda bo'sh qoladi.

Front uchun: `actions[].value` endi `b_…` ham bo'lishi mumkin — `POST /cards/{id}/actions` ga
`action` sifatida shu yuboriladi. `actions[].is_default_label: false` bo'lsa `label` yozilganidek
ko'rsatiladi (tarjima qilinmaydi). Ustunda yo'q tugma kodi: **409** `action_not_here` (avval noma'lum
kod uchun 422 edi).

### Avtomatik qoidalar (2026-11-23)

Tizim o'zi qiladigan har bir ko'chirish endi alohida qoida, bazada o'z qatori bilan (`board_rules`,
migratsiya 0080: 28 ta, hammasi kodda bo'lgan qiymatlar bilan). Superuser qoidaning ochiq qismlarini
o'zgartiradi; qolgani kodda qoladi.

`GET /boards/{board}/rules` → `{board, may_edit, max_custom, rules, kinds, units, from_choices, to_choices}`.
Har qoida: `{id, code, kind, name, sentence, is_enabled, from_columns, to_column, default_to, amount, unit,
amount_of, reason, editable, note, is_changed, is_custom}`. `sentence` — qoida oddiy gapda (o'zbekcha,
ustun nomlari bilan). `editable` — `enabled`, `from`, `to`, `amount`, `reason` dan qaysilari ochiq.

| Qoida | Ochiq qismlari |
|---|---|
| `sales.bill_opened`, `renewal.bill_opened` (mijoz hisob ochdi) | yoqish, qaysi ustunlardan, qaysi ustunga, sabab |
| `sales.bill_unpaid`, `renewal.bill_unpaid` (hisob to'lanmadi) | yoqish, qaysi ustunga, sabab |
| `support.due_back` (kutish vaqti keldi), `support.client_replied` (mijoz yozdi) | yoqish, qaysi ustunlardan, qaysi ustunga, sabab |
| `support.setup_late` (60 daqiqa), `support.meta_error` (30 daqiqa), `support.idle_no_launch` (3 kun), `support.idle_no_spend` (24 soat) | yoqish, muddat |
| `support.from_sales`, `support.survey` | yoqish |
| `renewal.opened` (muddat tugashidan 3 kun oldin) | muddat |
| `renewal.silent` (30 kun javobsiz → «Rad etdi») | yoqish, qaysi ustunlardan, muddat, sabab |
| `sales.sold`, `sales.start_bought`, `sales.offer_step`, `sales.offer_ended`, `support.unanswered`, `renewal.ended` | faqat sabab matni (pul va tasdiq qoidalari) |
| qolganlari (`sales.lead_opened`, `sales.given`, `support.reopened`, `renewal.renewed`, …) | hech narsa: sababni tizim har safar o'zi yozadi |

Sabab matni (`reason`) karta tarixiga yoziladi. Avval bo'sh yoziladigan 14 ta ko'chirish endi sabab bilan
yoziladi; hisob qoidalarida hisob raqami va summasi qo'shiladi («…: №TA-123, 490 000 UZS»).

**Superuserning o'z qoidalari** (`kind`): `stay` — karta ustunda shuncha tursa (kamida 1 soat);
`due` — kartaga qo'yilgan vaqt o'tsa (0 dan boshlab). Ikkalasi kartani tanlangan ustunga o'tkazadi,
tarixda `rule` («Avtomatik qoida»), matni: qoida nomi va sababi. Har daqiqalik tekshiruvda, tizim
qoidalaridan keyin ishlaydi. Bir kanbanda ko'pi bilan 20 ta.

Cheklovlar (**422** `rule_invalid`): qoida faqat ko'rinadigan ochiq ustunlardan o'qiydi (navbat,
chegirma va yakuniy ustunlardan emas) va faqat qo'lda ishlanadigan, yakuniy bo'lmagan ustunga
o'tkazadi. Tizim qoidasining yopiq qismi yuborilsa: **422** `rule_field_fixed`. Qoida ishlatadigan
ustunni doskadan olib bo'lmaydi: **422** `column_has_rules`.

Yo'llar (yozish faqat superuser, Egasi **403**; javob har doim butun `RulesOut`):

- `POST /boards/{board}/rules` `{kind, name, from_columns, to_column, amount, unit, reason}` → **201**.
- `PATCH /boards/{board}/rules/{id}` — tizim qoidasi uchun faqat o'zgargan maydonlar
  (`is_enabled`, `from_columns`, `to_column`, `amount`, `reason`); o'z qoidasi uchun butunligicha
  (`kind, name, from_columns, to_column, amount, unit, reason, is_enabled`).
- `POST /boards/{board}/rules/{id}/reset` — tizim qoidasini kod qiymatlariga qaytaradi.
- `DELETE /boards/{board}/rules/{id}` — faqat o'z qoidasi (tizimniki o'chirilmaydi, faqat `is_enabled: false`).

**Kartada «nega shu ustunda»**: `CardOut.why` (doskada ham, karta ichida ham):
`{kind, label, body, auto, at}` — kartani hozirgi ustuniga qo'ygan oxirgi tarix qatori.
`auto: true` — qoida ko'chirgan (odam emas). `null` — karta shu ustunda ochilgan.

### Qoidalar: shartlar, amallar, sinov; ustun belgisi; tarix; ustunlar hisoboti (2026-11-24)

Migratsiya `0081`. Hammasini faqat superuser o'zgartiradi (Owner 403, boshqalar 404).

**O'z qoidangiz (`POST` / `PATCH /boards/{board}/rules`)** endi ko'chirishdan boshqa ish ham qiladi. Yangi maydonlar (hammasi ixtiyoriy):

| Maydon | Ma'nosi |
|---|---|
| `kind` | `stay`, `due`, yangi `wrote`: karta ustunga kelganidan beri mijoz Yordam chatiga yozgan |
| `to_column` | bo'sh bo'lishi mumkin: karta joyida qoladi, qoida boshqa amal qiladi |
| `attempts_min` | kartada kamida shuncha «bog'lanib bo'lmadi» (faqat Sotuv va Uzaytirish; `counts_attempts`) |
| `plans` | mijozning tarifi shulardan biri (`plans` ro'yxatidan; `none` — tarifsiz) |
| `bill` | `open` — ochiq to'lov hisobi bor; `expired` — hisob to'lanmay muddati o'tgan |
| `due_amount` + `due_unit` | kartaga vaqt qo'yadi (hozirdan shuncha keyin; `0` — hozir); `null` — tegmaydi |
| `notify_manager`, `notify_lead`, `notify_text` | xodimlar boti orqali Telegram: karta xodimiga, rahbarga (kanban rahbari va Owner) |
| `assign_to` | kartani shu xodimga beradi (`staff` ro'yxatidan) |

Kamida bitta amal bo'lishi shart (`to_column`, vaqt, xabar yoki xodim), aks holda 422 `rule_invalid`. Karta joyida qoladigan qoida bitta turish (yoki bitta muddat) uchun bir marta ishlaydi. `GET /boards/{board}/rules` javobida `plans`, `bills`, `staff`, `counts_attempts` tanlovlari va har qoidada shu maydonlar keladi.

**Sinab ko'rish:** `POST /boards/{board}/rules/preview` — tanasi qoidaning o'zi (+ `rule_id`, tahrirlanayotgan bo'lsa). Javob `{count, cards[]}`: hozir nechta kartaga tegadi va birinchi 10 tasi. Hech narsa o'zgarmaydi.

**«Gaplashilgan» ustun (Sotuv):** `PUT /boards/sales/columns/{code}/talked` `{talked}`. Shunday ustunda turgan kartaning mijozi Start olsa, chegirma darhol boshlanadi. `columns[].is_talked`, `columns[].may_talk` (qaysi ustunga qo'yish mumkin). «Bog'lanildi» va chegirma ustunlarida doim bor, o'zgarmaydi (422).

**Sozlamalar tarixi:** `GET /boards/{board}/settings/history?area=&before=` — ustun, sabab, tugma, qoida qo'shilgani, o'zgargani, olib tashlangani: `rows[] {area, area_label, action, action_label, name, body, actor, at}`, `next_before`, `areas`. Superuser va Owner o'qiydi.

**Ustunlar hisoboti:** `GET /boards/{board}/columns/report?date_from&date_to` — o'qiyotgan odam ko'radigan har ustun (o'zingiz qo'shganlar ham): `now` (hozir turgan kartalar), `entered` (davrda kelgan), `left` va `stay_hours` (davrda chiqqan kartalar o'rtacha qancha turgani). Menejer o'z kartalarini, rahbar, Owner va superuser hammasini ko'radi (`everybody`).

**Sotuv menejeri va mijoz kartasi:** `me.can.sales_client_card` — Sotuv kartasidan mijozning to'liq kartasi ochiladi. `GET /api/v1/office/customers/{id}`, `…/ads…`, `…/activity` Sotuv menejeriga faqat o'z kartasidagi mijoz uchun (rahbarga jamoaniki) ochiq, javobda `reader: "sales"`; ro'yxat (`GET /customers`), qolgan tablar va barcha o'zgartirishlar yopiq (404).

### Xodimlar

Ofis frontida xodimlar va rollar endi faqat **Jamoa** bo'limida (`/api/v1/office/team`, Egasi va superuser):
`GET /team` (har birida `phone`), `GET /team/search?q=` (hali xodim bo'lmaganlar; kamida 3 belgi),
`POST /team {"email", "roles": [...]}` (rollari bilan birga qo'shish), `POST /team/{id}/roles`, `POST /team/{id}/remove`.
Qoidalar ikkala yo'lda bir xil. Quyidagi v2 yo'llar ishlaydi, lekin front ularni ishlatmaydi.

| So'rov | Vazifasi |
|---|---|
| `GET /api/v2/office/staff` | Xodimlar va ularning rollari |
| `GET /api/v2/office/staff/search?q=` | Hali xodim bo'lmagan ro'yxatdan o'tgan userlar (email, telefon, ism; kamida 3 harf) |
| `POST /api/v2/office/staff` | `{"user_id": "…", "roles": ["Sales"]}`: xodim qilish |
| `PATCH /api/v2/office/staff/{id}` | `{"roles": ["SalesLead", "Support"]}`: rollarning to'liq to'plami |
| `DELETE /api/v2/office/staff/{id}` | Xodimlikdan olish (yana mijoz bo'ladi) |

Rollar: `Sales`, `SalesLead`, `Renewal`, `Support`, `Finance`, `Engineer`, `Owner`.
`Owner` rolini faqat superuser beradi va oladi (**403** `owner_role_superuser_only`).
O'zining rolini o'zgartirib bo'lmaydi; superuserning rollari o'zgarmaydi.

### Support: zayavka turlari

`GET /api/v2/office/boards/support/kinds`, `PUT /api/v2/office/boards/support/kinds/{member_id}` `{"kinds": [...]}`.
Har bir Support xodimi avval qaysi turdagi zayavkalarni olishi; default — hamma tur. Board javobidagi
`take.own` — navbatning o'quvchi turidagi qismi. To'liq qoidalar: `docs/SUPPORT_KANBAN_YANGI_QOIDALAR.md` §3a.

### So'rovnoma: «yordam kerak» variantlari

- `GET /api/v2/office/surveys/questions/{question_id}/help-options`
- `PUT /api/v2/office/surveys/questions/{question_id}/help-options` body: `{"options": [0]}`

`options`: shu savolning «Mutaxassis yordami kerak» variantlari tartib raqamlari (0 dan).
Ro'yxat to'liq yuboriladi: yuborilmagan variantdan belgi olinadi. Faqat variantli
(`choice`) savollar uchun.

## 6. Xatolar

Xato javobida `code` va `message` (foydalanuvchiga ko'rsatiladigan matn) bor:

| Status | `code` | Qachon |
|---|---|---|
| 404 | — | Ruxsat yo'q yoki karta topilmadi |
| 409 | `nothing_to_take` | Olinadigan lid yo'q |
| 409 | `action_not_here` | Bu ustunda bu tugma yo'q (sahifani yangilang) |
| 409 | `card_closed` | Karta yopilgan |
| 409 | `ticket_held` | Bu mijoz bilan boshqa Support xodimi ishlayapti |
| 422 | `reason_required`, `note_required` | Yopish sababi yoki izoh yo'q |
| 422 | `not_on_board` | Bu xodim shu bo'limda ishlamaydi |
| 422 | `due_required`, `due_past`, `due_invalid` | Muddat berilmagan, o'tgan vaqtga qo'yilgan yoki noto'g'ri (zonasiz, 1 yildan uzoq) |
| 409 | `card_exists`, `client_paid` | Qo'lda lid: mijozning ochiq kartasi bor yoki u tarif sotib olgan |
| 422 | `client_not_found` | Qo'lda karta: bunday mijoz yo'q (xodim, CRM logini, bloklangan) |
| 422 | `no_such_column`, `move_reason_required` | Ko'chirishda ustun yoki sabab xato |
| 422 | `columns_mismatch`, `column_name_required` | Ustunlarni saqlashda xato |
| 403 | `owner_role_superuser_only` | Egasi rolini faqat superuser beradi |

## 7. Uzaytirish kanbani (`renewal`)

Uchinchi doska: Standart va Pro tarifidagi **pullik** mijozlarning tugayotgan obunalari. Start, Enterprise, sinov va
ofisdan to'lovsiz berilgan obuna tushmaydi. «Pullik»: joriy tarifi Standart/Pro va mijozda Standart/Pro uchun
to'langan hisob bor.

Umumiy yo'llar (`boards/{board}`, `cards/{id}`, `actions`, `due`, `notes`, `assign`, `move`, `columns`, `staff`)
`board = renewal` bilan o'zgarishsiz ishlaydi. Qo'lda karta ochilmaydi (`POST boards/renewal/cards` → 404).

### Kim ko'radi

| Rol | Ko'rishi | Qo'shimcha |
|---|---|---|
| `Renewal` («Uzaytirish menejeri») | faqat o'ziga biriktirilgan kartalar | tugmalar, izoh, muddat |
| `SalesLead` | hamma kartalar, hisobot | kartani menejerga berish |
| `Owner`, superuser | hammasi | mas'ul menejer, ustunlar, qo'lda ko'chirish |

`me.can.client_card` — mijozning ofis kartasi ochiladimi (Support, Finance, Owner, superuser); `false` bo'lsa havola
ko'rsatilmaydi. `me.can.renewal_manager` — mas'ul menejerni tanlay oladimi.

### Ustunlar va tugmalar

| Kod | Nomi | Qanday tushadi | Tugmalar |
|---|---|---|---|
| `ending` | Tugayapti | avto: tugashiga 3 kun qolganda | `contacted`, `no_contact`, `callback`, `decline` |
| `ended` | Tugagan | avto: muddat o'tdi, karta hali `ending`da | shu to'rttasi |
| `no_contact` | Bog'lanilmadi | tugma; `attempts` +1 | shu to'rttasi |
| `contacted` | Bog'lanildi | tugma | `callback`, `will_pay`, `decline` |
| `callback` | Qayta aloqa | tugma, `due_at` majburiy | `contacted`, `no_contact`, `callback`, `will_pay`, `decline` |
| `awaiting` | To'lov kutilmoqda | tugma (`will_pay`) yoki mijoz Standart/Pro hisobini ochganda | `callback`, `decline` |
| `renewed` | Uzaytirdi (yakuniy) | avto: Standart/Pro to'lovi tushganda, istalgan ustundan | — |
| `declined` | Rad etdi (yakuniy) | `decline` (sabab majburiy) yoki avto | — |

`decline`: `reason` — `GET /api/v2/office/boards/renewal/reasons` dagi kod (`expensive`, `no_result`,
`meta_problem`, `business_stopped`, `switched`, `no_answer`, `other`); `other` uchun `note` majburiy.

### O'zi nima bo'ladi (har daqiqa)

- Tugashiga ≤ 3 kun qolgan yoki oxirgi 30 kunda tugagan har bir pullik obunaga karta ochiladi, sozlamadagi mas'ul
  menejerga biriktiriladi. Birinchi ishga tushishda tugaganlar ham shu yo'l bilan yuklanadi.
- Muddat o'tsa, `ending`dagi karta `ended`ga o'tadi.
- Hisob ochilsa — `awaiting`; hisob to'lanmay yopilsa — `callback`, muddati «hozir».
- To'lov tushsa — `renewed` (karta `invoice_id`ni saqlaydi), `declined`dan ham.
- Tugaganiga 30 kun bo'lgan `ended` va `no_contact`dagi karta `declined`ga o'tadi, sabab `no_answer`.
- Ofis kun qo'shsa yoki olsa (to'lovsiz), ochiq karta yangi sanani oladi, joyida qoladi.
- Uzaytirilgan obuna yana tugashga yaqinlashsa, yangi karta ochiladi; eskisi `renewed`da tarix bo'lib qoladi.

### Kartadagi `renewal`

`CardOut.renewal` (boshqa doskalarda `null`): `plan_code`, `plan_name`, `term_ends_at`, `ended`, `days` (qolgan kun;
manfiy — o'tgan kun), `pages`, `ads_running`, `leads_month`, `spend_month[]`, `payments`, `last_login`,
`decline_reason`, `decline_label`, `paid` (uzaytirgan hisob summasi).

### Tartib, qidiruv, filterlar — `GET /api/v2/office/boards/renewal`

Tartib: eng kam kuni qolgani tepada, keyin eng yaqinda tugagani. `callback`da `due_at` bo'yicha (kechikkan tepada).
`renewed` va `declined`da — oxirgi tushgani tepada.

| Parametr | Qiymat |
|---|---|
| `q` | ism, email, telefon yoki sahifa nomi |
| `plan` | `standart`, `pro` |
| `term_from`, `term_to` | obuna tugash sanasi oralig'i (ofis kuni, `YYYY-MM-DD`) |
| `attempts` | `0`, `1-2`, `3+` |
| `reason` | rad sababi kodi |
| `mine`, `manager`, `due` | boshqa doskalardagidek |

### Hisobot: `GET /api/v2/office/boards/renewal/report?date_from&date_to`

Davr — obuna **tugash sanasi** bo'yicha (bo'sh bo'lsa oxirgi 30 kun, ko'pi bilan 366 kun). `plans[]` (Standart, Pro)
va `total`: `due` (nechta tugadi), `renewed`, `declined`, `open`, `rate` (%), `paid[]` (to'langan hisoblar summasi),
`reasons[]` (rad sabablari). Menejer faqat o'z kartalari bo'yicha ko'radi.

### Mas'ul menejer: `GET` / `PUT /api/v2/office/boards/renewal/manager`

Superuser va Egasi. `PUT {staff_id}` — `Renewal` roli bor xodim; ochiq kartalar darhol yangisiga o'tadi (`moved`),
yakuniylari eskisida qoladi. `staff_id: null` — mas'ul yo'q: kartalar `Renewal` roli bor xodimlar orasida
teng taqsimlanadi (kimda ochiq karta kam bo'lsa, o'shanga). Rolning o'zi yetarli: hech kim tanlanmagan bo'lsa ham,
rol berilgandan keyingi daqiqada egasiz ochiq kartalar ham shu xodimlarga beriladi.

## 8. Start: faqat birinchi xarid

Start (kodi `start` yoki «bir martalik» tarif) faqat mijozning eng birinchi xaridi sifatida sotiladi. Mijoz biror
tarif hisobini to'lagan yoki ofis/promo unga to'liq tarif bergan bo'lsa, Start tariflar ro'yxatida chiqmaydi va
hisob ochilmaydi (`plan_already_bought`). Start hisobiga promo kod qo'llanmaydi (`promo_not_applicable`); sotuv
chegirmasi ham unga tegmaydi. Hamyon balansi avvalgidek ishlatiladi.

## 9. Support: sabablarning holati

Mijozda bitta zayavka umrbod turadi, shuning uchun har sababning o'z holati bor (`ticket_reasons[]`):

| Maydon | Ma'nosi |
|---|---|
| `state` | `open` yoki `solved` |
| `solved_at`, `solved_by`, `solved_note` | qachon, kim va qanday hal qilgani («Hal qilindi» izohi) |
| `denied_at` | mijoz «Yo'q, hal bo'lmadi» degan vaqt: sabab qayta ochiq |
| `detail` | nima bo'lgani, sodda so'z bilan |
| `raw` | Meta'ning o'z matni (iqtibos uchun) |
| `target` | nima haqida: `{kind: launch|action, id, name}`; `launch`ning `id`si — mijoz kampaniyasi sahifasi |

- «Hal qilindi» (`resolve`) **hamma ochiq sabablarni birga** yopadi.
- Mijoz «Yo'q» desa yoki xodim «Qayta ochish»ni bossa, o'sha oxirgi yopilganlar qayta ochiladi.
- Yangi sabab kelsa, eskilari hal bo'lgan holicha qoladi.
- Kartadagi `reasons` / `reason_chips` va `reason` filtri endi faqat **hozir ochiq** sabablarni o'qiydi (yakunlangan
  zayavkada — oxirgi yopilganlarini).

Karta: `client_denied` (mijoz «Yo'q» dedi), `client_replied` (kutish paytida mijoz yozdi), `confirm_until`
(«Tasdiq kutilmoqda»da: shu vaqtgacha javob bo'lmasa zayavka o'zi yopiladi).

Karta tafsiloti: `resolution` — `{note, by, at, client: waiting|yes|silent, count}`; `client.troubles[]` — akkauntning
hozirgi muammolari (ofisdagi «Muammolar» ro'yxati bilan bir xil); `client.plan.expired`.

Migratsiya 0055 mavjud zayavkalarga shu holatni ularning o'z tarixidan yozadi.

## 10. Sotuv: hisobot, lid issiqligi, manba, eslatmalar (2026-11-19)

### Hisobot: `GET /api/v2/office/boards/sales/report?date_from&date_to`
Ofis kunlari (Toshkent), bo'sh bo'lsa oxirgi 30 kun, ko'pi bilan 366 kun. Javob `SalesReportOut`:
`total`, `days[]` (davrning har kuni, eskisi birinchi), `staff[]` (har bir Sotuv xodimi, ko'p sotgan birinchi;
`staff: null` — «Menejersiz»: hech kim olmay turib o'zi to'laganlar), `reasons[]`, `queue` (faqat rahbar),
`sources[]` va `campaigns[]` (faqat rahbar). Raqamlar kartalar tarixidan:
`leads` — ochilgan kartalar; `taken` — «Lid olish» yoki rahbar bergani; `contacted` / `no_contact` / `callbacks` —
bosilgan tugmalar; `sold` — birinchi to'liq tarif to'lovi (Start sotuv emas), `money` — o'sha hisob summasi;
`closed` — qo'lda yoki chegirma tugab yopilgan; `calls*` — ofis UTeL qo'ng'iroqlari; `first_touch_minutes` —
«Lid olish»dan birinchi qo'ng'iroq tugmasigacha mediana. `rate`: rahbar ko'rinishida jami va kunda `sold ÷ leads`,
xodim qatorida va menejerning o'z ko'rinishida `sold ÷ taken`. Menejer faqat o'zini ko'radi (`scope: "own"`).

### Kartada
`heat` (Sotuv, ochiq karta): `level` hot/warm/cold, `points`, `bill`, `facebook`, `page`, `business`, `returned`.
`client.signup_via` (`email`/`google`/`telegram`), `signup_via_label`, `utm` (`source`, `medium`, `campaign`, …).

### «Lid olish»
Navbat: §11 dagi tur tartibi, keyin eng issiq (`heat.points`), tenglar ichida eng yangi. «Yangi lead»da olingan,
hali qo'ng'iroq qilinmagan 5 ta lid bo'lsa — 409 `lead_take_limit`. `GET /boards/sales` javobida
`take: {queue, working, limit}`. `attempts` filtri (`0`, `1-2`, `3+`) Sotuvda ham ishlaydi.

### Ro'yxatdan o'tish
`POST /api/v1/auth/signup` va `POST /api/v1/auth/social/{provider}/start` `utm` qabul qiladi
(`{"source": "...", "campaign": "..."}`, `utm_` prefiksisiz).

### Telegram (xodimlar boti), har daqiqa
Kartaning vaqti keldi (oxirgi 60 daqiqa ichida) — kartaning menejeriga; mijoz tarif hisobini ochdi — menejerga;
navbatda yangi lidlar — Sotuv jamoasiga, 30 daqiqada bir martadan ko'p emas, 09:00–21:00. Har biri kartaga
tarix qatori bo'lib yoziladi (`due_reminded`, `bill_told`).

### Telefoniya
`clients[]` (jonli qo'ng'iroq, jurnal): `renewal_card_id`, `standing` (`paid`, `plan`, `days_left`, `state`,
`label`). UTeL'ning `contact_name`i: «Ism · «Standart» · 12 kun qoldi». `PUT /api/v2/office/telephony/me/accepting`
`{"accepts_calls": false}` — «Qo'ng'iroq qabul qilmayman»: yo'naltirish bu xodimni o'tkazib yuboradi, brauzer
telefoni kiruvchini rad etadi (486). `GET /telephony/me` va `/colleagues` `accepts_calls` beradi.

## 11. Sotuv: lid turlari, raqam bilan olish (2026-11-20)

**Kartaning yo'li.** Start olgan mijozning chegirmasi (24 soat 20%, keyin 96-soatgacha 10%) Start to'lovidan
hisoblanadi, narx kartaning ustuniga qaramaydi. Karta esa «Ishlanmagan» da turadi va 20%/10% ustuniga faqat
menejer «Gaplashildi» ni bosganda o'tadi — soat qayerda tursa, o'sha ustunga. Chegirma tugagach bosilsa —
«Bog'lanildi», yangi 20% berilmaydi. Hech kim ishlamagan karta chegirma tugasa ham «Ishlanmagan» da qoladi.
Chegirma ustunidagi karta chegirma tugaganda **yopilmaydi**: «Bog'lanildi» ga o'tadi, menejeri qoladi
(`offer_ended` qatori). «Yopildi» ga faqat «Yopish» tugmasi bilan. Start to'langanda karta «Bog'lanildi» da
(yoki eski suhbat chegirmasi ustunida) bo'lsa darhol chegirma ustuniga o'tadi; «Yangi lead», «Bog'lanilmadi»,
«Qayta aloqa» da joyida qoladi (`start_bought` qatori). Lead kartani qaytarsa (`assign` `staff_id: null`) —
doim «Ishlanmagan».

**Turlar** (`kind`, kartada va `take.kinds` da): `start_live` — Start olgan, chegirmasi bor (to'lovdan 96 soat);
`start_ended` — Start olgan, chegirmasi tugagan, Start tarifi hali ishlayapti; `start_expired` — Start olgan, tarifi
tugagan (Start obunasining `expires_at` i o'tgan), to'liq tarif olmagan; `new` — hech narsa to'lamagan. Tur shu
daqiqada hisoblanadi (2026-11-20 dan 4 ta).

**«Lid olish» tartibi**: menejerning o'z turlari, ular qolmasa istalgan tur. Ichida: `start_live` (20% lar 10% lardan
oldin, tezroq tugaydigani birinchi) → `start_ended` → `start_expired` → `new`; keyin `heat`, keyin eng yangi.
`GET /boards/sales` → `take: {queue, own, working, limit, kinds: [{value, label, count, own}]}`. «Hamma tur» dagi
menejerga yangi tur o'zi qo'shiladi; ayrim turlari belgilangan menejerga Owner qo'lda qo'shadi.

**Sozlamalar** (superuser va Egasi): `GET /api/v2/office/boards/sales/kinds` → `{kinds: [{value, label}],
members: [{id, name, email, kinds, all}]}`; `PUT /api/v2/office/boards/sales/kinds/{member_id}` `{"kinds": [...]}`
(kamida bitta; hammasi belgilansa `all: true` bo'lib saqlanadi). Belgilanmagan menejer hamma turni oladi.

**Raqam bilan olish**: `POST /api/v2/office/sales/take-by-phone` `{"phone": "+998 90 123 45 67"}` (istalgan yozuv,
kamida oxirgi 9 raqam). Tur, navbat va 5 lid chegarasi ta'sir qilmaydi; «Lid olish» huquqi borlarga.
- Xodimsiz lid («Ishlanmagan», «Yopildi» yoki kartasi yo'q) → shu menejerga, «Yangi lead», `taken_as: phone`,
  tarixda «Raqam bilan olindi».
- Boshqa menejerda → **409** `lead_with_other` «Bu lid boshqa menejerda.»; o'zida → **409** `lead_is_yours`
  «Bu lid sizda.»
- To'liq tarifni hech kim olmasdan to'lagan mijoz: to'lovdan keyin **12 soat** ichida olinsa karta «Sotildi» da
  qoladi, sotuv shu menejerniki bo'ladi.
- Raqam topilmadi, xodim raqami, yoki to'liq tarif 12 soatdan oldin to'langan → **404** `no_such_lead`
  «Bunday lid yo'q.»

**Kartada**: `kind` (hozirgi tur) va `taken_as` (`{value, label}`: olinganda qaysi tur edi, yoki `phone`; hali
hech kim olmagan yoki 2026-11-20 dan oldin olingan bo'lsa `null`).

**Hisobot**: `kinds` va har xodim qatorida `kinds`: `[{value, label, taken, sold, rate, money}]` — har tur,
«Raqam bilan olingan» doim; `value: ""` («Oldin olingan») faqat bor bo'lsa. «Yopildi» endi faqat yopilgan
kartani sanaydi (chegirma tugashi yopmaydi).

**Migratsiya 0070**: `board_sales_kinds` jadvali, `board_cards.taken_as`; xodimsiz 20%/10% kartalar →
«Ishlanmagan»; menejeri bor, lekin gaplashilmagan 20%/10% kartalar → «Yangi lead» yoki «Bog'lanilmadi»;
«Chegirma tugadi» bilan o'zi yopilgan Start kartalari → menejer gaplashgan bo'lsa «Bog'lanildi» (menejeri bilan),
aks holda «Ishlanmagan». Har ko'chgan kartaga `moved` qatori yoziladi.
