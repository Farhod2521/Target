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

### Yangi sahifa: `/accounts/reset/:token/`

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

Bajarildi: frontendning `feat/audience-and-center` branch'ida. Tahrir oynasi
joylar, xarita, qiziqishlar, istisnolar, o'z auditoriyalar, tillar va qamrovni
ko'rsatadi. Bu ishni qayta boshlamang.

---

## 3. Ofis: biznes yo'nalishlari

Super admin uchun yangi sahifa. API: [OFIS_API.md](OFIS_API.md), 5a-bo'lim.
Menyu bandini faqat `can.superuser` bo'lganda ko'rsating: boshqa rollar, Owner
ham, `404` oladi.

Bu yo'llarning maydonlari OFIS_API.md B-ilovasida yo'q, ularni `gen/openapi.ts`dan
oling: `DirectionsOut`, `DirectionOut`, `NewDirectionIn`, `DirectionIn`.

---

## 4. Taklif etilgan tartib

Hammasi backend deploy qilingandan keyin ishlaydi. Eski front buzilmaydi.

1. CRM: `seat_open` va `seated`. Foydalanuvchi xato xabar ko'rayotgani uchun
   birinchi navbatda.
2. Parolni tiklash.
3. Meta xatolari, 2-qism.
4. Ofis: yo'nalishlar.
5. API v2 ga o'tish.
