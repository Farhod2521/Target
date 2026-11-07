# Google orqali kirish va «Siz kimsiz?» — frontend uchun

Backend: branch `feat/google-login`. Barcha manzillar `https://api.targetolog.ai/api/v1` bilan boshlanadi.

**Xato javobi:** `{"detail": "matn", "code": "...", "problems": {"maydon": "matn"}}`
- `problems` faqat `422` da keladi. Matnni o'sha maydon ostida ko'rsating.
- Boshqa xatolarda `detail` ni ko'rsating.

**Rollar** (`role`):

| Qiymat | Ko'rinadigan matn |
|---|---|
| `business_owner` | Biznes egasi |
| `targetolog` | Targetolog |
| `marketer` | Marketolog / SMM |
| `agency` | Agentlik |
| `other` | Boshqa |

---

## 1. Kirish va ro'yxatdan o'tish sahifalari — «Google» tugmasi

### 1.1 Tugmani ko'rsatish

`GET /auth/social` — token kerak emas → `{"providers": ["google"]}`

- Ro'yxat bo'sh bo'lsa, tugma va «yoki» chizig'i chizilmaydi.
- `AuthContext.social` maydoni shu javobdan to'ldiriladi. Hozir bridge buni bermaydi, shuning uchun tugmalar yashirin.
- Faqat Google keladi. Facebook va Telegram keyin qo'shiladi.

### 1.2 Bosilganda

`POST /auth/social/google/start` — token kerak emas

```json
{ "next": "/app/billing/?plan=pro", "referral_code": "ABC123", "language": "uz" }
```

Hamma maydon ixtiyoriy:
- `next` — kirgandan keyin ochiladigan sahifa. U `/app/` bilan boshlanmasa, `/app/` ochiladi.
- `referral_code` — `/r/<code>/` havolasidan eslab qolingan kod.
- `language` — `uz`, `ru` yoki `en`.

Javob: `{"url": "https://accounts.google.com/..."}` → `location.assign(url)`.

Xatolar: `404 social_unavailable` (Google o'chirilgan), `429` (juda ko'p bosilgan).

### 1.3 Telegram Mini App ichida

Google o'z kirish oynasini Telegram WebView ichida bloklaydi (`disallowed_useragent`).
- Mini App ichida (`initData()` bor bo'lsa) Google tugmasini **ko'rsatmang**.
- Yoki `url` ni `Telegram.WebApp.openLink(url)` bilan tashqi brauzerda oching.

### 1.4 Google'dan qaytish

Backend brauzerni quyidagi 3 manzildan biriga yuboradi:

| Manzil | Nima qilinadi |
|---|---|
| `/accounts/handoff/<token>/` | Kirish muvaffaqiyatli. **Mavjud** `Handoff.tsx` sahifasi o'zi ishlaydi, yangi ish kerak emas |
| `/accounts/social/<token>/` | **Yangi sahifa** (2-bo'lim): telefon va rol so'raladi |
| `/accounts/login/?social_error=<kod>` | Xato. Login sahifasida xabar chiqaring (jadval pastda) |

`social_error` kodlari:

| Kod | Ko'rsatiladigan matn (taklif) |
|---|---|
| `cancelled` | Google orqali kirish bekor qilindi. |
| `expired` | Vaqt tugadi. Qaytadan urinib ko'ring. |
| `failed` | Google bilan bog'lanib bo'lmadi. Qaytadan urinib ko'ring. |
| `unverified` | Bu Google akkauntining emaili tasdiqlanmagan. Boshqa usul bilan kiring. |
| `blocked` | Akkaunt bloklangan. Yordam chatiga yozing. |
| `unavailable` | Google orqali kirish hozircha o'chirilgan. |

Xabarni ko'rsatgandan keyin `social_error` ni manzildan olib tashlang (`replace`).

Backend akkauntni quyidagicha tanlaydi:
- Google akkaunti avval ulangan bo'lsa, o'sha akkauntga kiradi.
- Google email'i tasdiqlangan va bizdagi akkaunt email'iga to'g'ri kelsa, Google o'sha akkauntga avtomatik ulanadi va foydalanuvchi kiradi.
- Boshqa hollarda yangi odam deb hisoblanadi va `/accounts/social/<token>/` ochiladi.

---

## 2. Yangi sahifa: `/accounts/social/<token>/` — «Ro'yxatdan o'tishni yakunlang»

Token 30 daqiqa amal qiladi. Sahifa `BareShell` va `AuthPage` uslubida bo'ladi.

### 2.1 Ochilganda

`GET /auth/social/finish/{token}` — token kerak emas

```json
{ "provider": "google", "email": "vali@gmail.com", "full_name": "Vali Aliyev" }
```

`410 social_expired` qaytsa, `/accounts/login/?social_error=expired` ga o'ting (`replace`).

### 2.2 Forma

| Maydon | Holati |
|---|---|
| Email | Faqat o'qish uchun (`email`) |
| Ism | `full_name` bilan to'ldirilgan, o'zgartirish mumkin |
| Telefon | **majburiy**, ro'yxatdan o'tish formasidagi bilan bir xil input |
| Siz kimsiz? | **majburiy**, 5 ta tugmadan bittasi tanlanadi |

### 2.3 Yuborish

`POST /auth/social/finish/{token}` — token kerak emas

```json
{ "phone": "+998901234567", "role": "targetolog", "full_name": "Vali Aliyev" }
```

`full_name` bo'sh bo'lsa, Google bergan ism saqlanadi.

**200:** `{"access_token", "refresh_token", "token_type", "next"}`
- Token juftligini saqlang (`tokens.set`), `meKey` ni yangilang va `next` ga o'ting.
- Bu `redeemHandoff` qiladigan ish bilan bir xil.

Xatolar:

| Status / kod | Nima qilinadi |
|---|---|
| `422 phone_taken`, `problems.phone` | Matnni telefon ostida ko'rsating va **«Parol bilan kirish»** tugmasini qo'shing (`/accounts/login/`). Token o'chmaydi, raqamni tuzatib qayta yuborish mumkin |
| `422 bad_phone` | `detail` ni telefon ostida ko'rsating |
| `422 invalid_input` | Rol tanlanmagan yoki noto'g'ri |
| `409 conflict` | Bu email bilan akkaunt shu orada ochilgan. «Google orqali qayta kiring» deb, login sahifasiga yuboring |
| `410 social_expired` | Login sahifasiga `?social_error=expired` bilan yuboring |
| `429` | `detail` ni ko'rsating |

---

## 3. Oddiy ro'yxatdan o'tish formasi — «Siz kimsiz?»

`POST /auth/signup` ga yangi maydon qo'shildi: `"role": "business_owner"`.

- Formada majburiy qiling: tanlanmaguncha «Ro'yxatdan o'tish» tugmasi ishlamasin.
- Backend uni hozircha majburiy deb tekshirmaydi, chunki eski front ishlab tursin. Rol yuborilmasa, kirishdan keyin 4-bo'limdagi oyna so'raydi.
- `SignupInput` ga `role` qo'shing va bridge'da `json` ga uzating.

---

## 4. Eski foydalanuvchilar: «Siz kimsiz?» bir marta so'raladi

`GET /account` (me) javobiga yangi maydonlar qo'shildi:

| Maydon | Ma'nosi |
|---|---|
| `role` | `""` yoki rol qiymati |
| `role_needed` | `true` → rol so'ralishi kerak. CRM menejerlarida hech qachon `true` bo'lmaydi |
| `has_password` | `false` → akkaunt Google orqali ochilgan va paroli yo'q |

- Kabinetga kirilganda `role_needed === true` bo'lsa, yopib bo'lmaydigan oyna chiqadi: «Siz kimsiz?» va 5 ta tugma.
- Saqlash: `PUT /account/role` `{"role": "agency"}` → yangilangan `UserOut`. Shundan keyin oyna yopiladi.
- Mini App ichida ham shunday ishlaydi.
- Profil sahifasida rolni keyin ham o'zgartirsa bo'ladi (xuddi shu `PUT`).

---

## 5. Profil / Sozlamalar → «Kirish usullari»

### 5.1 Holat

`GET /account/social`

```json
{
  "providers": ["google"],
  "has_password": true,
  "linked": [
    { "provider": "google", "email": "vali@gmail.com", "created_at": "...", "last_used_at": "..." }
  ]
}
```

- `providers` dagi har bir provayder uchun bitta qator chiqadi.
- Provayder ulangan bo'lsa: email va «Uzish» tugmasi.
- Ulanmagan bo'lsa: «Ulash» tugmasi.

### 5.2 Ulash

`POST /account/social/google/start` `{"next": "/app/account/"}` → `{"url"}` → `location.assign(url)`

- Google email'i akkaunt email'idan **boshqa** bo'lishi mumkin.
- Brauzer `next` ga qaytadi (default `/app/account/`) va manzilga shulardan biri qo'shiladi:
  - `?linked=google` → «Google ulandi» toast'i;
  - `?social_error=taken` → «Bu Google akkaunti boshqa akkauntga ulangan»;
  - `?social_error=cancelled`, `failed`, `expired` yoki `unavailable` → 1.4 dagi matnlar.
- Toast ko'rsatilgach, parametrni manzildan olib tashlang.

### 5.3 Uzish

`DELETE /account/social/google` → `204`

`409 social_last_way` → `detail` ni ko'rsating: «Avval parol o'rnating…». Bu Google orqali ochilgan, paroli yo'q akkauntda chiqadi.

### 5.4 Parolsiz akkauntga parol o'rnatish

`PUT /account/password` `{"current_password": "", "new_password": "..."}`

- `has_password === false` bo'lsa, «Joriy parol» maydonini **ko'rsatmang** va `""` yuboring.
- Sarlavha «Parolni o'zgartirish» emas, «Parol o'rnatish» bo'ladi.

---

## 6. Office → Mijozlar

### 6.1 Ro'yxat — `GET /office/customers`

- Har bir qatorda `role: {code, label} | null` bor. `null` → «So'ralmagan».
- Yangi filtr: `role=` query parametri.
- Filtr qiymatlari javobdagi `roles: [{value, label}]` dan olinadi. `none` qiymati rol so'ralmaganlarni ko'rsatadi.

### 6.2 Mijoz kartasi — `GET /office/customers/{id}`

`profile` ichida yangi maydonlar:

| Maydon | Ma'nosi |
|---|---|
| `role` | `{code, label} \| null` |
| `social_only` | `true` → «Faqat Google orqali kiradi» |
| `sign_ins` | `[{provider, email, linked_at, last_used_at}]` → «Kirish usullari» qatori |

---

## Tekshiruv ro'yxati

- [ ] Login va Signup: `GET /auth/social` → Google tugmasi chiqadi va bosilganda Google ochiladi
- [ ] Mini App ichida Google tugmasi yo'q (yoki tashqi brauzerda ochiladi)
- [ ] Login sahifasi `social_error` ning 6 ta kodini ko'rsatadi
- [ ] `/accounts/social/<token>/` sahifasi: ma'lumotni olish, forma, `phone_taken`, `410`, muvaffaqiyatli yakun
- [ ] Signup formasida «Siz kimsiz?» majburiy va `role` yuboriladi
- [ ] `role_needed` oynasi bir marta chiqadi va `PUT /account/role` qilinadi
- [ ] Profil: rolni o'zgartirish
- [ ] Profil: «Kirish usullari» — ulash, `linked` yoki `social_error` toast'i, uzish, `social_last_way`
- [ ] Parolsiz akkaunt: joriy parolsiz parol o'rnatish
- [ ] Office: ro'yxatda rol ustuni va filtri, kartada rol, `social_only` va `sign_ins`
- [ ] Mock handler'lar yangi endpoint'lar bo'yicha yangilangan
