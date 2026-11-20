# Mijoz CRM: qo'lda lid, ommaviy amallar, eslatma — frontend ishlari

Backend: `feat/crm-sales-metrics` shoxi. Migratsiya yo'q (bu qism uchun). Avval backend deploy qilinadi.
Bog'liq hujjatlar: [FRONTEND_SOTUV_KORSATKICHLARI.md](FRONTEND_SOTUV_KORSATKICHLARI.md),
[FRONTEND_CRM_VALYUTA.md](FRONTEND_CRM_VALYUTA.md).

Eski front yangi backend bilan buzilmaydi: hammasi yangi yo'l va yangi maydon.

## Nima o'zgardi (qisqa)

| # | O'zgarish |
|---|---|
| 1 | Doskaga **qo'lda mijoz qo'shish**: reklamadan kelmagan (qo'ng'iroq, do'konga kelgan, tanish orqali) |
| 2 | **Ommaviy amal**: bir nechta kartani bitta ustunga ko'chirish yoki bitta menejerga berish |
| 3 | Kartada `lead.manual` belgisi, tarixda yangi `added` yozuvi |
| 4 | Statistikada `sales.direct`: qo'lda qo'shilgan mijozlar sotuvi alohida |
| 5 | Egasining kunlik Telegram xabarida CRM eslatmasi (frontda ish yo'q) |

## 1. Qo'lda mijoz qo'shish

`POST /api/v1/crm/cards` — egasi ham, menejer ham (doskada ishlay oladigan har kim).

```json
{"name": "Vali", "phone": "90 111 22 33", "note": "Do'konga keldi"}
```

- `name` — majburiy. `phone` — majburiy, istalgan yozuvda (`90 111 22 33`, `+998901112233`):
  backend o'zi to'liq raqamga keltiradi. `note` — ixtiyoriy, birinchi izoh bo'lib yoziladi.
- Javob: `201`, oddiy karta (`CardOut`). Karta birinchi ustunga tushadi.
- Menejer qo'shsa — karta **darhol uniki** (`assignee`, `taken_at` to'la).
  Egasi qo'shsa — CRM taqsimot sozlamasi bo'yicha (navbat bilan yoki hech kimga).

| Holat | Javob |
|---|---|
| Ism bo'sh | 400, `code: "name_required"` |
| Telefon noto'g'ri yoki bo'sh | 400, `code: "phone_required"`, matn: «Telefon raqamini to'liq yozing, masalan +998 90 123 45 67.» |
| Bu telefon bilan ochiq (yoki rad etilgan) karta bor | 409, `code: "phone_on_board"`, `hints.card_id` — o'sha karta |
| CRM yoqilmagan | 400, `code: "not_running"` |

`phone_on_board` da xabar bilan birga **«Kartani ochish»** tugmasini bering (`hints.card_id`).
Reklamadan kelgan lidning telefoni bilan ham shu javob qaytadi — bir telefon doskada bitta mijoz.
Istisno: o'sha telefonning kartasi **sotilgan** bo'lsa, yangi karta ochiladi (`returned: 1`),
reklama lidi qayta kelgandagi kabi.

Tugma joyi: doska tepasida «+ Mijoz qo'shish». Dialog: ism, telefon, izoh.

### Kartada

`card.lead.manual: true` — «Qo'lda» belgisini chizing (reklama nomi o'rnida).
Bunday kartada `lead.ad_external_id` bo'sh, `GET /cards/{id}` → `source: null`, `answers: []`.
Tarixda birinchi yozuv `kind: "added"` («Qo'lda qo'shildi», `actor` — kim qo'shgan);
reklama lidida avvalgidek `arrived`.

Qolgan hamma amal (olish, ko'chirish, izoh, muddat, sotildi, rad) oddiy kartadagi kabi.

### Qayerda ko'rinmaydi

Qo'lda qo'shilgan mijoz **faqat CRM'da** yashaydi:

- «Lidlar» sahifasida yo'q (ro'yxatda ham, `GET /leads/{id}` da ham — 404);
- reklama raqamlariga (lid soni, lid narxi, Dashboard) kirmaydi;
- Meta'ga hech narsa yuborilmaydi (CAPI signali ham, auditoriya ro'yxati ham).

Doskadagi «reklama bo'yicha filtr»da ular hech bir reklamaga tegishli emas.

## 2. Ommaviy amal

`POST /api/v1/crm/cards/bulk`

```json
{"ids": ["<karta id>", "..."], "action": "move", "to": "<ustun id>"}
{"ids": ["<karta id>", "..."], "action": "assign", "to": "<menejer user id>"}
```

- `ids` — 1 tadan 100 tagacha. Ko'p bo'lsa 422.
- `action: "move"` — egasi ham, menejer ham. `action: "assign"` — **faqat egasi** (menejerga 404).
- `assign` da `to: ""` — kartalarni menejerdan qaytarib olish; `to` egasining o'z id si bo'lishi ham mumkin.

Javob (`200`):

```json
{
  "done":    [{...CardOut...}],
  "refused": [{"id": "<karta id>", "code": "not_allowed", "detail": "Bu amal sizga ruxsat etilmagan."}]
}
```

Har bir karta **alohida**, bitta kartani bosgandagi qoidalar bilan tekshiriladi. Rad etilgani
joyida qoladi va sababi bilan `refused` da keladi; qolganlari o'tadi. Shuning uchun javob har doim
`200`: natijani `done` va `refused` sonidan chiqaring («12 ta ko'chirildi, 2 tasi ko'chmadi»),
`refused` ni ro'yxat qilib ko'rsating.

Uchraydigan kodlar:

| `code` | Qachon |
|---|---|
| `not_allowed` | Menejer o'ziniki bo'lmagan kartani ko'chirmoqchi |
| `use_the_dialog` | «Sotildi» yoki «Rad etildi» ustuniga: summa/sabab so'raladi, ommaviy yo'l bilan kirilmaydi |
| `unknown_card` | Karta topilmadi (o'chirilgan yoki boshqa juftlikda) |
| `unknown_member`, `member_not_seated` | `assign`: menejer topilmadi yoki o'rindig'i yo'q |

Frontda: «Sotildi» va «Rad etildi» ustunlarini ommaviy ko'chirish ro'yxatida **ko'rsatmang**
(`kind: "won"`, `"lost"`). «Sifatsiz» (`junk`) ga ommaviy ko'chirish mumkin.

Tanlash: karta burchagida belgi (checkbox), tanlanganda pastda panel — «N ta tanlandi ·
Ko'chirish ▾ · Menejerga berish ▾ (faqat egasiga) · Bekor qilish».

## 3. Statistika: `sales.direct`

`GET /api/v1/crm/stats` (va Dashboard, Expert) → `sales.direct` — qo'lda qo'shilgan mijozlar
bo'yicha kataklar, `sales.totals` bilan bir xil kalitlar:

```json
"direct": {"leads": {"value": 1, "missing": null}, "sales": {"value": 1, "missing": null},
           "revenue": {"value": 20000, "missing": null}, "roas": {"value": null, "missing": "not_here"}}
```

- `sales.totals` — **faqat reklamadan kelgan** lidlar: ROAS va CAC shu sarfga qarshi qo'yiladi.
- `sales.direct` — qo'lda qo'shilganlar. Ularning sarfi yo'q, shuning uchun sarfga bog'liq
  kataklar `not_here`. Alohida kichik blok: «Reklamasiz mijozlar: N ta, sotuv M ta, daromad X».
- `/crm/stats` ning eski `totals`, `funnel`, `daily` maydonlari — **ikkalasi birga** (doskaning umumiy ishi).

`direct.leads.value` nol bo'lsa blokni ko'rsatmang.

## 4. Kunlik Telegram xabari (ma'lumot uchun)

Egasining kunlik va haftalik hisobotida CRM yoqilgan har bir juftlik uchun, kutayotgan ish bo'lsa,
qatorlar chiqadi:

- «CRM: 12 ta yangi lid hali olinmagan» — bir soatdan beri hech kim olmagan yangi lidlar;
- «CRM: 3 ta kartaning muddati o'tgan»;
- «CRM: 5 ta sifatli lid 7 kundan beri yopilmagan (sotildi yoki rad etildi deb belgilang)».

Hech narsa kutmayotgan bo'lsa qator chiqmaydi. Frontda ish yo'q.
