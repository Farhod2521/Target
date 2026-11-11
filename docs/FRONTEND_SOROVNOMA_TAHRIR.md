# So'rovnoma: xodimlarga sinov, o'chirish, faol so'rovnomani tahrirlash, chala javoblar

Backend: `feat/survey-edit-staff-progress` branchi, migratsiya `0040`. Front hozir `8047ad0` holatida tekshirildi.

Qisqacha nima o'zgardi:

1. **Xodimlar (staff)** endi qabul qiluvchilar ro'yxatida bor. Ularni tanlab so'rovnomani o'zingizda sinab ko'rasiz.
2. **O'chirish** endi hech narsani bazadan o'chirmaydi. So'rovnoma yopiladi va ro'yxatdan yo'qoladi, savollar va javoblar qoladi. Faol yoki javob berilgan so'rovnomani ham o'chirish mumkin.
3. **Tahrirlash** faol va javob berilgan so'rovnomada ham ishlaydi. Javob bergan odamga qayta yuborilmaydi, yangi qo'shilgan odam yangilangan formani oladi. Endi nusxa olib qayta yuborish shart emas.
4. **Chala javoblar** saqlanadi. Mijoz har bir savolga javob berganda u darhol bazaga yoziladi, «Yuborish» bosilmasa ham. Keyingi safar dialog qolgan joyidan ochiladi.

---

## 1. Ofis: xodimlarni tanlash

### `GET /api/v1/office/surveys/roster`

`persons[]` ichida xodimlar ham keladi. Har bir odamda yangi maydon bor:

```json
{
  "id": "…", "name": "Ali", "email": "ali@office.uz", "phone": "",
  "plan_id": "", "plan": "", "trial": false,
  "staff": true
}
```

- `staff: true` bo'lgan odamning tarifi yo'q (`plan_id: ""`).
- `plans[]` jami sonlariga xodimlar kirmaydi.

**Front qiladigan ish** (`apps/office/src/pages/surveys/Audience.tsx`, `model.ts`):

- «Tanlanganlarga» ro'yxatida xodimlarni alohida guruh qilib ko'rsating, masalan «Xodimlar (sinov uchun)», yoki `Xodim` belgisi bilan.
- Hozir `reach()` va `Audience.tsx` tarifi yo'q odamni «tarifi tugagan» deb hisoblaydi (`!p.planId`). Xodimni bundan ajrating: `!p.planId && !p.staff`.
- «Barcha mijozlar» rejimi xodimlarga **yuborilmaydi**. Xodim faqat ismi bilan tanlanganda oladi.
- Xodim va hamma mijoz birga tanlansa, backend buni «everyone» deb saqlamaydi. Butun tarif + xodim ismi saqlanadi. `modeOf()` / `reach()` ham shunday hisoblasin: tanlanganlar orasida xodim bo'lsa, `everyone = false`.

**Xodim uchun so'rovnoma qanday ishlaydi:**

| | Mijoz | Xodim |
|---|---|---|
| Faol tarif kerakmi | ha | yo'q |
| «Necha kundan keyin» (`ask_after_days`) | ishlaydi | e'tiborga olinmaydi (darhol) |
| «Barchaga» so'rovnoma | oladi | olmaydi |
| Ismi bilan tanlangan | oladi | oladi |
| Botda | 10:00–21:00, soatning :11 da | xuddi shunday, agar xodim mijoz botiga ulangan bo'lsa (`telegram_chats`) |

Kabinetda sinab ko'rish: xodim kabinetga kirsa, `GET /api/v1/surveys/due` unga so'rovnomani qaytaradi. `packages/api/src/surveys.ts` dagi izohda «null (staff, …)» deb yozilgan, uni yangilang.

---

## 2. Ofis: o'chirish

### `POST /api/v1/office/surveys/{id}/delete`

```json
200 { "message": "So'rovnoma o'chirildi." }
```

- Endi **har doim** ruxsat: faol bo'lsa ham, javob berilgan bo'lsa ham. `survey_is_live` va `survey_has_answers` xatolari bu yerda endi qaytmaydi.
- O'chirilgandan keyin:
  - so'rovnoma hech kimga yuborilmaydi (botda boshlangan suhbat ham «yopilgan» deydi);
  - `GET /office/surveys` ro'yxatida chiqmaydi;
  - `GET /office/surveys/{id}` va unga tegishli boshqa so'rovlar `404` qaytaradi;
  - **javoblar qoladi**: «Javoblar» bo'limida (`GET /office/surveys/responses`) va mijoz kartasida ko'rinadi;
  - qayta o'chirish `404` qaytaradi.

**Front qiladigan ish** (`shared.tsx:358`):

- Shart `!s.active && s.answers === 0` ni olib tashlang. «O'chirish» tugmasi har doim ko'rinsin.
- Tasdiqlash dialogidagi matnni o'zgartiring, masalan: «So'rovnoma yopiladi va ro'yxatdan olinadi. Berilgan javoblar «Javoblar» bo'limida qoladi.»
- O'chirgandan keyin ro'yxat sahifasiga qayting (detal endi 404).

---

## 3. Ofis: faol yoki javob berilgan so'rovnomani tahrirlash

### `PUT /api/v1/office/surveys/{id}`

Body avvalgidek. **Yangi narsa:** har bir savolda `id` maydoni bor.

```json
{
  "name": "…", "source_language": "uz", "title": "…", "intro": "…",
  "questions": [
    { "id": "3f1c…", "kind": "choice", "text": "Yoqdimi?", "options": ["Ha", "Yo'q"], "is_required": true, "show_if": 0, "show_options": [] },
    { "id": "",      "kind": "text",   "text": "Yangi savol" }
  ],
  "people": ["…"], "starts_at": null, "ends_at": null, "ask_after_days": 7
}
```

- `id` — detal javobidagi `questions[].id`. Yangi savol uchun `""` yuboring yoki maydonni umuman qo'shmang.
- **`id` ni albatta qaytarib yuboring.** Savol id'si saqlanib qolsa, unga berilgan javoblar va «yordam kerak» belgilari (`HelpMarks`) ham saqlanadi. `id` yuborilmasa, hamma savol yangi deb hisoblanadi va «yordam kerak» belgilari yo'qoladi.
- Savol qachon eski id'sini saqlaydi: turi (`kind`), variantlar soni va raqam oralig'i (`min_value`/`max_value`) o'zgarmasa. Faqat matn o'zgarsa, id saqlanadi. Variant qo'shilsa yoki olib tashlansa, turi yoki oralig'i o'zgarsa, u yangi savolga aylanadi.
- Ro'yxatda yo'q savol olib tashlanadi, lekin unga berilgan javoblar o'qiladigan bo'lib qoladi (pastdagi `removed` ga qarang).
- Matn o'zgarsa, so'rovnoma `state: "translating"` ga o'tadi va faolligicha qoladi. Tarjima tugaguncha boshqa tildagi mijozlar asl tildagi matnni ko'radi.
- `POST /{id}/retranslate` endi faol so'rovnomada ham ishlaydi.
- `survey_is_live` va `survey_has_answers` xatolari tahrirlashda endi qaytmaydi. `survey_is_translating` qoladi: tarjima ketayotganda saqlab bo'lmaydi.

**Kimga yuboriladi:**

- So'rovnomani **tugatgan** odamga qayta yuborilmaydi.
- **Yangi qo'shilgan** odam yangilangan formani oladi.
- **Chala qoldirgan** odam ham yangilangan formani oladi. U javob bergan savollar (id'si saqlanganlari) tayyor bo'lib turadi.

**Front qiladigan ish** (`Editor.tsx`, `Questions.tsx`, `model.ts`):

- `isFrozen()` qulfini va «Savollar qulflangan / Nusxa olib o'zgartirish» bannerini olib tashlang. Savollar har doim tahrirlanadi. Faqat `state === "translating"` paytida qulflansin, bu hozir ham bor.
- Formadagi savollarga `id` ni saqlang va `PUT` bilan qaytaring. `M.add()` yangi savolga `id: ""` bersin. `M.move()` id'ni saqlab qolsin.
- Javob berilgan so'rovnomada saqlashdan oldin ogohlantirish chiqaring, masalan: «Javob bergan N kishiga qayta yuborilmaydi. Variantlar sonini o'zgartirsangiz, bu savol yangi savol bo'ladi.»
- «Nusxa olish» tugmasi qolishi mumkin, lekin endi u asosiy yo'l emas.

---

## 4. Chala javoblar: mijoz kabineti va mini app

### Yangi: `POST /api/v1/surveys/progress`

Har bir javobdan keyin chaqiring: «Keyingi» bosilganda, variant tanlanganda, matn maydonidan chiqilganda (`blur`), dialog yopilganda va «Keyinroq» bosilganda.

```json
POST /api/v1/surveys/progress
{ "survey": "<survey_id>", "answers": { "<question id>": ["1"] }, "channel": "web" }

200 { "saved": 2 }
```

- `answers` — **shu paytgacha berilgan javoblar**. Faqat oxirgisini yuborsangiz ham bo'ladi: backend uni oldingi saqlanganlar ustiga qo'shadi.
- Bo'sh ro'yxat (`[]`) o'sha javobni o'chiradi.
- Hech narsa majburiy emas. Savolga mos kelmaydigan qiymat (masalan oraliqdan tashqaridagi raqam) xato bermaydi, shunchaki saqlanmaydi.
- Tanlov o'zgarib, unga bog'liq savol yashirinsa, o'sha savolning javobi o'chadi.
- `saved` — saqlangan javoblar soni. Hech narsa javob berilmagan bo'lsa `0` keladi va qator yaratilmaydi.
- Xatolar:
  - `400 survey_not_due` — so'rovnoma yopilgan, o'chirilgan yoki allaqachon tugatilgan. Dialogni yoping.
  - `401` — avvalgidek.
- `channel`: mini app ichida `"miniapp"`, aks holda `"web"`.

### `GET /api/v1/surveys/due` — yangi `saved` maydoni

```json
{
  "survey": {
    "survey_id": "…", "language": "uz", "title": "…", "intro": "…",
    "questions": [ … ],
    "saved": { "<question id>": ["1"], "<question id>": ["Qimmat"] }
  },
  "always": 2
}
```

- `saved` — mijoz oldin bergan javoblar, `POST /surveys/answer` qabul qiladigan formatda. Birinchi marta ochilganda `{}` keladi.
- Dialog shu javoblar bilan to'ldirilib ochilsin va **birinchi javobsiz savoldan** boshlansin.

### `POST /api/v1/surveys/answer` — o'zgarmadi

- Hamma javoblarni yuboring. Yuborsangiz ham, faqat qolganlarini yuborsangiz ham bo'ladi: backend saqlanganlar bilan qo'shadi.
- Majburiy savollar shu yerda tekshiriladi. Javob o'sha chala qatorning o'ziga yoziladi va so'rovnoma «tugatildi» deb belgilanadi.
- Tugatilgandan keyin so'rovnoma qayta so'ralmaydi.

**Front qiladigan ish** (`packages/api/src/surveys.ts`, `apps/cabinet/src/pages/surveys/SurveyDialog.tsx`):

- `useSaveSurveyProgress()` mutatsiyasini qo'shing (`POST /surveys/progress`). U `dueSurveyKey` ni tozalamasin.
- `DueSurvey` turiga `saved: Record<string, string[]>` qo'shing. Dialog `answers` holatini shundan boshlasin. Birinchi qadam: `askedQuestions()` ichida `saved` da javobi yo'q birinchi savol.
- Har bir qadamdan keyin, «Keyinroq» va «Yopish» bosilganda `progress` ni chaqiring. Agar `progress` `survey_not_due` qaytarsa, dialogni yoping.
- Tarmoq xatosida jim qoling: keyingi qadam yana yuboradi.

**Botda** hech narsa qilish shart emas. Bot har bir javobni o'zi saqlaydi va to'xtagan joyidan davom etadi.

---

## 5. Ofis: chala javoblarni ko'rsatish

### `GET /api/v1/office/surveys` (ro'yxat)

Har qatorda `answers` endi faqat **tugatilgan** javoblar soni. Yangi maydon:

```json
{ "answers": 12, "partial": 3 }
```

### `GET /api/v1/office/surveys/{id}` (detal)

Yangi maydon: `partial`.

### `GET /api/v1/office/surveys/responses`

- Yangi filtr: `?finished=true` — faqat tugatilganlar, `?finished=false` — faqat chalalar. Parametr berilmasa, hammasi keladi.
- Har qatorda yangi maydonlar:

```json
{ "finished": false, "completed_at": null, "at": "2026-11-11T07:41:37Z" }
```

`at` — birinchi javob saqlangan vaqt. `completed_at` — tugatilgan vaqt, chala bo'lsa `null`.

### `GET /api/v1/office/surveys/responses/{id}`

`lines[]` har bir qatorida yangi maydon:

```json
{ "question": "Yoqdimi?", "kind": "choice", "answer": "Ha", "removed": false }
```

- `question` va `answer` — javob **berilgan paytdagi** matn. So'rovnoma keyin tahrirlansa ham bular o'zgarmaydi.
- `removed: true` — bu savol keyinchalik so'rovnomadan olib tashlangan. Kulrang qilib yoki «olib tashlangan savol» deb ko'rsating.

### `GET /api/v1/office/surveys/{id}/results`

- `funnel.answered` — tugatganlar soni.
- Yangi: `funnel.partial` — boshlab, tugatmaganlar soni.
- Chala javoblar har bir savol statistikasiga kiradi (`questions[].answered`, variantlar, raqamlar).

### `GET /api/v1/office/customers/{id}/surveys`

Har qatorda yangi maydon: `finished`.

### Excel (`/{id}/excel`)

Yangi «Holati» ustuni qo'shildi: «Tugatgan» yoki «Chala». «Sana» ustuni tugatilgan vaqtni ko'rsatadi, chala bo'lsa birinchi javob vaqtini.

**Front qiladigan ish:**

- `Surveys.tsx`: «Javoblar» ustunida `partial` bo'lsa uni ham ko'rsating, masalan «12 · 3 chala».
- `Responses.tsx`: «Holati» filtri (Hammasi / Tugatgan / Chala) va qatorda «Chala» belgisi.
- `Response.tsx`: `removed` qatorlarini ajratib ko'rsating.
- `Results.tsx`: voronkaga «Chala qoldirgan» qatorini qo'shing.

---

## Tekshirish ro'yxati (front tayyor bo'lganda)

1. Ofisda o'zingizni (xodim) tanlab, «necha kundan keyin» ni istalgan qiymatda qoldirib e'lon qiling. Kabinetga kirganingizda so'rovnoma darhol chiqishi kerak.
2. Bitta savolga javob berib, dialogni yoping. Ofis «Javoblar» bo'limida «Chala» qator ko'rinsin. Sahifani yangilang: dialog o'sha javob bilan, keyingi savoldan ochilsin.
3. Faol so'rovnoma savolining matnini o'zgartirib saqlang. Tugatgan odamga qayta chiqmasin, yangi tanlangan odamga yangi matn chiqsin.
4. Javob berilgan so'rovnomani o'chiring. U ro'yxatdan yo'qolsin, javoblari «Javoblar» bo'limida qolsin.
