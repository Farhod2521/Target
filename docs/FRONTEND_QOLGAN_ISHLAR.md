# Boshqa hujjatda yozilmagan frontend ishlari — 2026-10-31

Barcha yo'llar `/api/v1` ostida. Boshlashdan oldin OpenAPI'dan
`gen/openapi.ts`ni qayta yarating.

Bu yerda uchta ish bor. Qolgan yangi ishlar o'z hujjatlarida:
[CRM_API_OZGARISHLAR.md](CRM_API_OZGARISHLAR.md),
[META_XATOLAR_FRONTEND_2.md](META_XATOLAR_FRONTEND_2.md),
[API_V2_CAMPAIGNS.md](API_V2_CAMPAIGNS.md).

---

## 1. Parolni tiklash

Parol Telegram bot orqali tiklanadi. Havola faqat kabinetga ulangan chatga
boradi.

### Kirish sahifasi

"Parolni unutdingizmi?" bosilganda:

```http
GET /auth/reset
```

```json
{"bot_url": "https://t.me/..."}
```

`bot_url` ni oching. Bo'sh satr kelsa, bot ulanmagan: Support bilan bog'lanishni
ko'rsating.

### Yangi sahifa: `/accounts/parol/:token/`

Bot foydalanuvchini shu sahifaga yuboradi. Havola 15 daqiqa ishlaydi va bir
marta ishlatiladi.

1. Sahifa ochilganda havolani tekshiring:

   ```http
   GET /auth/reset/{token}
   ```

   ```json
   {"email": "user@example.com"}
   ```

2. Forma yuboriladi:

   ```http
   POST /auth/reset/{token}
   {"new_password1": "...", "new_password2": "..."}
   ```

   Javob `TokenPair`, xuddi `POST /auth/login`dagidek. Tokenlarni saqlab,
   foydalanuvchini kabinetga o'tkazing. Boshqa qurilmalardagi sessiyalar yopiladi.

| Javob | Qachon | Nima qilish kerak |
|---|---|---|
| `400`, `code: reset_link_invalid` | Havola eskirgan, ishlatilgan yoki noto'g'ri. `GET` ham, `POST` ham | `detail` matnini ko'rsating, formani chizmang. Matn: "Havola eskirgan yoki ishlatilgan. Botdan yangi havola oling." |
| `422`, `new_password2` | Ikki parol bir xil emas | Maydon ostida ko'rsating |
| `422`, `new_password` | Parol talablarga javob bermadi | Matnni ko'rsating. Havola kuymaydi, yana urinsa bo'ladi |

---

## 2. Ishlayotgan reklamada joylashuvni o'zgartirish

Kampaniya tahriri endi auditoriya joylarini ham ko'rsatadi va almashtiradi.
Launch'dagi joy qidiruvi bilan bir xil ishlaydi:
[FRONTEND_GEOLOCATION.md](FRONTEND_GEOLOCATION.md).

### Forma

`GET /campaigns/{id}/edit` javobiga qo'shildi:

```json
{
  "places": [{"id": "UZ", "name": "UZ", "type": "country"}],
  "placeLimit": 10,
  "canMove": true,
  "learning": false
}
```

- `canMove: false` — joyni o'zgartirib bo'lmaydi, maydonni faqat o'qish uchun
  ko'rsating.
- `learning: true` — guruh o'rganish bosqichida. Bu holatda ham `canMove: true`
  bo'lishi mumkin: `locks.audience` `"learning"` bo'lsa ham joy o'zgaradi,
  auditoriyaning boshqa qismlari (yosh, jins) esa o'zgarmaydi.
- `learning: true` va `canMove: true` bo'lsa, saqlashdan oldin ogohlantiring:
  joyni o'zgartirish o'rganishga ta'sir qilishi mumkin. Qarorni ega qiladi.

### Qidiruv

```http
GET /campaigns/{id}/locations?q=tosh&country=UZ
```

`country` ixtiyoriy. Javob:

```json
[{"id": "111", "name": "Toshkent", "type": "city", "context": "...", "country_code": "UZ"}]
```

`context` bir xil nomli joylarni ajratadi, ro'yxatda ko'rsating. Daqiqasiga 60 ta
qidiruvdan oshsa `429` keladi.

### Saqlash

`PATCH /campaigns/{id}` body'siga `places` qo'shildi:

```json
{
  "dailyBudget": 10,
  "ageMin": 25,
  "ageMax": 45,
  "gender": "all",
  "audienceIds": [],
  "places": [{"id": "111", "name": "Toshkent", "type": "city"}]
}
```

`places` ro'yxati **to'liq** yuboriladi: u eskisini butunlay almashtiradi. Joy
o'zgarmasa, maydonni yubormang.

Yangi joy faqat `/locations` qidiruvidan olingan bo'lishi kerak. Aks holda, yoki
ro'yxat bo'sh yoki 10 tadan ko'p bo'lsa, `422` keladi va xato `places` maydoniga
biriktiriladi.

---

## 3. Ofis: biznes yo'nalishlari

Super admin uchun yangi sahifa. API: [OFIS_API.md](OFIS_API.md), 5a-bo'lim.
Menyu bandini faqat `can.superuser` bo'lganda ko'rsating: boshqa rollar, Owner
ham, `404` oladi.

---

## 4. Taklif etilgan tartib

Hammasi backend deploy qilingandan keyin ishlaydi. Eski front buzilmaydi.

1. CRM: `seat_open` va `seated`. Foydalanuvchi xato xabar ko'rayotgani uchun
   birinchi navbatda.
2. Parolni tiklash.
3. Meta xatolari, 2-qism.
4. Joylashuvni o'zgartirish.
5. Ofis: yo'nalishlar.
6. API v2 ga o'tish.
