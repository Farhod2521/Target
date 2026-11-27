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
