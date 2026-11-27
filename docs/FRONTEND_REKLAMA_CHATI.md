# Reklama yaratish chati — frontend qo'llanma

Backend: `feat/business-knowledge` branchi. Bu chat faqat **ofis ichida, xodimlar sinovi
uchun** ochiladi (backendda cheklov yo'q — frontda ko'rsatmang). Eski «Reklama berish»
sahifalari o'zgarmagan va ishlayveradi.

## 1. G'oya

Chat — suhbat orqali to'ldiriladigan forma. Har javobda backend:

- ko'rsatiladigan qatorlarni (`lines`),
- kutilayotgan **bitta** savolni tugmalari bilan (`ask`),
- shu paytgacha aniqlangan narsalarni (`chips`)

qaytaradi. Matnlarni backend yozadi (o'zbekcha, tayyor qoliplardan), front hech narsa
to'qimaydi. Tugma bosilganda AI chaqirilmaydi — javob darhol keladi. Yozma xabar bitta
qisqa AI chaqiruvidan o'tadi (taxminan 2–3 soniya).

Chat mavjud «Reklama berish» ning o'zini boshqaradi: savollar uning birinchi qadamini
to'ldiradi, keyin media, tayyorlash va ishga tushirish ham shu suhbatda o'tadi
(5-bo'lim). Hammasi o'sha `launch` ga yoziladi, shuning uchun eski sahifalar bilan bir
xil natija chiqadi.

## 2. API

Hammasi `Authorization: Bearer …` bilan, javob shakli bir xil (`SessionOut`).

| Yo'l | Nima qiladi |
|---|---|
| `POST /api/v3/launch-agent/sessions` | Suhbatni ochadi. Shu reklama uchun tugallanmagan suhbat bo'lsa, o'shani davom ettiradi |
| `GET /api/v3/launch-agent/sessions/{id}` | Hozirgi holat (sahifa qayta ochilganda) |
| `POST /api/v3/launch-agent/sessions/{id}/turns` | Bitta xabar yoki bitta tugma |
| `POST /api/v3/launch-agent/sessions/{id}/voice` | Ovozli yozuvni matnga aylantiradi (9-bo'lim) |
| `POST /api/v3/launch-agent/sessions/{id}/close` | Suhbatni yopadi (204) |

### So'rov (`turns`)

Yozma xabar:

```json
{"text": "IELTS kursiga ariza kerak, kuniga 5 dollar"}
```

Tugma (oxirgi javobdagi `ask.options[]` dan `slot` va `value` aynan o'zi):

```json
{"slot": "goal", "value": "leads"}
```

### Javob (`SessionOut`)

```json
{
  "session_id": "…",
  "status": "open",
  "lines": [],
  "ask": {
    "slot": "goal",
    "text": "Reklamadan nima kerak?",
    "options": [
      {"label": "Ariza qoldirsin", "slot": "goal", "value": "leads", "recommended": false, "opens": ""},
      {"label": "Xabar yozsin", "slot": "goal", "value": "messages", "recommended": false, "opens": ""}
    ],
    "input": "text",
    "hint": ""
  },
  "chips": [{"slot": "offer", "label": "Reklama", "value": "IELTS kursi"}],
  "ready": false,
  "stage": "asking",
  "wait": false,
  "card": null,
  "launch_id": "…",
  "next": "",
  "messages": [{"author": "agent", "text": "…", "at": "2026-11-27T…"}],
  "turns_left": 39
}
```

- `lines` — savoldan oldin ko'rsatiladigan qatorlar: nima qabul qilinmagani va nega
  («Bu maqsad uchun kunlik byudjet kamida $2 bo'lishi kerak.»), yoki targetolog tavsiyasi.
  Bo'sh bo'lishi mumkin.
- `ask` — kutilayotgan savol. `ready: true` bo'lsa `null`.
  - `options` — tugmalar. `recommended: true` bo'lganini birinchi va ajratib chizing
    (hozircha hech qachon `true` emas: targetolog ma'lumoti kiritilgach yoqiladi).
  - `opens: "form"` — bu tugma javob yubormaydi, kabinetning hozirgi «Lid formasi»
    dialogini ochadi (hozircha backend formani so'ramaydi; keyingi bosqichda keladi).
  - `input` — kiritish maydoni turi: `text`, `url`, `phone`, `money`, `none`
    (`none`: faqat tugmalar, lekin yozma javob ham qabul qilinadi).
  - `hint` — maydon ostidagi yordam matni (`Kamida $1`, `example.uz`).
- `chips` — aniqlangan narsalar, suhbat tepasida. `slot`: `kind`, `offer`, `goal`,
  `link`, `phone`, `channel`, `form`, `budget`.
- `ready` — savollar tugadi va `launch` ga saqlandi; davomi 5-bo'limda (`stage`).
- `stage` — reklama qayerda turgani: `asking`, `media`, `preparing`, `review`,
  `creating`, `done`, `failed` (5-bo'lim). Har doim keladi.
- `wait` — `true` bo'lsa backendda ish ketyapti: 3 soniyadan keyin `GET` qiling.
- `card` — tayyorlangan reklama qisqachasi: `stage: "review"` da, va tayyor reklamani
  Meta rad etgan `stage: "failed"` da. Boshqa payt `null`.
- `messages` — butun suhbat, eskisidan yangisiga (`author`: `user` yoki `agent`).
  Sahifa qayta ochilganda shundan chizing.
- `status` — `open`, `ready`, `closed`.

`ready` bo'lgandan keyin ham foydalanuvchi yozishi mumkin («byudjetni 10 qiling») —
sozlama yangilanadi va yana `ready` keladi.

### Sxema nomlari (`openapi.json`)

To'liq sxema `openapi.json` da (prodda `https://api.targetolog.ai/openapi.json`):

| Nima | Sxema nomi |
|---|---|
| Javob | `SessionOut` |
| `ask` | `LaunchChatAskOut` |
| `ask.options[]` | `LaunchChatOptionOut` (`opens`: `""`, `media`, `upload`, `review`, `form`) |
| `chips[]` | `LaunchChatChipOut` |
| `messages[]` | `LaunchChatMessageOut` |
| `card` | `LaunchChatCardOut` (`name`, `media_count`, `age_min`, `age_max`, `genders`, `interests`, `interests_more`, `adverts[]`) |
| `card.adverts[]` | `LaunchChatCardAdvertOut` (`primary_text`, `headline`) |
| `turns` so'rovi | `TurnIn` |
| `voice` javobi | `VoiceOut` |

## 3. Savollar tartibi

1. `kind` — biznes turi. Ikki ko'rinishda keladi:
   - tur umuman noma'lum: «Biznesingiz nima bilan shug'ullanadi?» — yozma javob;
   - turni AI sahifadan taxmin qilgan, hali hech kim tasdiqlamagan:
     «Biznesingiz: Ta'lim. To'g'rimi?» va ikki tugma — «Ha, to'g'ri»
     (`slot: "kind"`, `value: "yes"`) va «Yo'q, boshqa» (`value: "no"`). «Yo'q» dan
     keyin birinchi ko'rinishdagi savol keladi. Tugma o'rniga yozsa ham bo'ladi.
   Tur allaqachon tasdiqlangan bo'lsa, bu savol kelmaydi.
2. `offer` — hozir nimani reklama qilamiz.
3. `goal` — reklamadan nima kerak (tugmalar).
4. Maqsadning o'z savoli: `link` (sayt yoki Telegram), `phone`, `channel`.
5. `budget` — kunlik byudjet (tugmalar + yozish).

Bitta xabarda bir nechtasi aytilsa, ular so'ralmaydi. Hammasi aytilsa — darhol `ready`.

Biznes turi aniq bo'lgach `chips` da «Biznes: Ta'lim → ingliz tili kurslari»
ko'rinadi. Taxmin tasdiqlanmaguncha u `chips` da yo'q — faqat savolning o'zida.
Tur faqat ikki yo'l bilan tasdiqlanadi: «Ha, to'g'ri» bosilsa, yoki foydalanuvchi
biznesini o'z so'zi bilan aytib, savollarni oxirigacha javoblasa.

## 4. Xatolar

| Kod | HTTP | Ma'nosi |
|---|---|---|
| `launch_agent_session_not_found` | 404 | Suhbat yo'q yoki boshqa foydalanuvchiniki |
| `launch_agent_session_closed` | 409 | Yopilgan, yoki reklamasi allaqachon tayyorlangan: yangisini oching |
| `launch_agent_too_many_turns` | 429 | Bitta suhbatda 40 ta navbat tugadi |
| `launch_agent_daily_limit` | 429 | Kuniga 80 ta yozma xabar chegarasi; tugmalar ishlayveradi |
| `launch_agent_text_too_long` | 422 | Xabar 1000 belgidan uzun |

`POST …/sessions` mavjud «Reklama berish» ning o'z xatolarini ham qaytarishi mumkin
(obuna tugagan, sahifa tanlanmagan va h.k.) — ularni hozirgidek ko'rsating.

Tushunilmagan xabar xato emas: `lines` da «Buni tushunmadim, qaytadan yozib bering.»
keladi va o'sha savol qayta so'raladi.

## 5. Savollardan keyin: media, tayyorlash, ishga tushirish

`ready: true` bo'lgach suhbat shu yerning o'zida davom etadi. Qayerda turgani `stage`
da, u **reklamaning o'z holatidan** o'qiladi (eski sahifalarda qilingan o'zgarish ham
ko'rinadi):

| `stage` | Nima ko'rsatiladi | Front nima qiladi |
|---|---|---|
| `asking` | savollar (2–3-bo'lim) | — |
| `media` | `ask.slot = "media"`, ikki tugma: `opens: "media"` va `opens: "upload"` | Mavjud media tanlagichni oching (pastga qarang) |
| `preparing` | «Reklama tayyorlanmoqda…», `wait: true` | Har 3 soniyada `GET …/sessions/{id}` |
| `review` | `card` + «Ishga tushirish» va «Sozlamalarni ko'rish» | Kartani chizing |
| `creating` | «Reklama Meta'da yaratilmoqda…», `wait: true` | Har 3 soniyada `GET` |
| `done` | «Reklama yaratildi va yoqilmoqda…» | Suhbat yopiladi (`status: closed`) |
| `failed` | `ask.text` — sabab. Tayyorlash o'xshamagan bo'lsa: «Qayta urinish» (`slot: "prepare"`, `value: "retry"`). Tayyor reklamani Meta rad etgan bo'lsa: `card` + «Qayta ishga tushirish» (`slot: "launch"`, `value: "start"`) va «Sozlamalarni ko'rish» | Tugmalarni `ask.options` dan chizing |

Suhbat ochilganda (`POST …/sessions`) reklama allaqachon tayyorlangan bo'lsa (eski
sahifada yoki oldingi suhbatda), birinchi javobning o'zi shu bosqichni qaytaradi:
masalan `stage: "review"` va `card`. Savollar qaytadan so'ralmaydi.

Javobda yo'q tugma yuborilsa (masalan, eski xabardagi tugma), hech narsa bajarilmaydi
va `lines` da «Bu tugma hozir ishlamaydi. Quyidagilardan birini tanlang.» keladi.

### Media

1. `opens: "media"` — Instagram postlari va kutubxona: mavjud
   `GET /api/v1/launch/{launch_id}/media` ro'yxatini ko'rsating.
2. `opens: "upload"` — mavjud yuklash API lari
   (`POST /api/v1/launch/{launch_id}/media/upload…`).
3. Foydalanuvchi tanlab bo'lgach chatga:

```json
{"slot": "media", "value": "done", "asset_ids": ["…", "…"]}
```

`asset_ids` — tanlagichda belgilangan kutubxona fayllari (yuklangan fayllar o'zi
qo'shiladi, ularni yubormang). Hech narsa tanlanmagan bo'lsa `lines` da
«Avval kamida bitta post tanlang…» keladi va `stage` `media` da qoladi.
Reklama matni alohida so'ralmaydi: suhbatda aytilgan «nimani reklama qilamiz» javobi
ishlatiladi. Tanlangan postlarni chatda foydalanuvchi xabari sifatida ko'rsating.

### Karta (`card`, `review` da)

```json
{"name": "", "media_count": 2, "age_min": 18, "age_max": 35, "genders": ["Ayollar"],
 "interests": ["Ingliz tili", "IELTS"], "interests_more": 0,
 "adverts": [{"primary_text": "…", "headline": "…"}]}
```

Byudjet, maqsad va boshqalar `chips` da. To'liq sozlamalar va tahrirlash —
`opens: "review"` tugmasi: mavjud ko'rib chiqish sahifasini (`/api/v1/launch/{id}/review`)
oching. U yerda o'zgartirilgani chatga qaytganda ko'rinadi.

### Ishga tushirish

```json
{"slot": "launch", "value": "start"}
```

Bu **pul sarflaydigan yagona tugma** — mavjud «Yaratish» ning o'zi: reklama Meta'da
yaratiladi va o'zi yoqiladi. Rad etilsa (obuna, to'lov usuli, Meta tasdig'i va h.k.)
sababi `lines` da keladi, tugma joyida qoladi. Tasdiqlash oynasi backendda yo'q —
kerak bo'lsa frontda qo'ying.

`preparing` dan boshlab yozma xabar sozlamani o'zgartirmaydi: «Sozlamalar saqlangan…»
javobi keladi (AI chaqirilmaydi).

## 6. Biznes xotirasi

- **Keyingi safar:** biznes nima sotishi ma'lum bo'lsa, «Hozir nimani reklama qilamiz?»
  savoli ostida ular tugma bo'lib chiqadi (`ask.options`, `slot: "offer"`). Bosilsa
  AI chaqirilmaydi. Foydalanuvchi boshqa narsani yozishi ham mumkin.
- **Eslab qolish:** suhbatda bitta aniq mahsulot yoki xizmat aytilsa (nomi, bo'lsa narxi),
  u biznes bilimining kutish ro'yxatiga tushadi (`GET /api/v3/businesses/{id}/knowledge`
  dagi `pending`). Reklama yaratilgach (`stage: done`) o'zi tasdiqlanadi. Reklama
  yaratilmasa, kutishda qoladi — «Biznes» sahifasida tasdiqlash yoki rad etish mumkin.
- Front bu yerda hech narsa qilishi shart emas: hammasi backendda.

## 7. Ofisda joylashtirish (xodimlar sinovi)

- Kirish: ofis ichida alohida sahifa yoki tugma («Reklama chati — sinov»). Mijozlar
  kabinetida ko'rsatilmaydi.
- Xodim o'z kabineti nomidan ishlaydi: API lar oddiy foydalanuvchi tokeni bilan chaqiriladi,
  ya'ni xodimning o'z sahifasi va reklama akkaunti ishlatiladi.
- «Ishga tushirish» haqiqiy reklama yaratadi va yoqadi. Sinovda byudjetni minimal qo'ying
  va reklamani «Reklama» sahifasidan o'chiring.
- Bog'liq qo'llanma: `docs/FRONTEND_BIZNES_BILIMI.md` (biznes bilimi, «Eslab qolish» va
  «Tasdiqlash» tugmalari, setup o'zgarishi, ofisdagi tur tavsiyalari).

## 8. Hali yo'q

- Lid formasini chat ichida tanlash: hozircha AI tayyorlagan forma ishlatiladi,
  o'zgartirish — «Sozlamalarni ko'rish» orqali.

## 9. Ovozli xabar

Mikrofon tugmasi yozuvni matnga aylantiradi, lekin **xabarni o'zi yubormaydi**: matn
yozish maydoniga tushadi, foydalanuvchi o'qib, kerak bo'lsa tuzatib, odatdagidek
«Yuborish» ni bosadi (`turns` ga `text` bo'lib ketadi).

`POST /api/v3/launch-agent/sessions/{id}/voice` — `multipart/form-data`:

| Maydon | Nima |
|---|---|
| `file` | Yozuv: webm, ogg, m4a, mp3 yoki wav. 10 MB gacha |
| `language` | Ixtiyoriy: `uz`, `ru` yoki `en` (sayt tili). Bo'sh bo'lsa o'zi aniqlaydi |

Javob: `{"text": "Yozgi chegirma, kuniga 5 dollar", "language": "uzb"}`. Odatda 1–2
soniyada keladi; kutish paytida mikrofon o'rnida yuklanish belgisini ko'rsating.
`text` 1000 belgidan oshmaydi. Suhbat holati o'zgarmaydi, navbat sarflanmaydi.

| Kod | HTTP | Ma'nosi |
|---|---|---|
| `launch_agent_voice_off` | 503 | Ovoz sozlanmagan: mikrofonni yashiring yoki «yozib yuboring» deng |
| `launch_agent_voice_busy` | 503 | Hozir aylantirib bo'lmadi: qayta urinish mumkin |
| `launch_agent_voice_refused` | 422 | Faylni o'qib bo'lmadi |
| `launch_agent_voice_silent` | 422 | Yozuvda gap yo'q |
| `launch_agent_voice_too_big` | 413 | 10 MB dan katta |
| `launch_agent_voice_daily_limit` | 429 | Kuniga 60 ta ovozli xabar chegarasi |

Hamma xatoda `message` tayyor o'zbekcha matn — o'shani ko'rsating. Yozishni 2 daqiqa
bilan cheklang (brauzerda `MediaRecorder`, `audio/webm`).

## 10. Eski «Reklama berish» oynalaridan foydalanish

Chat eski «Reklama berish» ning o'sha `launch` ini to'ldiradi (`launch_id` har javobda
keladi), shuning uchun yangi oyna yozish shart emas: mavjud modal oynalarni shu
`launch_id` bilan oching. Chatning o'zida faqat suhbat, tugmalar, `chips` va karta
chiziladi.

| Chatda | Qaysi mavjud oyna | Uning API lari (o'zgarmagan) | Yopilgach chatga |
|---|---|---|---|
| `opens: "media"` | Media tanlagich (Instagram postlari, kutubxona) | `GET /api/v1/launch/{launch_id}/media` | `{"slot": "media", "value": "done", "asset_ids": […]}` |
| `opens: "upload"` | Fayl yuklash | `POST /api/v1/launch/{launch_id}/media/upload`, `…/upload/chunk`, `…/upload/finish` | `{"slot": "media", "value": "done"}` |
| `opens: "review"` | Ko'rib chiqish va tahrirlash (matn, auditoriya, byudjet, lid formasi) | `GET /api/v1/launch/{launch_id}/review`, `POST …/edit` va boshqalar | `GET …/sessions/{id}` — yangilangan `card` va `chips` |
| «Ishga tushirish» | Mavjud tasdiqlash oynasi (bo'lsa) | — | `{"slot": "launch", "value": "start"}` |

Qoidalar:

- Oyna ichidagi «Davom etish» / «Yaratish» tugmalari eski yo'llarni **chaqirmasin**
  (`POST /api/v1/launch/{id}/media`, `…/create`): bu qadamlarni chat o'zi bajaradi
  (yuqoridagi `turns` so'rovlari). Aks holda tayyorlash ikki marta so'raladi.
- Lid formasi alohida so'ralmaydi: AI tayyorlagani ishlatiladi. O'zgartirish kerak
  bo'lsa — ko'rib chiqish oynasidagi mavjud «Lid formasi» dialogi
  (`/api/v1/launch/{launch_id}/form…`).
- Oyna yopilgach har doim `GET …/sessions/{id}` qiling: `stage` reklamaning o'z
  holatidan o'qiladi, oynada qilingan o'zgarish shu yerda ko'rinadi.

