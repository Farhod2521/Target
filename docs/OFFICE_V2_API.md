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

### `POST /api/v2/office/sales/take`

«Lid olish». Body yo'q. Eng **yangi** «Ishlanmagan» lid shu menejerga beriladi va
«Yangi lead» ga o'tadi. Javob: karta (yuqoridagi shakl).
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
- Mijoz tarif uchun to'ladi → istalgan ustundan «Sotildi».
- Menejeri bor mijoz tarif hisobini ochdi → «To'lov kutilmoqda» (har hisob uchun bir marta;
  20% va 10% ustunidagi karta ko'chmaydi, unda faqat `has_bill` yonadi).
- Shu hisob to'lanmay muddati o'tdi → «Qayta aloqa», muddati shu zahoti o'tgan. «To'laydi»
  tugmasi bilan qo'yilgan karta o'zi qaytmaydi.

**Support**: bitta mijozga **bitta** karta. Yangi sabab shu kartaga qo'shiladi.
«Hal qilindi» dagi kartaga yangi sabab kelsa, u qayta ochiladi va o'sha xodimga qaytadi.

| `reasons` kodi | Qachon |
|---|---|
| `setup` | To'lovdan 1 soat o'tdi, sozlash tugamagan |
| `from_sales` | Sotuvda «Support kerak» belgisi bor mijoz to'ladi (darhol) |
| `meta_error` | Reklamani ishga tushirish yoki mijozning amali Meta xatosi bilan tugadi |
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

### Xodimlar

| So'rov | Vazifasi |
|---|---|
| `GET /api/v2/office/staff` | Xodimlar va ularning rollari |
| `GET /api/v2/office/staff/search?q=` | Hali xodim bo'lmagan ro'yxatdan o'tgan userlar (email, telefon, ism; kamida 3 harf) |
| `POST /api/v2/office/staff` | `{"user_id": "…", "roles": ["Sales"]}`: xodim qilish |
| `PATCH /api/v2/office/staff/{id}` | `{"roles": ["SalesLead", "Support"]}`: rollarning to'liq to'plami |
| `DELETE /api/v2/office/staff/{id}` | Xodimlikdan olish (yana mijoz bo'ladi) |

Rollar: `Sales`, `SalesLead`, `Support`, `Finance`, `Engineer`, `Owner`.
`Owner` rolini faqat superuser beradi va oladi (**403** `owner_role_superuser_only`).
O'zining rolini o'zgartirib bo'lmaydi; superuserning rollari o'zgarmaydi.

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
yakuniylari eskisida qoladi. `staff_id: null` — yangi kartalar egasiz tushadi.

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
