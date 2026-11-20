# Mijoz CRM: valyutani tanlash — frontend ishlari

Backend: `feat/crm-sales-metrics` shoxi, migratsiya `0072`. Avval backend deploy qilinadi.
Bu «Reklama → Sotuv» ko'rsatkichlari rejasining 1-bosqichi (valyuta va kurs). ROAS, CAC va
boshqa ko'rsatkichlar keyingi bosqichlarda keladi.

Eski front yangi backend bilan buzilmaydi: yangi maydonlar qo'shildi, eskisi o'zgarmadi.

## Nima o'zgardi (qisqa)

| # | O'zgarish |
|---|---|
| 1 | Egasi CRM valyutasini o'zi tanlaydi (har bir sahifa + akkaunt juftligi uchun alohida) |
| 2 | Yopilgan sotuv o'z valyutasida qoladi; yig'indilar juftlik valyutasida, sotuv yopilgan kun kursi bilan |
| 3 | Doska javobida `currency` maydoni: ustundagi `won_minor` shu valyutada |
| 4 | Statistikada `totals.revenue_unpriced`: kurs topilmagani uchun daromadga qo'shilmagan sotuvlar soni |

## 1. Valyutani tanlash

`GET /api/v1/crm/settings` javobida yangi maydon:

```json
"currency_choices": [
  {"value": "UZS", "label": "O'zbek so'mi (UZS)"},
  {"value": "USD", "label": "AQSH dollari (USD)"},
  {"value": "EUR", "label": "Yevro (EUR)"},
  {"value": "RUB", "label": "Rossiya rubli (RUB)"},
  {"value": "KZT", "label": "Qozog'iston tengesi (KZT)"}
]
```

Hozirgi qiymat avvalgidek `setup.currency` da.

Saqlash: `POST /api/v1/crm/settings/currency`, tana `{"currency": "USD"}`. Javob — to'liq
sozlamalar (`SettingsOut`), boshqa sozlash tugmalaridagi kabi.

| Holat | Javob |
|---|---|
| Ro'yxatda yo'q valyuta | 400, `code: "unknown_currency"`, matn: «Valyutani ro'yxatdan tanlang.» |
| Menejer yuborsa | 404 (boshqa sozlamalardagi kabi, faqat egasi) |

Sozlash ustasida (CRM hali `draft`) ham ishlaydi: valyutani ustaning istalgan qadamida
so'rash mumkin.

### O'zgartirishdan oldin ogohlantirish

Valyuta o'zgarganda ikki narsa bo'ladi, dialogda aytib qo'ying:

- **Yopilgan sotuvlar o'zgarmaydi.** Ular yozilgan valyutasida qoladi; hisobotlarda yangi
  valyutaga o'sha kun kursi bilan o'tkazib ko'rsatiladi.
- **Menejerning fix maoshi o'chadi.** U eski valyutadagi summa edi; foiz qoladi. Javobdagi
  `members[]` da `kpi_fix_minor: null`, `kpi_currency: ""` bo'lib keladi — egasi qayta
  kiritadi.

## 2. Summalar qaysi valyutada

| Joy | Maydon | Valyuta |
|---|---|---|
| Karta | `card.won_amount_minor` + `card.currency` | Sotuv yozilgan valyuta (o'zgarmaydi) |
| «Sotildi» dialogi | `GET /cards/{id}` → `currency` | Juftlikning hozirgi valyutasi |
| Doska ustuni | `columns[].won_minor` + doska `currency` (yangi) | Juftlik valyutasi |
| Statistika | `totals.revenue_minor`, `managers[].revenue_minor`, `ads[].revenue_minor` + `currency` | Juftlik valyutasi |

Kartadagi summani har doim **kartaning o'z** `currency` si bilan chizing, doskaniki bilan
emas: valyuta o'zgargandan keyin ular farq qilishi mumkin.

## 3. `revenue_unpriced`

`GET /api/v1/crm/stats` → `totals.revenue_unpriced` (son, odatda `0`).

Boshqa valyutada yopilgan sotuv uchun o'sha kun kursi bazada bo'lmasa, u daromadga
qo'shilmaydi va shu yerda sanaladi. `0` dan katta bo'lsa, daromad yonida izoh ko'rsating:
«N ta sotuv hisobga kirmadi: o'sha kun kursi yo'q». `avg_deal_minor` faqat narxlangan
sotuvlar bo'yicha hisoblanadi.

Kurs manbai: O'zbekiston Markaziy bankining kunlik kursi. Dam olish kuni uchun undan
oldingi oxirgi kurs olinadi.
