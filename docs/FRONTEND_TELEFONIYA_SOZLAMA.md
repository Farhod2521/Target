# Ofis telefoniyasi (UTeL): sozlama sahifasi — frontend ishlari

Backend: `feat/office-telephony` shoxi, migratsiya `0046`. Avval backend deploy qilinadi.
Bu 1-bosqich: **faqat ulanish va sozlama**. Softfon, qo'ng'iroqlar jurnali va kiruvchi
qo'ng'iroq oynasi keyingi bosqichlarda keladi, ularning qo'llanmasi alohida bo'ladi.

Sozlama bitta: Sotuv va Support doskalari shu bitta ulanishdan foydalanadi.

Front fayllari: `apps/office/src/pages/boards/Settings.tsx` yoniga yangi sahifa
(masalan `apps/office/src/pages/telephony/`), `packages/api/src/` da yangi klient.
OpenAPI'ni qayta generatsiya qiling.

## 1. Sahifani kimga ko'rsatish

`GET /api/v2/office/me` → `can.telephony` (yangi maydon).

| `can.telephony` | Frontda |
|---|---|
| `true` | Menyuda «Telefoniya» bandi ko'rinadi (superuser va Owner roli) |
| `false` | Band yo'q. Bu odam quyidagi yo'llarga so'rov yuborsa **404** oladi |

## 2. Yo'llar

Hammasi `/api/v2/office/telephony` ostida. **Har biri bir xil javob qaytaradi** (3-bo'lim),
shuning uchun har amaldan keyin sahifani shu javob bilan yangilang, qayta `GET` shart emas.

| Yo'l | Nima qiladi | So'rov tanasi |
|---|---|---|
| `GET /` | Sahifa holati | — |
| `PUT /connection` | UTeL'ga kiradi, ichki nomerlarni o'qiydi, hodisalar manzilini o'rnatadi | `{"tenant", "email", "password"}` |
| `DELETE /connection` | Ulanishni, nomerlarni va kimga berilganini o'chiradi | — |
| `POST /sync` | Ichki nomerlarni UTeL'dan qayta o'qiydi | — |
| `POST /hook` | Hodisalar manzilini qayta o'rnatadi | — |
| `PATCH /extensions/{id}` | Nomerni xodimga beradi / oladi, brauzer telefonini yoqadi / o'chiradi | `{"user_id"?, "softphone"?}` |

`PUT /connection`, `POST /sync`, `POST /hook` va `DELETE /connection` UTeL'ga murojaat
qiladi: javob 1–15 soniya kutilishi mumkin. Tugmani kutish holatiga o'tkazing va ikkinchi
bosishni to'sing.

### `PUT /connection`

```json
{"tenant": "utc181", "email": "api@firma.uz", "password": "…"}
```

- `tenant`: UTeL manzili. `utc181`, `utc181.utel.uz`, `https://utc181.utel.uz/…` — hammasi
  qabul qilinadi, backend o'zi tozalaydi.
- `password` **saqlanmaydi**, faqat bir marta kirish uchun ishlatiladi. Formada
  `autocomplete="off"` qo'ying, javobdan keyin maydonni tozalang.
- Ulangan holatda shu formani qayta yuborish mumkin («Qayta kirish»): o'sha UTeL bo'lsa
  nomerlar va kimga berilgani saqlanadi. **Boshqa** `tenant` kiritilsa, eski nomerlar va
  bog'lanishlar o'chadi — yuborishdan oldin tasdiq so'rang.

### `PATCH /extensions/{id}`

Faqat yuborilgan maydon o'zgaradi:

| Tana | Natija |
|---|---|
| `{"user_id": "<xodim id>"}` | Nomer shu xodimga beriladi |
| `{"user_id": null}` | Nomer xodimdan olinadi |
| `{"softphone": false}` | Brauzer telefoni o'chadi, xodim o'zgarmaydi |
| `{"user_id": "…", "softphone": true}` | Ikkalasi birga |

Bir xodimda **bitta** nomer bo'ladi. Xodimga ikkinchi nomer berilsa, avvalgisi o'zi
bo'shaydi (javobda ko'rinadi) — bu xato emas, alohida ogohlantirish shart emas.

## 3. Javob

```json
{
  "connected": true,
  "connection": {
    "tenant": "utc181",
    "api_email": "api@firma.uz",
    "connected_at": "2026-11-12T09:00:00Z",
    "synced_at": "2026-11-12T09:00:01Z",
    "sip_domain": "utc181.utel.uz",
    "sip_socket": "wss://utc181.utel.uz:8089/ws",
    "hook_set_at": "2026-11-12T09:00:02Z",
    "last_event_at": null,
    "events_last_day": 0,
    "last_error": ""
  },
  "extensions": [
    {
      "id": "…",
      "number": "101",
      "title": "Operator 1",
      "user": {"id": "…", "name": "Ali Valiyev", "email": "ali@…"},
      "softphone": true,
      "is_gone": false
    }
  ],
  "staff": [{"id": "…", "name": "Ali Valiyev", "email": "ali@…"}]
}
```

Ulanmagan holatda: `connected: false`, `connection: null`, `extensions: []`, `staff` to'la.

Javobda parol, kalit va hodisalar manzili **yo'q** va bo'lmaydi.

| Maydon | Frontda |
|---|---|
| `connected` | `false`: faqat kirish formasi. `true`: holat kartasi va nomerlar jadvali |
| `connection.hook_set_at` | `null`: sariq ogohlantirish «UTeL hodisa yubormayapti», `last_error` matni va «Qayta o'rnatish» tugmasi (`POST /hook`) |
| `connection.last_event_at` | Oxirgi hodisa vaqti. `null`: «Hali hodisa kelmagan» |
| `connection.events_last_day` | Oxirgi 24 soatdagi hodisalar soni |
| `connection.synced_at` | «Nomerlar yangilangan vaqt», yonida «Yangilash» tugmasi (`POST /sync`) |
| `extensions[].user` | `null`: «Biriktirilmagan». Tanlov ro'yxati `staff` dan |
| `extensions[].softphone` | Tugmacha (switch). Xodim biriktirilmagan bo'lsa ham saqlanadi |
| `extensions[].is_gone` | `true`: qator xira, «UTeL'da yo'q» belgisi, xodim tanlovi o'chiq. Ular ro'yxat oxirida keladi |
| `staff` | Faol xodimlar. Boshqa nomerni ushlab turgan xodimni ham tanlash mumkin |

`sip_domain` va `sip_socket` hozircha faqat ma'lumot sifatida ko'rsatiladi; softfon
bosqichida ishlatiladi.

Nomerlar tartibi backenddan tayyor keladi (avval raqam bo'yicha, yo'qolganlari oxirida),
frontda qayta saralamang.

## 4. Xatolar

Hammasi odatdagi shaklda: `{"code": "...", "detail": "..."}`. `detail` o'zbekcha,
foydalanuvchiga shundayligicha ko'rsating.

| `code` | HTTP | Qachon | Frontda |
|---|---|---|---|
| `tenant_shape` | 422 | UTeL manzili noto'g'ri | `tenant` maydoni ostida |
| `exchange_refused_login` | 422 | UTeL login yoki parolni qabul qilmadi | `password` maydoni ostida |
| `exchange_unreachable` | 502 | UTeL javob bermadi | Toast, «Qayta urinish» |
| `exchange_session_ended` | 409 | UTeL saqlangan kalitni rad etdi (parol almashgan) | Kirish formasini oching: «Login va parolni qayta kiriting» |
| `not_connected` | 409 | Ulanish yo'q, lekin amal so'raldi | `GET /` ni qayta o'qing |
| `extension_not_found` | 404 | Nomer o'chgan | `GET /` ni qayta o'qing |
| `extension_gone` | 409 | UTeL'da yo'q nomerni xodimga berishga urinish | Toast |
| `not_staff` | 422 | Tanlangan odam faol xodim emas | Toast, `GET /` ni qayta o'qing |

## 5. Sahifa tarkibi (taklif)

1. **Ulanmagan:** qisqa izoh va forma — UTeL manzili, API login (email), parol, «Ulash».
2. **Ulangan, tepada holat kartasi:** tenant, API login, ulangan vaqt, hodisalar holati
   (`hook_set_at` / `last_event_at` / `events_last_day`), tugmalar: «Qayta kirish»,
   «Yangilash», «Uzish» (tasdiq bilan: «Nomerlar va biriktirishlar o'chadi»).
3. **Nomerlar jadvali:** Nomer · UTeL'dagi nomi · Xodim (tanlov) · Brauzer telefoni (switch).

## 6. Tekshirish ro'yxati

- [ ] `can.telephony: false` bo'lgan xodimda menyu bandi yo'q
- [ ] Noto'g'ri parol: xato `password` ostida, forma tozalanmaydi (paroldan tashqari)
- [ ] Ulashdan keyin nomerlar jadvali darhol chiqadi
- [ ] Xodimga ikkinchi nomer berilganda birinchisi «Biriktirilmagan» bo'ladi
- [ ] `is_gone` qatorda xodim tanlab bo'lmaydi
- [ ] `hook_set_at: null` da ogohlantirish va «Qayta o'rnatish» ishlaydi
- [ ] «Uzish» tasdiqdan keyin formaga qaytaradi
