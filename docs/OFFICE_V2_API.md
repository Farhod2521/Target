# Ofis v2: Sotuv va Support kanbanlari

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
| Superuser va `Owner` | Ikkala kanban | Hammasi: ko'chirish, ustunlar, xodimlar, so'rovnoma belgilari; superuser «Lid olish» ham |

### `GET /api/v2/office/me`

Sahifa ochilganda birinchi shu chaqiriladi.

```json
{
  "user": {"id": "…", "name": "Ali", "email": "ali@…"},
  "roles": [{"value": "Sales", "label": "Sotuv menejeri"}],
  "is_superuser": false,
  "boards": [{"code": "sales", "label": "Sotuv", "lead": false}],
  "default_board": "sales",
  "can": {"take": true, "assign": false, "move": false, "columns": false, "staff": false}
}
```

- `boards` bo'sh bo'lsa, bu xodimga kanban yo'q: menyuda ko'rsatmang.
- `default_board`: birinchi ochiladigan kanban.
- `can.take`: «Lid olish» tugmasi. `can.assign`: kartani boshqa xodimga berish.
  `can.move`, `can.columns`, `can.staff`: superuser va Egasi uchun.

## 2. Kanban

### `GET /api/v2/office/boards/{board}`

`board`: `sales` yoki `support`. Parametrlar (hammasi ixtiyoriy):

| Parametr | Ma'nosi |
|---|---|
| `q` | Mijozning ismi, emaili yoki telefoni bo'yicha qidiruv |
| `column` | Faqat bitta ustun (keyingi sahifa uchun) |
| `offset`, `limit` | Shu ustunning sahifasi; `limit` 1–200, odatda 50 |

```json
{
  "board": "sales",
  "columns": [
    {
      "code": "new_lead", "name": "Yangi lead", "position": 2,
      "kind": "manual", "is_final": false, "total": 12,
      "cards": [
        {
          "id": "…", "board": "sales", "column": "new_lead",
          "client": {"id": "…", "name": "Vali", "email": "…", "phone": "+998…", "signed_up_at": "…"},
          "manager": {"id": "…", "name": "Ali", "email": "…"},
          "contact_mark": "", "needs_support": false, "reasons": [],
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
| `discount_20` | 20% chegirma | avto | Ega menejer, rahbar |
| `discount_10` | 10% chegirma | avto | Ega menejer, rahbar |
| `no_discount` | Chegirmasiz | avto | Ega menejer, rahbar |
| `sold` | Sotildi | avto, yakuniy | Ega menejer, rahbar |
| `closed` | Yopildi | tugma, yakuniy | Rahbar |

**Chegirma.** «Bog'lanildi» dagi «Chegirma berish» (`offer`) kartani «20% chegirma» ga
o'tkazadi va soat shu bosilgan paytdan boshlanadi: 24 soat 20%, 72-soatgacha 10%,
keyin «Chegirmasiz». Bu o'tishlarni tizim har daqiqa o'zi qiladi. Har mijozga bir marta
beriladi. Chegirma mijozning **birinchi** tarif to'loviga tushadi (qo'shimcha sahifa va
o'rinlarga emas). Tartib: asl narx → sotuv chegirmasi → promokod (qolgan summadan) →
hamyon. Shu chegirma bilan narxlangan
to'lov bosqich tugaganidan 15 daqiqa keyingacha to'lanadi. Karta yopilsa yoki qo'lda
chegirma ustunlaridan chiqarilsa, chegirma ham to'xtaydi.

Mijoz kabinetida: `GET /api/v1/billing` va `GET /api/v1/billing/paywall` javobida
`sales_offer: {percent, ends_at, pay_until}` (yoki `null`). Tarif kartalari
(`cards[].offer`) va `chosen` da: `price_minor` asl narx, `offer_minor` sotuv chegirmasi,
`promo_minor` promokod (faqat `chosen`), `discount_minor` = ikkalasi, `wallet_minor` hamyon,
`due_minor` to'lanadigan summa. `promo_quote.base_minor` = chegirmadan keyingi narx.
Start va bir martalik tariflarga sotuv chegirmasi berilmaydi: ularda `offer_minor` = 0.

`trial` ustuni bazada bor, lekin hozircha yashirin: kelmaydi. Bepul sinov qilinganda chiqadi.

**Support:** `new` (Yangi), `in_progress` (Ishlanmoqda), `resolved` (Hal qilindi, yakuniy).

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
  "offer": {"percent": 20, "started_at": "…", "ends_at": "…"},
  "close_reason": "expensive", "close_reason_label": "Qimmat", "close_note": "",
  "actions": [{"value": "contacted", "label": "Bog'lanildi"}],
  "history": [{"kind": "taken", "label": "Lid olindi", "from_column": "unworked", "to_column": "new_lead",
               "actor": {"id": "…", "name": "Ali", "email": "…"}, "body": "", "at": "…"}]
}
```

- **`actions`**: kartada ko'rsatiladigan tugmalar, tartibi bilan. Faqat shularni chizing.
- `history`: eng yangisi birinchi. `actor: null` bo'lsa, buni tizim qilgan.
- `ticket_reasons`: Support kartasi nega ochilgani (eng yangisi birinchi).
- `support_chat_id`: mijozning Yordam chati bo'lsa, shu chatni ochish uchun.
- `offer`: Sotuv kartasiga chegirma berilgan bo'lsa: hozirgi foiz va u qachon tugashi.
  Chegirma tugagan yoki karta yopilgan bo'lsa `percent: 0`, `ends_at: null`. Berilmagan bo'lsa `null`.

### `POST /api/v2/office/sales/take`

«Lid olish». Body yo'q. Eng eski «Ishlanmagan» lid shu menejerga beriladi va
«Yangi lead» ga o'tadi. Javob: karta (yuqoridagi shakl).
Lid qolmagan bo'lsa: **409** `nothing_to_take`. Sotuv rollarida va superuserda ishlaydi (`Owner` da yo'q).

### `POST /api/v2/office/cards/{id}/actions`

```json
{"action": "contacted", "note": "Ertaga to'laydi"}
```

| `action` | Qaysi ustunda | Nima bo'ladi |
|---|---|---|
| `contacted` | Yangi lead, Bog'lanilmadi | → Bog'lanildi |
| `no_contact` | Yangi lead | → Bog'lanilmadi |
| `offer` | Bog'lanildi | → 20% chegirma; ikkinchi marta **409** `offer_given` |
| `needs_support` | Bog'lanildi, 20%, 10%, Chegirmasiz | «Support kerak» belgisi; `"on": false` olib tashlaydi |
| `close` | Yangi lead, Bog'lanilmadi, Bog'lanildi, 20%, 10%, Chegirmasiz | → Yopildi; `reason` majburiy |
| `start` | Support: Yangi | → Ishlanmoqda; bosgan xodim mijozning doimiy mas'uli bo'ladi |
| `resolve` | Support: Ishlanmoqda | → Hal qilindi |

- `close` uchun `reason`: `GET /api/v2/office/boards/sales/reasons` dagi qiymat
  (`expensive`, `not_needed`, `no_answer`, `wrong_number`, `other`). `other` bo'lsa `note` majburiy.
- `note` ixtiyoriy (`close` + `other` dan tashqari), tarixga yoziladi.
- Javob: yangilangan karta.

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

**Support**: bitta mijozga **bitta** karta. Yangi sabab shu kartaga qo'shiladi.
«Hal qilindi» dagi kartaga yangi sabab kelsa, u qayta ochiladi va o'sha xodimga qaytadi.

| `reasons` kodi | Qachon |
|---|---|
| `setup` | To'lovdan 1 soat o'tdi, sozlash tugamagan |
| `from_sales` | Sotuvda «Support kerak» belgisi bor mijoz to'ladi (darhol) |
| `meta_error` | Reklamani ishga tushirish yoki mijozning amali Meta xatosi bilan tugadi |
| `survey` | So'rovnomada «yordam kerak» deb belgilangan variantni tanladi |
| `idle` | To'lovdan 3 kun o'tib birorta reklama yoqilmagan, yoki faol reklamada 24 soat sarf 0 (soatiga bir tekshiriladi) |

## 5. Sozlamalar (superuser va Egasi)

### Ustunlar: `PATCH /api/v2/office/boards/{board}/columns`

Hamma ko'rinadigan ustunlarni yangi tartibda va nomi bilan yuboring:

```json
{"columns": [{"code": "new", "name": "Kelgan"}, {"code": "in_progress", "name": "Jarayonda"}, {"code": "resolved", "name": "Tayyor"}]}
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
| 422 | `no_such_column`, `move_reason_required` | Ko'chirishda ustun yoki sabab xato |
| 422 | `columns_mismatch`, `column_name_required` | Ustunlarni saqlashda xato |
| 403 | `owner_role_superuser_only` | Egasi rolini faqat superuser beradi |
