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
