# Auditoriya qoidalari: front backend aytganini chizadi

Backend va front: `feat/audience-rules` (ikkala repo). Front bu hujjat bo'yicha o'zgartirildi.

## Nima o'zgardi

### 1. `GET /api/v1/launch/drafts/{id}/edit` → yangi `rules` (faqat o'qish uchun)

```jsonc
"rules": {
  "default": "auto",            // hech kim tanlamasa shu rejim
  "recommended": "auto",        // «Tavsiya» belgisi shunda; maxsus kategoriyada null
  "recommendedNote": "...",     // tavsiya sababi
  "locked": false,              // true: maxsus kategoriya, tanlov yo'q, bitta rejim
  "modes": [
    {
      "value": "auto",          // "auto" | "interests" | "broad"
      "title": "Meta o'zi tanlaydi",
      "note": "Qiziqishlar yuborilmaydi - ...",
      "fields": {
        "interests": "unused",   // exact | hint | unused | required
        "habits": "unused",
        "genders": "hint",
        "includeLists": "hint"
      },
      "age": { "min": 18, "max": 65, "lowestMax": 25, "upperSent": false, "fixed": false }
    }
    // interests, broad ...
  ]
}
```

Maydon qiymatlari:

| Qiymat | Ma'nosi | Front nima qiladi |
|---|---|---|
| `exact` | Meta'ga ketadi, aniq saqlanadi | Oddiy ko'rsatadi |
| `hint` | Ketadi, lekin Meta undan tashqariga chiqishi mumkin | Ko'rsatadi + «Meta uchun faqat yo'l-yo'riq» izohi |
| `unused` | Bu rejimda umuman yuborilmaydi | **Ko'rsatmaydi**: bo'lim (tab) va kartadagi qator yashiriladi |
| `required` | Ketadi, kamida bittasi bo'lmasa launch rad etiladi | Ko'rsatadi; bo'sh bo'lsa «cheklovsiz» emas, «kamida bitta qo'shing» deydi |

Yosh:
- `fixed: true` — 18–65, tahrirlab bo'lmaydi.
- `lowestMax` — «dan» bundan katta bo'lmaydi (auto'da 25). Kattasini kiritishga yo'l qo'ymang.
- `upperSent: false` — «gacha» Meta'ga yuborilmaydi (65+). «gacha» maydonini ko'rsatmang yoki «65+» deb qulflang.

Qoidalar foydalanuvchi rejimni almashtirganda darhol qo'llanadi: front tanlangan `aud.who` ga mos `modes[]` qatorini oladi. Qayta so'rov kerak emas.

Saqlashda (`PUT .../edit`) `rules` qaytarib yuborilsa ham e'tiborga olinmaydi.

### 2. Frontdan olib tashlanadigan qattiq qiymatlar

- `EditAud.tsx`: uchta rejim ro'yxati, «Tavsiya» belgisi, `AUTO_AGE_LIMIT = 25`, rejim matnlari → hammasi `rules`dan.
- «auto» uchun «qiziqishlar faqat yo'l-yo'riq» degan matn noto'g'ri edi: qiziqishlar yuborilmaydi. Matn `note`dan olinadi.
- `Edit.tsx`: `int` va `hab` tablari `fields.interests` / `fields.habits` `unused` bo'lsa ko'rinmaydi.
- `EditMisc.tsx`: `required` holatda bo'sh ro'yxatga «Hech narsa tanlanmagan — cheklovsiz» deb yozilmaydi.
- Yosh tekshiruvi (zod): 13 emas, `age.min`–`age.max`.

### 3. Ko'rib chiqish kartasi (`GET /api/v1/launch/drafts/{id}` → `proposal`)

O'zgarish frontsiz ishlaydi, faqat bilib qo'ying:
- `audience.age` — **Meta'ga ketadigan** yosh. Auto'da 30–50 kiritilsa `[25, 65]` keladi (65 = 65+).
- `audience.interests` — rejim qiziqish yubormasa `[]`.
- `audience.places` — xarita rejimida `"Chilonzor · 7 km atrofida"` kabi bitta qator (oldin bo'sh edi va karta «Butun mamlakat» derdi).
- `attention[]` ga yangi ikki xil:
  - `geo_widened` — hech kim joy tanlamagan, reklama butun mamlakatga ketadi. Tugma `to: "geo"`.
  - `interests_unconfirmed` — «Siz tanlagan qiziqishlar» rejimida Meta topmagan nomlar. Tugma `to: "int"`.
- `blockers[]` ga yangi `interests_missing`: qiziqishlar rejimida Meta'da topilgan birorta qiziqish ham, «Ko'rsatilsin» ro'yxati ham yo'q. Tugma `to: "int"`.

Meta tekshiruvi tugaguncha (bir necha soniya) yangi qo'shilgan qiziqish «topilmagan» bo'lib ko'rinishi mumkin. Taklif yangilanganda (poll) bu ogohlantirish o'zi yo'qoladi.

### 4. Joy

Faqat yosh yoki jins o'zgartirilib saqlanganda, hech kim tanlamagan joy endi «tanlangan» bo'lib qolmaydi. `geo_widened` ogohlantirishi owner joyni o'zi tanlamaguncha turadi.

### 5. Qiziqish qidiruvi

`GET /api/v1/launch/drafts/{id}/interests?q=engl` → `[{id, name, kind: "interests", path, lower, upper}]`.
Faqat Meta qiziqishlari (behaviour/life event emas: «Qiziqishlar» saqlanganda nomlar qiziqish katalogidan qayta topiladi).
Joy qidiruvi bilan bir xil cheklov (daqiqasiga) va 429. Front «Qiziqishlar» bo'limida erkin matn o'rniga shu qidiruvdan tanlaydi.
