# Ishlab turgan reklamani tahrirlash — frontend uchun

Bu hujjat ishlab turgan reklamada Meta o'zgartirishga ruxsat bergan
sozlamalarni tahrirlash uchun backend'da qo'shilgan narsalarni
tushuntiradi. Har bosqich tugaganda shu hujjatga yangi bo'lim qo'shiladi.

**Umumiy qoidalar**
- Barcha manzillar `/api/v1` bilan boshlanadi, `Authorization: Bearer <token>` talab qiladi.
- `/campaigns/...` javoblari **camelCase**da. So'rovda camelCase ham, snake_case ham qabul qilinadi.
- Hech narsa buzilmagan: yangi maydonlar faqat **qo'shilgan**. Front ularni yubormasa, Meta'dagi qiymat boricha qoladi.
- API turlarini backenddan to'liq qayta generatsiya qilish **shart emas** (u `bridges/crm.ts` va `bridges/sales.ts` ni buzadi). Quyidagi turlarni qo'lda qo'shing.
- Qiymatlar, ro'yxatlar va qulf sabablari backenddan keladi. Frontda statik ro'yxat yoki standart qiymat yozilmaydi.

**Hujjat tuzilishi:** avval «Qanday ishlaydi» — hamma bosqichga umumiy
mexanizm (bir marta o'qiladi). Keyin har bosqich uchun API va ekran qoidalari.

---

## Qanday ishlaydi

### 0.1. Uch daraja va qaysi sozlama qayerda turadi

Meta'da reklama uch qavatdan iborat. Har sozlama faqat bitta qavatda turadi,
shuning uchun uni tahrirlaydigan yo'l ham o'sha qavatning id'sini oladi.

| Daraja | Bizda | Bu yerda turadigan sozlamalar |
|---|---|---|
| Kampaniya (`campaign`) | Ro'yxatdagi qator | Nom, sarf limiti, byudjet (agar CBO bo'lsa) |
| Guruh (`adset`) | Daraxtdagi ikkinchi qavat | Nom, byudjet (ABO), auditoriya, joylashuv, Advantage+ auditoriya, tugash sanasi, narx chegarasi, attribution, chastota |
| Reklama (`ad`) | Daraxtdagi uchinchi qavat | Nom, matn, sarlavha, tavsif, tugma, havola, UTM, rasm/video, karusel kartalari, lid forma, chat salomi |

Ikki xil id bor, ularni aralashtirmang:

- **bizning id** (UUID) — faqat kampaniyada: `/campaigns/{id}/edit`, `PATCH /campaigns/{id}`;
- **Meta id** (`externalId`, uzun raqam) — guruh va reklamada, hamda `/campaigns/manage/{level}/{externalId}/…` yo'llarida uchala daraja uchun.

Foydalanuvchi ko'pincha «kampaniyani tahrirlayman» deb o'ylaydi, lekin
auditoriya va joylashuv aslida **guruhniki**. Kampaniyada bitta guruh bo'lsa,
tahrir oynasi shu guruhni o'zi topadi. Bir nechta guruh bo'lsa, oyna
`?group=<guruh externalId>` bilan ochiladi; busiz guruhga tegishli bo'limlar
`null` keladi va chizilmaydi.

### 0.2. Bitta o'zgarishning yo'li

Hech bir o'zgarish Meta'ga so'rov ichida yuborilmaydi. Yo'l har doim bir xil:

```
foydalanuvchi «Saqlash»ni bosadi
   │
   ▼
backend tekshiradi ──► xato bo'lsa: 422 / 400 / 409 (hech narsa yozilmaydi)
   │
   ▼
o'zgarish tarixga «kutilmoqda» bo'lib yoziladi, javob darhol qaytadi:
ControlState { pending: true, action: { id, status: "pending" } }
   │
   ▼
orqa fondagi ishchi Meta'ga yuboradi (odatda 1–5 soniya)
   │
   ├─► Meta qabul qildi  → status: "applied", bazadagi nusxa yangilanadi
   └─► Meta rad etdi     → status: "failed", failure to'ldiriladi
```

Front javobni olgach, **o'sha obyektning holatini so'rab turadi**:

`GET /campaigns/manage/{level}/{externalId}/state?tries={oldingi javobdagi tries}`

- har `pollSeconds` soniyada (hozir 2), `pending: false` bo'lguncha;
- `tries`ni o'zingiz sanamang — har javobdagi `tries`ni keyingi so'rovga qaytaring;
- 15 urinishdan keyin backend `pending: false, stalled: true` qaytaradi: so'rashni to'xtating.

Bu mexanizm yangi emas — to'xtatish/yoqish va byudjet shu bilan ishlaydi.
Yangi imkoniyatlarning hammasi shu `ControlState`ni qaytaradi, shuning uchun
mavjud holat satri (status line) komponentini qayta ishlating.

```ts
type ControlState = {
  level: "campaign" | "adset" | "ad";
  externalId: string;
  pending: boolean;        // hali yo'lda: yana so'rang
  stalled: boolean;        // uzoq cho'zildi: so'rashni to'xtating
  failure: {               // Meta rad etgan bo'lsa
    text: string;
    fix: { label: string; url: string } | null;
    explanationHtml: string | null;
    explaining: boolean | null;
  } | null;
  action: { id: string; status: string; dryRun: boolean; revertible: boolean } | null;
  tries: number;
  pollSeconds: number;
  refused: string | null;  // umuman yuborilmadi: sababi
  gone: boolean | null;    // obyekt o'chirilgan
  notes: string[];         // backend o'zi moslagan narsalar
};
```

### 0.3. Natija holatlari va nima ko'rsatiladi

| Holat | Qanday taniladi | Foydalanuvchiga |
|---|---|---|
| Yo'lda | `pending: true` | Spinner, «Saqlanmoqda…». Shu obyektning boshqaruvlari vaqtincha o'chiriladi. |
| Bajarildi | `pending: false`, `failure: null`, `action.status: "applied"` | «Saqlandi». Formani **qaytadan o'qing** (`GET …/edit`) — Meta ba'zi qiymatni o'zgartirgan bo'lishi mumkin. `notes` bo'lsa ko'rsating. |
| Meta rad etdi | `failure` to'la | `failure.text`ni ko'rsating. `fix` bo'lsa — tugma (`label`, `url`). `explaining: true` — AI tushuntirish yozmoqda, yana so'rang; tayyor bo'lgach `explanationHtml` keladi. |
| Cho'zildi | `stalled: true` | «Hali tugamadi, birozdan keyin sahifani yangilang». Xato emas: o'zgarish keyinroq bajarilishi mumkin. |
| Yuborilmadi | `refused` to'la | Matnni ko'rsating. Meta'ga hech narsa ketmagan. |
| Obyekt yo'q | `gone: true` | Qatorni ro'yxatdan olib tashlang. |

Muhim: **«bajarildi» degani Meta qabul qildi degani**, reklama darhol shu
ko'rinishda ishlay boshladi degani emas. Ayrim o'zgarishlardan keyin Meta
reklamani qayta ko'rikdan o'tkazadi (0.6-bandga qarang).

### 0.4. Saqlashdan oldingi xatolar

Uch xil shakl bor, har biri boshqa joyda ko'rsatiladi:

| Kod | Tana | Ma'nosi | Qayerda ko'rsatiladi |
|---|---|---|---|
| `422` | `problems: { maydon: "matn" }` | Maydon noto'g'ri to'ldirilgan | O'sha maydon ostida |
| `400` | `detail: "matn"`, `code: "…"` | Bu o'zgarish shu reklamaga qo'llanmaydi yoki hech narsa o'zgarmagan | Toast yoki bo'lim ostida. `code`ga qarab mantiq yozish mumkin, matnni esa `detail`dan oling |
| `409` | `detail`, `code: "refused"`, ba'zan `problems` | Qoida ruxsat bermadi (masalan o'rganish davri) | Toast; `problems` bo'lsa maydon ostida |
| `204` | bo'sh | Forma o'zgarmagan holda saqlandi | Oynani jimgina yoping |

Ayrim yo'llar (to'xtatish/yoqish, byudjet) qoidaning rad javobini xato kodi
bilan emas, `200` va `ControlState.refused` ichida qaytaradi. Shuning uchun
har javobda **ikkalasini** tekshiring: HTTP kodi va `refused`.

Matnlar foydalanuvchi tilida keladi. Frontda xato matni yozilmaydi.

### 0.5. «Yuborilmagan», `null` va «o'zgarmagan»

Bu qoida hamma yangi maydonlarga tegishli va eng ko'p xato shu yerda chiqadi:

| Front nima yubordi | Backend nima qiladi |
|---|---|
| Maydon tanada **yo'q** | Tegmaydi. Meta'dagi qiymat qoladi. |
| Maydon hozirgi qiymati bilan | O'zgarish deb hisoblamaydi. |
| Maydon yangi qiymat bilan | O'zgartiradi. |
| Maydon aniq `null` (`endsAt`, `limit`, `costCap`, `frequency`) | Sozlamani **olib tashlaydi**. |
| Bo'sh satr `""` (`urlTags`, karta `headline`/`description`) | Qiymatni **tozalaydi**. |

Shundan ikki amaliy xulosa:

1. Forma holatida `undefined` (tegilmagan) va `null` (olib tashlandi)ni alohida saqlang. JSON'ga aylantirishda tegilmagan maydonni tanadan olib tashlang.
2. Backend qiymatni o'qiy olmagan bo'lsa (`urlTags.value: null`, `readable: false`), o'sha maydonni bo'sh ko'rsatmang va yubormang — aks holda foydalanuvchi bilmagan holda sozlamani o'chirib yuboradi.

### 0.6. Meta nimaga ruxsat beradi va oqibati nima

| O'zgarish | Meta'da nima bo'ladi | Foydalanuvchiga aytiladigan oqibat |
|---|---|---|
| Nom (uchala daraja) | Faqat yozuv | Hech qanday. O'rganish davrida ham ochiq. |
| Byudjet | Guruh sozlamasi yangilanadi | Katta o'zgarish o'rganishni qayta boshlashi mumkin (ogohlantirish, to'smaydi). |
| Tugash sanasi, sarf limiti | Yangilanadi yoki olib tashlanadi | Hech qanday. |
| Auditoriya, joylashuv, Advantage+ | Guruh targetingi **butunlay almashtiriladi** | O'rganish qaytadan boshlanadi. O'rganish davrida yopiq. |
| Narx chegarasi, attribution, chastota | Guruh sozlamasi yangilanadi | O'rganishni qayta boshlaydi (ogohlantirish, to'smaydi). |
| Matn, sarlavha, tugma, havola, UTM, karta, rasm/video, forma, chat salomi | **Yangi kreativ** yaratiladi | Qayta ko'rik. 0.7-bandga qarang. |

O'zgartirib **bo'lmaydi** (Meta ruxsat bermaydi, bizda ham yo'q):

- kampaniya maqsadi;
- byudjet qayerda turishi (kampaniyadami, guruhdami) va uning turi (kunlik ↔ butun muddatga);
- maxsus toifa belgisi;
- nashr qilingan lid formaning savollari (o'rniga nusxa olib yangi forma — 2.7-band);
- post asosida qilingan reklamaning matni va tugmasi (`canSwap: false`).

Bunday holatda yo'l bitta: nusxa olish yoki yangi reklama ishga tushirish.

### 0.7. Kreativ o'zgarmas — reklama tahririning asosiy g'oyasi

Meta'da reklama ko'rinishi (kreativ) yaratilgach **o'zgarmaydi**. Shuning uchun
«matnni tuzatish» aslida: eski kreativdan nusxa → o'zgargan maydon qo'yiladi →
yangi kreativ yaratiladi → u reklamaga ulanadi. Bu ulash ikki xil bo'ladi va
foydalanuvchi tanlaydi (`inPlace`):

| | `inPlace: false` (standart) | `inPlace: true` |
|---|---|---|
| Nima bo'ladi | Yangi reklama ochiladi, eskisi to'xtatiladi | O'sha reklamaning kreativi almashtiriladi |
| Reklama id'si | Yangi | O'sha |
| Layk, izoh, ulashishlar | Eski reklamada qoladi, yangisi noldan | Noldan boshlanadi |
| Statistika | Eskisi alohida saqlanadi, solishtirish mumkin | Bir qatorda davom etadi |
| Ko'rik | Yangi reklama ko'rikdan o'tadi | Shu reklama qayta ko'rikdan o'tadi, o'tguncha ko'rsatilmaydi |
| Orqaga qaytish | Eskisini yoqib, yangisini to'xtatish | Yo'q |

Front buni saqlashdan oldin aytishi kerak: tugma, havola, UTM, karta
o'zgarishi ham matn o'zgarishi bilan **bir xil** oqibatga ega. Bir saqlashda
bir nechta maydon o'zgarsa, bitta yangi kreativ yaratiladi (har maydonga
alohida emas) — shuning uchun maydonlarni bitta «Saqlash» ostiga yig'ing.

`inPlace: false`dan keyin daraxtda yangi qator paydo bo'ladi: ro'yxatni
qaytadan o'qing.

### 0.8. Qulflar

Qulf doim backenddan keladi (`open`, `locks`, `canChange`, `note`). Front
holatni o'zi hisoblamaydi.

| Sabab | Nima yopiladi | Nima ochiq qoladi |
|---|---|---|
| **O'rganish davri** (`"learning"`) — guruh yangi yoki yaqinda jiddiy o'zgargan, Meta kimga ko'rsatishni o'rganmoqda | Auditoriya, joylashuv, Advantage+, reklama tahriri | Nom, byudjet (ogohlantirish bilan), narx chegarasi/attribution/chastota (ogohlantirish bilan), to'xtatish/yoqish |
| **Kampaniya tugagan** (`"closed"` / `"ended"`) | Hammasi | Nusxa olish |
| **Reklama turi** | Shu turga to'g'ri kelmaydigan sozlama (`offered: false`, `appsOffered: []`, `buttons` bitta) | Qolgani |
| **Rad etilgan reklama** | — | Reklama tahriri o'rganish davrida ham ochiq (tuzatish uchun) |

Yopiq bo'limni yashirmang: o'chirilgan holda chizing va `note`ni ko'rsating —
foydalanuvchi sozlama borligini va nega hozir yopiqligini bilishi kerak.
Faqat `offered: false` / `null` bo'limlar umuman chizilmaydi (bu reklamaga
tegishli emas).

### 0.9. Tarix va «Qaytarish»

- Har o'zgarish tarixga yoziladi: `GET /campaigns/{id}/history` — `text`, `at`, `by`, `status`, `level`.
- `ControlState.action.revertible: true` bo'lsa, «Qaytarish» tugmasini chizing:
  `POST /campaigns/manage/{level}/{externalId}/revert` tanasi `{ "log": "<action.id>" }`.
- «Qaytarish» ham oddiy o'zgarish: o'sha yo'ldan o'tadi, `ControlState` qaytaradi, tarixga yoziladi.

| O'zgarish | Qaytariladimi |
|---|---|
| Nom, byudjet, tugash sanasi, sarf limiti | Ha — avvalgi qiymat (yoki «yo'q» holati) tiklanadi |
| Auditoriya, joylashuv, Advantage+ | Ha — avvalgi targeting aynan tiklanadi |
| Narx chegarasi, attribution, chastota | Ha |
| Reklama tahriri (kreativ) | **Yo'q.** `inPlace: false`da eski reklama to'xtatilgan holda turadi — uni yoqish mumkin |

### 0.10. Qiymatlar qayerdan o'qiladi

| Manba | Qaysi maydonlar | Front uchun oqibat |
|---|---|---|
| Bizning bazadagi nusxa (Meta bilan vaqti-vaqti bilan tenglashtiriladi) | Nom, byudjet, auditoriya, joylashuv, tugash sanasi, matn, tugma, havola, kartalar | Tez, doim keladi. Ads Manager'da hozirgina qilingan o'zgarish bir necha daqiqa kechikishi mumkin. |
| Meta'dan shu so'rov paytida | `urlTags.value`, butun `…/delivery` formasi | Sekinroq (0.5–2 s), **kelmasligi mumkin** (`null` / `readable: false`). Bo'lim ochilganda so'rang, skeleton ko'rsating, «qayta urinish» qo'ying. |

### 0.11. AI chat bilan bog'liqligi

AI chat alohida mexanizm emas. Chatdagi tasdiqlash tugmasi bosilganda o'sha
0.2-banddagi yo'l ishlaydi: o'sha tekshiruvlar, o'sha tarix, o'sha «Qaytarish».
Farqi faqat kim to'ldirgani: formani foydalanuvchi emas, AI to'ldiradi va
foydalanuvchi `before → after`ni ko'rib tasdiqlaydi. Shuning uchun chatda
bajarilgan o'zgarish Reklama sahifasida ham darhol ko'rinishi kerak — tugma
bosilgach kampaniya ma'lumotlarini yangilang (query invalidation).

### 0.12. Ekranlar xaritasi

| Ekran (front) | Nima qo'shiladi | Bo'lim |
|---|---|---|
| Tahrir oynasi, auditoriya bo'limi (`EditSheet.tsx`) | Joylashuv, Advantage+ auditoriya | 1-bosqich |
| Tahrir oynasi, yangi «Kengaytirilgan» bo'limi | Narx chegarasi, attribution, chastota | 3-bosqich |
| Tahrir oynasi, muddat va limit | «Tugash sanasiz», limitni olib tashlash | 4-bosqich |
| Reklama tahriri (`AdEdit.tsx`) | Tugma, havola, UTM, karusel kartalari, shablon, formadan nusxa | 2-bosqich |
| Daraxt va Expert jadvali (`Tree.tsx`, `Manager.tsx`) | Guruh va reklama nomini joyida tahrirlash | 4-bosqich |
| AI chat | Yangi turdagi tasdiqlash tugmalari | 6-bosqich |

Tavsiya etilgan qurish tartibi: 4 (eng kichik, mexanizmni sinab olish uchun)
→ 1 → 2 → 3 → 6.

### 0.13. Hozirgi holat

- Backend production'da. Barcha o'zgarishlar **qo'shimcha**: front hech narsa qilmasa, eski ekranlar avvalgidek ishlaydi.
- Bazada o'zgarish yo'q.
- Har bosqich oxiridagi «Hali tekshirilmagan» ro'yxatidagi narsalar real Meta'da hali sinalmagan. Sinov natijasi chiqquncha yangi bo'limlarni foydalanuvchilarga ochmang (flag ostida quring).
- `action.dryRun: true` — sinov muhiti: o'zgarish Meta'ga yuborilmagan, faqat tarixga yozilgan. Bunda holat satrida «sinov» belgisini ko'rsating.

---

## 1-bosqich. Joylashuvlar va Advantage+ auditoriya

Ikkalasi mavjud tahrir oynasiga (`C/EditSheet.tsx`, auditoriya bo'limi) qo'shiladi.
Yangi yo'l yo'q: o'sha `GET /campaigns/{id}/edit` va `PATCH /campaigns/{id}`.

### 1.1. Formada yangi ikki maydon

`GET /campaigns/{id}/edit[?group=<adset id>]` javobiga qo'shildi:

```json
{
  "placement": {
    "apps": "instagram",
    "appsOffered": ["auto", "instagram", "facebook", "fbig"],
    "positions": {
      "instagram": ["stream", "story"],
      "facebook": ["feed", "story", "facebook_reels"]
    },
    "positionOptions": {
      "instagram": [
        { "value": "stream", "label": "Instagram lentasi", "needs": [] },
        { "value": "profile_feed", "label": "Instagram profil lentasi", "needs": ["instagram.stream"] }
      ],
      "facebook": [
        { "value": "story", "label": "Facebook Stories", "needs": ["facebook.feed", "instagram.story"] }
      ]
    },
    "open": true,
    "note": "",
    "warnings": {}
  },
  "advantage": { "on": true, "open": true, "ageMinCap": 25, "note": "" }
}
```

Ikkalasi ham `null` bo'lishi mumkin: oyna bitta guruhning auditoriyasiga
yetmaganda (bo'lingan kampaniya `?group`siz ochilganda). Bunda bo'limlar chizilmaydi.

```ts
type ShownApps = "auto" | "fbig" | "instagram" | "facebook";
type ShownPosition = { value: string; label: string; needs: string[] };
type EditPlacement = {
  apps: ShownApps | "other";
  appsOffered: ShownApps[];
  positions: { instagram: string[]; facebook: string[] };
  positionOptions: { instagram: ShownPosition[]; facebook: ShownPosition[] };
  open: boolean;
  note: string;
  warnings: Partial<Record<ShownApps, string>>;
};
type EditAdvantage = { on: boolean; open: boolean; ageMinCap: number; note: string };
```

### 1.2. `placement` — reklama qayerda ko'rsatiladi

Shakli ishga tushirish tahrirchisidagi bilan bir xil (`L/EditApps.tsx`):
`apps`, `positions`, `positionOptions` nomlari va ma'nosi o'sha. Shu
komponentni qayta ishlatish mumkin.

| Maydon | Ma'nosi |
|---|---|
| `apps` | Hozirgi tanlov. `auto` — Meta o'zi tanlaydi; `fbig` — Facebook va Instagram; `instagram`; `facebook`. `other` — Ads Manager'da qo'yilgan, bizning to'rttamizdan hech biriga to'g'ri kelmaydigan aralashma (masalan Messenger bilan). |
| `appsOffered` | Shu reklamaga ruxsat etilgan tanlovlar. Faqat shularni chizing. Bo'sh bo'lsa — tanlov qotirilgan. |
| `positions` | Har ilovaning belgilangan joylari. Ishlamayotgan ilova uchun ham keladi: foydalanuvchi shu ilovaga o'tsa, boshlang'ich belgilar shu. |
| `positionOptions` | Har ilovada belgilash mumkin bo'lgan joylar. `needs` — bu joy yolg'iz ishlamaydi, sanalganlardan kamida biri ham belgilangan bo'lishi kerak (`ilova.joy` ko'rinishida). |
| `open` | `false` — bo'lim ko'rsatiladi, lekin o'zgartirib bo'lmaydi. Sababi `note`da. |
| `note` | Nega yopiq. Bo'lim ostida shu matnni ko'rsating. |
| `warnings` | Tanlovga qarab ogohlantirish: `warnings[tanlov]` bor bo'lsa, foydalanuvchi shu tanlovni bosganda ostida ko'rsating. To'smaydi, faqat aytadi. |

`apps` qiymatlari bo'yicha chizish:
- `auto` — joylar ro'yxati chizilmaydi (Meta o'zi tanlaydi).
- `fbig` — ikkala ilovaning joylari.
- `instagram` / `facebook` — faqat o'sha ilovaning joylari.
- `other` — to'rt tanlovdan hech biri belgilanmagan holda chizing va «Ads Manager'da sozlangan» deb yozing. Foydalanuvchi to'rttadan birini tanlasa, aralashma o'sha tanlov bilan almashtiriladi.

`appsOffered` qachon torayadi:
- **Profilga o'tish reklamasi** — `[]`, `open: false`. Reklama faqat Instagram'da ishlaydi.
- **Messenger'da suhbat** — `instagram` yo'q.
- **Instagram Direct'da suhbat** — `facebook` yo'q.

`warnings` hozir bitta holatda keladi: **lid formali reklamada `instagram`**
tanlovi uchun («Faqat Instagram'da qo'yilgan lid reklamalarining ko'pi umuman
ko'rsatilmagan…»).

### 1.3. `advantage` — Advantage+ auditoriya

Meta auditoriyani o'zi kengaytirishi. Bitta tugma (switch).

| Maydon | Ma'nosi |
|---|---|
| `on` | Hozir yoqilganmi. |
| `open` | `false` — tugma o'chirilgan holda chiziladi, sababi `note`da. Maxsus toifadagi reklamada (uy-joy, ish, moliya) doim `false`. |
| `ageMinCap` | Yoqilganda «yosh … dan» shu qiymatdan katta bo'la olmaydi va yuqori yosh yuborilmaydi. |
| `note` | Nega yopiq. |

Foydalanuvchi tugmani **yoqsa**, formani darhol shunga moslang:
- «gacha» (yuqori yosh) maydonini yashiring;
- «dan» qiymati `ageMinCap`dan katta bo'lsa, `ageMinCap`ga tushiring;
- jins va o'z auditoriyalari ostida «Meta buni tavsiya sifatida oladi» deb yozing.

Front moslamasa ham xato bo'lmaydi: backend o'zi moslaydi va javobda
`notes: ["Avtomatik auditoriya qoidasi bilan moslandi."]` qaytaradi. Shu
matnni saqlangandan keyin ko'rsating.

### 1.4. Saqlash

`PATCH /campaigns/{id}` tanasiga uchta **ixtiyoriy** maydon qo'shildi:

```json
{
  "dailyBudget": 10, "ageMin": 25, "ageMax": 45, "gender": "all", "audienceIds": [],
  "apps": "fbig",
  "positions": { "instagram": ["stream", "reels"], "facebook": ["feed"] },
  "advantage": true
}
```

| Maydon | Qoida |
|---|---|
| `apps` | `appsOffered`dagi qiymatlardan biri. Yuborilmasa — o'zgarmaydi. |
| `positions` | Faqat tanlangan `apps`ning ilovalari hisobga olinadi. Ilova yuborilmasa, uning joylari boricha qoladi. `auto`da e'tiborga olinmaydi. |
| `advantage` | `true` / `false`. Yuborilmasa — o'zgarmaydi. |

Formadagi boshqa maydonlar kabi: front ko'rsatgan qiymatni o'zgarmagan holda
qaytarsa, backend buni o'zgarish deb hisoblamaydi. Hech narsa o'zgarmagan
bo'lsa — `204`.

**Javob:** `ControlState` (odatdagidek `pending` / `pollSeconds` bilan kuzatiladi),
ichida `notes` — backend o'zi moslagan narsalar matni.

**Xatolar** (`422`, `problems: {maydon: "matn"}` — matnni shu maydon ostida ko'rsating):

| `problems` kaliti | Qachon |
|---|---|
| `positions` | Ilovada hech narsa belgilanmagan; ro'yxatda yo'q joy; yolg'iz ishlamaydigan joy (matnda qaysi joy kerakligi aytiladi). |
| `apps` | `appsOffered`da yo'q tanlov yuborilgan. |

`open: false` bo'lgan bo'limning maydoni yuborilsa, xato chiqmaydi — u
shunchaki e'tiborga olinmaydi (boshqa qulflangan maydonlar kabi).

### 1.5. Qulflar

Ikkala sozlama ham auditoriyaning qolgan qismi bilan bir qoidada:

| Holat | `placement.open` / `advantage.open` | `note` |
|---|---|---|
| Guruh o'rganish davrida | `false` | «Reklama o'rganish davrida: bu sozlamani o'rganish tugagach o'zgartirasiz.» |
| Kampaniya tugagan | `false` | «Reklama tugagan: bu sozlama endi o'zgarmaydi.» |
| Profilga o'tish reklamasi | `placement.open: false` | Instagram haqidagi matn |
| Maxsus toifa | `advantage.open: false` | Maxsus toifa haqidagi matn |

Mavjud `locks.audience` (`"learning"` / `"closed"` / `null`) o'zgarmagan va
shu ikki sozlamaga ham tegishli.

### 1.6. Qaytarish va tarix

- O'zgarish auditoriya o'zgarishi sifatida yoziladi, shuning uchun mavjud
  **«Qaytarish»** tugmasi (`POST /campaigns/manage/adset/{id}/revert`) uni ham
  qaytaradi: avvalgi joylashuv va avvalgi tugma holati aynan tiklanadi.
- Meta biror joyni qabul qilmay tashlab yuborsa (masalan maqsadga to'g'ri
  kelmaydigan joy), o'zgarish baribir «bajarildi» bo'ladi. Keyingi
  `GET .../edit` Meta'da qolgan joylarni ko'rsatadi, tarixda esa
  `dropped: {"instagram_positions": ["ig_search"]}` yoziladi.

### 1.7. Tekshirish ro'yxati (front)

- [ ] `placement` / `advantage` `null` bo'lganda bo'lim chizilmaydi.
- [ ] Faqat `appsOffered`dagi tanlovlar chiziladi.
- [ ] `needs`i bajarilmagan joy belgilanganda saqlashdan oldin ogohlantiriladi (backend baribir `422` qaytaradi).
- [ ] `warnings[tanlov]` tanlov bosilganda ko'rinadi.
- [ ] Advantage+ yoqilganda yosh maydonlari moslanadi.
- [ ] `open: false`da `note` ko'rinadi, boshqaruv o'chirilgan.
- [ ] Saqlangandan keyin `notes` ko'rsatiladi.

### Hali tekshirilmagan

Bu bosqich soxta Meta javoblari bilan testlangan. **Real Meta'da sinalmagan**:
ishlab turgan guruhda joylashuvni almashtirish va Advantage+ tugmasini
o'zgartirish. 5-bosqichda bitta to'xtatilgan reklamada sinaladi.

---

## 2-bosqich. Reklamaning o'zi: tugma, havola, UTM, karusel, shablon, forma

Hammasi mavjud reklama tahriri sahifasiga (`C/AdEdit.tsx`) qo'shiladi.
Yangi yo'l yo'q: o'sha `GET /campaigns/ads/{id}/edit` va `POST /campaigns/ads/{id}/edit`.

**Esda tuting:** Meta kreativni tahrirlashga ruxsat bermaydi. Quyidagi har bir
o'zgarish yangi kreativ yaratadi, shuning uchun mavjud `inPlace` qoidasi
shularga ham tegishli (`false` — yangi reklama ochilib eskisi to'xtaydi;
`true` — shu reklama qayta ko'rikdan o'tadi, layk va izohlar noldan boshlanadi).

### 2.1. Formada yangi maydonlar

`GET /campaigns/ads/{id}/edit` javobiga qo'shildi:

```json
{
  "button": "LEARN_MORE",
  "buttons": [
    { "key": "LEARN_MORE", "label": "Batafsil" },
    { "key": "SHOP_NOW", "label": "Xarid qilish" }
  ],
  "link": "https://tort.uz",
  "urlTags": {
    "value": "utm_source=meta&utm_medium=cpc",
    "suggested": "utm_source={{site_source_name}}&utm_medium=paid_social&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{adset.id}}",
    "maxChars": 1000
  },
  "cards": [
    { "source": 0, "headline": "Asal", "description": "", "thumb": "https://…", "isVideo": false }
  ],
  "cardLimits": { "min": 2, "max": 10, "headline": 255, "description": 255 },
  "welcomeTemplates": [
    { "id": "…", "name": "Bahor", "text": "Salom!", "questions": [{ "title": "Narxi?", "response": "100 ming" }] }
  ],
  "forms": { "currentId": "123", "currentName": "Forma", "currentQuestions": ["Qaysi tort?"], "options": [] }
}
```

```ts
type ButtonChoice = { key: string; label: string };
type AdCard = { source: number; headline: string; description: string; thumb: string | null; isVideo: boolean };
type AdEditExtra = {
  button: string;
  buttons: ButtonChoice[];
  link: string | null;
  urlTags: { value: string | null; suggested: string; maxChars: number } | null;
  cards: AdCard[] | null;
  cardLimits: { min: number; max: number; headline: number; description: number } | null;
  welcomeTemplates: { id: string; name: string; text: string; questions: { title: string; response: string }[] }[];
};
// forms ichiga qo'shildi: currentId: string; currentQuestions: string[]
```

Qaysi reklamada nima keladi:

| Reklama turi | `buttons` | `link` | `urlTags` | `cards` | `welcomeTemplates` |
|---|---|---|---|---|---|
| Saytga olib boradigan | bir nechta | manzil | bor | karusel bo'lsa | `[]` |
| Lid formali | bir nechta | `null` | `null` | karusel bo'lsa | `[]` |
| Suhbat (Messenger / Direct) | bitta (o'zi) | `null` | `null` | — | sahifaning shablonlari |
| Qo'ng'iroq, profilga o'tish | bitta (o'zi) | `null` | `null` | — | `[]` |
| Post asosidagi (`canSwap: false`) | `[]` | `null` | `null` | `null` | `[]` |

`null` yoki bitta elementli ro'yxat — o'sha bo'limni **chizmang** (tanlov yo'q).

### 2.2. Tugma (CTA)

- `buttons` — tugmaga qo'yish mumkin bo'lgan so'zlar, birinchisi hozirgisi. `label`ni ko'rsating, `key`ni yuboring.
- Tugma qayerga olib borishi o'zgarmaydi (o'sha sayt yoki o'sha forma), faqat so'zi.
- Nusxa olish oynasidagi (`CopyDialog.tsx`) `button` / `buttons` bilan bir xil shakl.

### 2.3. Havola

- `link` — reklama olib boradigan sayt. Faqat saytga olib boradigan reklamada keladi.
- Yangi manzil `https://`siz yozilsa ham qabul qilinadi (backend qo'shadi).
- Facebook yoki Instagram manzili rad etiladi («o'z saytingiz kerak»).
- Karuselda asosiy manzil o'zgarsa, o'sha manzilga olib borgan kartalar ham ko'chadi; o'z manzili bor karta o'zida qoladi.

### 2.4. UTM (`urlTags`)

- `value` — reklamada hozir turgan parametrlar. Bu qiymat **Meta'dan shu so'rov paytida o'qiladi**:
  - `""` — parametr yo'q;
  - `null` — Meta javob bermadi. Maydonni bo'sh ko'rsatmang: «hozirgi qiymatni o'qib bo'lmadi» deb yozing va foydalanuvchi o'zgartirmasa `urlTags`ni **yubormang**.
- `suggested` — tizimning standart parametrlari. «Standartini qo'yish» tugmasi shu matnni maydonga yozadi.
- Format: `nom=qiymat&nom=qiymat`. Boshidagi `?` yoki `&` olib tashlanadi. Bo'sh joy, `#` bo'lsa rad etiladi.
- Bo'sh satr yuborilsa — parametrlar **olib tashlanadi**.

Muhim tuzatish (front ishi kerak emas): avval reklama matni tahrirlanganda,
nusxa olinganda yoki yangi reklama qo'shilganda UTM yo'qolib qolardi. Endi
foydalanuvchi o'zgartirmasa, eski parametrlar yangi kreativga ko'chiriladi.

### 2.5. Karusel kartalari

- `cards` — faqat karusel reklamada. Har kartada `source` — uning hozirgi o'rni.
- Saqlashda kartalarni **kerakli tartibda** yuboring:

```json
"cards": [
  { "source": 1, "headline": "Napoleon 20%" },
  { "source": 0 },
  { "headline": "Medovik", "picture": "<kutubxonadagi rasm id>" }
]
```

| Maydon | Qoida |
|---|---|
| `source` | Mavjud kartaning `source`i. Yuborilmasa — bu **yangi karta**. Ro'yxatda bo'lmagan `source` — karta **olib tashlandi**. |
| `headline`, `description` | Yuborilmasa — kartaniki qoladi. `""` — olib tashlanadi. |
| `picture` | `library`dagi **rasm** id (video emas). Yangi kartada majburiy. Mavjud kartada yuborilsa — rasmi almashadi (video karta ham rasmga aylanadi). |

- Kartalar soni `cardLimits.min`–`cardLimits.max` oralig'ida.
- Yangi karta birinchi kartaning manzili va tugmasini oladi.
- `isVideo: true` karta ko'chiriladi, so'zi o'zgaradi, lekin yangi video qo'yib bo'lmaydi.
- Kartalar yuborilmasa (`cards` yo'q) — o'zgarmaydi.

### 2.6. Suhbat shabloni

- `welcomeTemplates` — shu reklama sahifasi uchun saqlangan shablonlar (yaratish bosqichidagi «Shablon qilib saqlash»dan).
- Bu faqat **o'qish uchun**: foydalanuvchi shablonni tanlasa, front uning `text` va `questions`ini mavjud `welcome` maydonlariga yozadi va odatdagidek saqlaydi (`welcome: { text, questions }`).
- Yangi shablon saqlash va o'chirish yaratish bosqichida qoladi.

### 2.7. Formadan nusxa olib tahrirlash

Meta nashr qilingan formani o'zgartirtirmaydi, shuning uchun «tahrirlash» —
yangi forma yaratib, reklamani unga o'tkazish.

1. «Shu formadan nusxa» bosilganda front yangi forma oynasini `forms.currentQuestions` bilan to'ldiradi (boshqa formadan bo'lsa — `forms.options[].questions`).
2. Foydalanuvchi savollarni o'zgartiradi → mavjud `POST /campaigns/ads/{id}/forms` (`{ name, questions }`) → javobda yangi forma `id`.
3. Shu `id` mavjud `leadForm` maydoni bilan saqlanadi.

`currentQuestions`da faqat **o'z savollari** bor: ism va telefon yangi formaga
o'zi qo'shiladi, ularni qayta yubormang.

### 2.8. Saqlash

`POST /campaigns/ads/{id}/edit` tanasiga to'rtta **ixtiyoriy** maydon qo'shildi:

```json
{
  "message": "…", "headline": "…", "description": "…", "inPlace": false,
  "button": "SHOP_NOW",
  "link": "https://tort.uz/menyu",
  "urlTags": "utm_source=meta&utm_medium=cpc",
  "cards": [{ "source": 0 }, { "source": 1 }]
}
```

Yuborilmagan maydon o'zgarmaydi. Hozirgi qiymat o'zgarmagan holda qaytarilsa
ham o'zgarish deb hisoblanmaydi.

**Javob:** `ControlState`, odatdagidek kuzatiladi.

**Xatolar:**

| Kod | Javob | Qachon |
|---|---|---|
| `422` | `problems.link` | Manzil sayt emas, yoki Facebook/Instagram manzili. |
| `422` | `problems.cards` | Kartaga kutubxonada yo'q rasm yoki video tanlangan. |
| `400` | `detail` + `code` | `button_not_offered` — tugma `buttons`da yo'q · `link_not_offered` — reklama saytga olib bormaydi · `url_tags_unusable` — parametr formati noto'g'ri · `cards_not_offered` — karusel emas · `cards_refused` — kartalar soni yoki rasmsiz yangi karta · `nothing_changed` — hech narsa o'zgarmagan. |

`detail` matnini toast yoki tegishli maydon ostida ko'rsating.

### 2.9. Qulflar

Mavjud qoidalar o'zgarmagan: guruh o'rganish davrida bo'lsa reklama tahriri
yopiq (rad etilgan reklama bundan mustasno), tugagan kampaniyada yopiq.
Reklama tahriri «Qaytarish» bilan qaytarilmaydi (avvalgidek).

### 2.10. Tekshirish ro'yxati (front)

- [ ] `buttons` bittadan ko'p bo'lsagina tugma tanlovi chiziladi.
- [ ] `link` / `urlTags` `null` bo'lsa bo'lim chizilmaydi.
- [ ] `urlTags.value === null`da maydon bo'sh ko'rsatilmaydi va o'zgartirilmasa yuborilmaydi.
- [ ] Kartalarni sudrab tartiblash, o'chirish, qo'shish; `cardLimits` chegaralari.
- [ ] Yangi kartada faqat rasm tanlanadi.
- [ ] Shablon tanlansa `welcome` maydonlari to'ladi.
- [ ] «Shu formadan nusxa» `currentQuestions` bilan ochiladi.
- [ ] `inPlace` oqibati yangi maydonlar uchun ham aytiladi.

### Hali tekshirilmagan

Soxta Meta javoblari bilan testlangan. **Real Meta'da sinalmagan**: tugma so'zini
almashtirish, havolani almashtirish, `url_tags`ni o'qish va yangi kreativga
yozish, karusel kartalarini qayta qurish.

---

## 3-bosqich. Narx chegarasi, attribution, chastota

Reklama guruhining uchta sozlamasi. Bular Meta'da guruhda turadi va bizning
bazada saqlanmaydi, shuning uchun **alohida ikki yo'l** bor va forma ochilganda
qiymatlar Meta'dan shu paytda o'qiladi.

Qayerga qo'yiladi: tahrir oynasida (`C/EditSheet.tsx`) yangi «Kengaytirilgan»
bo'limi. Bo'lim **ochilganda** so'rang, oyna ochilishi bilan emas — har so'rov
Meta'ga bitta murojaat.

### 3.1. Forma

`GET /campaigns/adsets/{adsetId}/delivery`

`adsetId` — guruhning Meta id'si (`group.externalId`, ro'yxat va daraxtdagi `externalId`).

```json
{
  "externalId": "120…",
  "name": "Guruh",
  "currency": "USD",
  "readable": true,
  "canChange": true,
  "warnsLearning": false,
  "note": "",
  "costCap": { "offered": true, "value": 2.5, "highest": 3.33, "budgetMultiple": 3, "note": "" },
  "attribution": {
    "offered": false,
    "value": "click_7",
    "options": [
      { "key": "click_7_view_1", "label": "7 kun bosish, 1 kun ko'rish" },
      { "key": "click_7", "label": "…" },
      { "key": "click_1_view_1", "label": "…" },
      { "key": "click_1", "label": "…" }
    ]
  },
  "frequency": { "offered": false, "times": null, "days": null, "maxTimes": 50, "maxDays": 90 }
}
```

```ts
type DeliveryForm = {
  externalId: string; name: string; currency: string;
  readable: boolean; canChange: boolean; warnsLearning: boolean; note: string;
  costCap: { offered: boolean; value: number | null; highest: number | null; budgetMultiple: number; note: string };
  attribution: { offered: boolean; value: string; options: { key: string; label: string }[] };
  frequency: { offered: boolean; times: number | null; days: number | null; maxTimes: number; maxDays: number };
};
```

| Maydon | Ma'nosi |
|---|---|
| `readable` | `false` — Meta javob bermadi. `note`ni ko'rsating, **hech narsani tahrirlatmang** va bo'sh qiymat chizmang. «Qayta urinish» tugmasi shu GET'ni qayta chaqiradi. |
| `canChange` | `false` — kampaniya tugagan; `note`da sababi. |
| `warnsLearning` | Guruh o'rganish davrida. Tahrir **ochiq**, lekin saqlashdan oldin ogohlantiring: «Bu o'zgarish o'rganishni qaytadan boshlaydi». |
| `*.offered` | `false` — bu sozlama shu guruhga qo'llanmaydi. Qismni **chizmang** (`costCap.note` bo'sh bo'lmasa, o'rniga shu matnni ko'rsating). |

Uchala sozlama ham `offered: false` bo'lsa, «Kengaytirilgan» bo'limini umuman chizmang.

Qaysi maqsadda nima taklif qilinadi:

| Sozlama | Qachon `offered: true` |
|---|---|
| Narx chegarasi | Lid formali yoki saytdagi konversiya maqsadi, **va** byudjet shu guruhda turgan bo'lsa (ABO). Byudjet kampaniyada (CBO) bo'lsa yopiq, `costCap.note` sababini aytadi. |
| Attribution | Saytdagi konversiya maqsadi. |
| Chastota | Qamrov (reach) maqsadi. |

### 3.2. Narx chegarasi (`costCap`)

- Bitta natija (lid, konversiya) uchun eng ko'p to'lanadigan narx.
- `value: null` — chegara yo'q (Meta eng arzon narxda oladi).
- `highest` — bugungi kunlik byudjet ko'tara oladigan eng yuqori chegara: kunlik byudjet chegaraning kamida `budgetMultiple` barobari bo'lishi kerak. Maydon ostida yozing: «Kunlik byudjetingiz bilan eng ko'pi {highest}».
- `costCap.note` — Ads Manager'da boshqa usulda (bid cap) cheklangan guruhda keladi; bunda `offered: false`.

### 3.3. Attribution (`attribution`)

- Natija reklamaga qachon yoziladi: bosishdan / ko'rishdan necha kun ichida.
- `options` — tanlovlar, `label`ni ko'rsating, `key`ni yuboring.
- `value` bo'sh satr bo'lsa — Ads Manager'da bizning to'rttamizdan boshqasi qo'yilgan. Hech biri belgilanmagan holda chizing.

### 3.4. Chastota (`frequency`)

- Bir odam reklamani `days` kun ichida ko'pi bilan `times` marta ko'radi.
- Ikkalasi `null` — chegara yo'q.
- Chegaralar: `1..maxTimes`, `1..maxDays`.

### 3.5. Saqlash

`POST /campaigns/adsets/{adsetId}/delivery`

**Faqat yuborilgan maydon o'zgaradi.** Yuborilmagan maydon o'zgarmaydi;
`null` yuborilsa — o'sha sozlama **olib tashlanadi**.

```json
{ "costCap": 3 }                              // chegarani 3 ga qo'yish
{ "costCap": null }                           // chegarani olib tashlash
{ "attribution": "click_1_view_1" }
{ "frequency": { "times": 2, "days": 7 } }
{ "frequency": null }                         // chastota chegarasini olib tashlash
```

Shuning uchun frontda `undefined` va `null`ni aralashtirmang: o'zgarmagan
maydonni tanadan **olib tashlang**.

**Javob:** `ControlState` (`level: "adset"`), odatdagidek kuzatiladi.

**Xatolar:**

| Kod | Javob | Qachon |
|---|---|---|
| `422` | `problems.costCap` | Summa noto'g'ri yozilgan (valyutaning eng kichik birligidan mayda). |
| `400` | `code: cost_cap_too_low` | Chegara kunlik byudjetga nisbatan yuqori. `detail`da kerakli byudjet aytiladi. |
| `400` | `code: cost_cap_not_offered` | Bu guruhda chegara qo'yilmaydi. |
| `400` | `code: delivery_option_unusable` | Attribution yoki chastota shu maqsadga qo'llanmaydi, yoki qiymat chegaradan tashqarida. |
| `400` | `code: delivery_unreadable` | Meta hozirgi qiymatlarni bermadi; birozdan keyin qayta urinish. |
| `400` | `code: nothing_changed` | Yuborilgan qiymat hozirgisi bilan bir xil. |
| `400` | `code: campaign_finished` | Kampaniya tugagan. |

### 3.6. Qaytarish va tarix

- Tarixda «Narx va hisoblash» nomi bilan ko'rinadi.
- Mavjud **«Qaytarish»** (`POST /campaigns/manage/adset/{id}/revert`) ishlaydi: avvalgi qiymatlar tiklanadi (chegara bo'lmagan bo'lsa — olib tashlanadi).

### 3.7. Tekshirish ro'yxati (front)

- [ ] So'rov bo'lim ochilganda yuboriladi.
- [ ] `readable: false`da qiymat chizilmaydi, «qayta urinish» bor.
- [ ] `offered: false` qism chizilmaydi (`costCap.note` bo'lsa — matn).
- [ ] O'zgarmagan maydon tanadan olib tashlanadi; `null` faqat «olib tashlash» uchun.
- [ ] `warnsLearning`da saqlashdan oldin ogohlantirish.
- [ ] `highest` maydon ostida ko'rsatiladi.

### Hali tekshirilmagan

Soxta Meta javoblari bilan testlangan. **Real Meta'da sinalmagan**: ishlab turgan
guruhda `bid_strategy`/`bid_amount`ni almashtirish, `attribution_spec`ni
o'zgartirish, `frequency_control_specs`ni bo'sh ro'yxat bilan tozalash.

---

## 4-bosqich. Nomlar, tugash sanasini olib tashlash, sarf limitini olib tashlash

### 4.1. Guruh va reklama nomi — YANGI yo'l

`POST /campaigns/manage/{level}/{externalId}/name`

- `level`: `campaign` | `adset` | `ad`. `externalId` — obyektning Meta id'si.
- Tana: `{ "name": "Yangi nom" }`. Javob: `ControlState`.
- Kampaniya uchun eski `POST /campaigns/{id}/name` ham ishlayveradi.

Qoidalar kampaniya nomidagi bilan bir xil:

- bo'sh bo'lmasin, 100 belgidan oshmasin → aks holda `422 problems.name`;
- ortiqcha bo'shliqlar yig'iladi;
- hozirgi nom yuborilsa — rad etiladi (o'zgarish yo'q);
- nom yetkazishga ta'sir qilmaydi: qayta ko'rik ham, o'rganish ham yo'q. O'rganish davrida ham ochiq;
- tarixda ko'rinadi, «Qaytarish» eski nomni aynan tiklaydi.

Qayerga: `C/NameEdit.tsx` komponenti guruh va reklama qatorlarida ham
ishlatiladi (`C/Manager.tsx` Expert jadvali, `C/Tree.tsx`). Hozir u faqat
kampaniyada chiziladi.

### 4.2. Tugash sanasini olib tashlash

Yangi yo'l yo'q. `PATCH /campaigns/{id}` da `endsAt: null` endi **ishlaydi**:
reklama tugash sanasiz, to'xtatilguncha ishlaydi.

**Muhim:** olib tashlash faqat `endsAt` tanada **aniq `null` qilib yuborilganda**
bajariladi. Maydon umuman yuborilmasa — hech narsa o'zgarmaydi. Shuning uchun
foydalanuvchi «tugash sanasiz»ni tanlaganda `endsAt: null` yuboring, boshqa
hollarda formadagi qiymatni qaytaring.

Formaga qo'shildi (`GET /campaigns/{id}/edit`):

| Maydon | Ma'nosi |
|---|---|
| `endsAtRequired` | `true` — byudjet butun muddatga belgilangan (lifetime), Meta bunday reklamani tugash sanasiz ishlatmaydi. «Tugash sanasiz» tanlovini **chizmang**. |

`endsAtRequired: true` bo'lganda `endsAt: null` yuborilsa — `422 problems.endsAt`.

### 4.3. Sarf limitini olib tashlash

`PATCH /campaigns/{id}` da `limit: null` endi limitni **olib tashlaydi** —
xuddi shu qoida bilan: faqat aniq `null` yuborilganda.

Limit maydoni avvalgidek faqat backend taklif qilgan kampaniyada chiziladi.
**O'zimiz ishga tushirgan kampaniyalarda limit maydoni yo'q va bo'lmaydi**:
bunday kampaniya bir sahifa va bir maqsad uchun umumiy, keyingi ishga
tushirishlar ham unga guruh qo'shadi. Kampaniyaga qo'yilgan umumiy limit
keyingi reklamalarni ham jimgina to'xtatib qo'yardi.

### 4.4. Qaytarish

- Tugash sanasi olib tashlansa, «Qaytarish» eski sanani tiklaydi; sana qo'yilgan bo'lsa va avval sana bo'lmagan bo'lsa — «Qaytarish» uni olib tashlaydi.
- Sarf limiti uchun ham xuddi shunday.

### 4.5. Tekshirish ro'yxati (front)

- [ ] Guruh va reklama nomi joyida tahrirlanadi (`x/100`).
- [ ] «Tugash sanasiz» tanlanganda `endsAt: null` aniq yuboriladi; `endsAtRequired`da tanlov yo'q.
- [ ] Limit tozalanganda `limit: null` aniq yuboriladi.
- [ ] O'zgarmagan forma hech narsa yubormaydi yoki qiymatlarni o'zgarmagan holda qaytaradi.

### Hali tekshirilmagan

Soxta Meta javoblari bilan testlangan. **Real Meta'da sinalmagan**: guruh va
reklama nomini o'zgartirish, `end_time=0` bilan sanani olib tashlash,
`spend_cap=922337203685478` bilan limitni olib tashlash (ikkalasi Meta
hujjatidagi qiymatlar).

---

## 6-bosqich. AI chat shu o'zgarishlarni taklif qiladi

Foydalanuvchi chatda so'rasa, AI o'zgarishni **tayyorlaydi** va javob ostida
tasdiqlash tugmasi chiqadi. AI hech narsani o'zi o'zgartirmaydi: o'zgarish
faqat egasi tugmani bosganda yuboriladi va o'sha paytda Reklama sahifasidagi
tekshiruvlardan qayta o'tadi.

**Yo'llar va tugma shakli o'zgarmagan.** Front ishi kam: faqat quyidagi
ikki narsani tekshiring.

### 6.1. Chat endi nimalarni taklif qila oladi

| `action` | Nima | Daraja |
|---|---|---|
| `budget`, `pause`, `resume` | avvalgidek | kampaniya / guruh / reklama |
| `rename` | nom | uchala daraja |
| `end_date` | tugash sanasini qo'yish | guruh |
| `no_end_date` | tugash sanasini olib tashlash | guruh |
| `cost_cap` | bitta natija narxi chegarasi (0 — olib tashlash) | guruh |
| `audience` | yosh, jins, Advantage+ auditoriya | guruh |
| `placement` | qayerda ko'rsatilishi | guruh |
| `advert_text` | reklama matni, sarlavha, tavsif, tugma so'zi, sayt manzili | reklama |

Chatdan **qilinmaydi** (AI «Reklama sahifasida» deb aytadi): joylar,
qiziqishlar, tillar, o'z auditoriyalari, rasm/video, lid forma, chat
salomi, karusel kartalari, nusxa olish, yangi reklama.

Bir javobda ko'pi bilan **2 ta** tugma (avvalgidek).

### 6.2. Tugma maydonlari (o'zgarmagan shakl)

Eski chat: `GET /chat/threads/{id}` → `messages[].changes[]`.
Yangi assistent: `messages[].buttons[]` (`kind: "change"`).

```json
{
  "kind": "change",
  "key": "P1",
  "action": "audience",
  "level": "adset",
  "external_id": "120…",
  "target": "Toshkent 25-45",
  "target_kind": "reklama guruhi",
  "label": "Auditoriyani o'zgartirish",
  "before": "25-45 yosh, hamma, Advantage+ o'chirilgan",
  "after": "25-35 yosh, ayollar, Advantage+ o'chirilgan",
  "state": "open",
  "log_id": ""
}
```

Front tekshiradigan ikki narsa:

1. **`label`, `before`, `after`ni backend bergan matn bilan chizing**, `action`
   bo'yicha frontda matn yozmang. Yangi `action` qiymatlari kelganda tugma
   baribir to'g'ri chiqishi kerak. Agar front `action`ga qarab ikonka yoki
   matn tanlasa — noma'lum qiymatda umumiy ko'rinishga tushsin.
2. **`before` / `after` bir necha qatorli bo'lishi mumkin** (`\n` bilan) —
   `advert_text`da har o'zgargan maydon alohida qatorda:

   ```
   before: "Matn: Buyurtma bering\nTugma: Batafsil"
   after:  "Matn: Bugun 20% chegirma\nTugma: Xarid qilish"
   ```

   `white-space: pre-line` bilan chizing. Uzun matn 80 belgida «…» bilan
   kesilgan holda keladi.

Yangi assistent tugmasida qo'shimcha `params` maydoni keladi — bu backendning
ichki ma'lumoti, uni chizmang va yubormang.

### 6.3. Bosish, bekor qilish, holat

O'zgarmagan:

- eski chat: `POST /chat/changes/{messageId}/{key}`, `…/dismiss`, `GET …`;
- yangi assistent: `POST /assistant/buttons/{messageId}/{key}`, `…/dismiss`.

Yangi holat: tugma bosilganda obyekt o'chirilgan yoki o'zgarish allaqachon
boshqa yo'l bilan bajarilgan bo'lsa, javob `state: "gone"` bo'ladi va hech
narsa yuborilmaydi. Tugmani yashiring, matnini ko'rsating.

### 6.4. Muhim ogohlantirish

`advert_text` yangi reklama yaratadi va eskisini to'xtatadi (Meta qayta
ko'rikdan o'tkazadi). AI buni javobida aytadi; tugma ostida ham qisqa izoh
bo'lsa yaxshi.

### Hali tekshirilmagan

- Tugma oqimi soxta Meta javoblari bilan testlangan; real Meta'da sinalmagan.
- **AI'ning o'zi jonli tekshirilmagan**: yangi prompt versiyalari
  (`assistant/v8`, `chat_answer/v30`) bilan AI to'g'ri obyekt va to'g'ri
  qiymatni tanlashi jonli savollarda (`python -m tools.assistant_eval`)
  o'tkazilmagan.
