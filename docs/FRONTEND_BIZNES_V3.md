# Biznes: yangi API (`/api/v3/businesses`) — frontend qo'llanmasi

Backend: migratsiyalar `0085`, `0086`, `0088`. Avval backend deploy
qilinadi, keyin `python -m app.modules.businesses.backfill --apply` bir marta yurgiziladi.

**Eski API o'zgarmagan.** `/api/v1` va `/api/v2` dagi hech bir yo'l, maydon yoki javob
o'zgarmadi. Eski front yangi backend bilan avvalgidek ishlaydi. Bu hujjatdagi hamma narsa
yangi, yonma-yon qo'shilgan.

OpenAPI'ni qayta generatsiya qiling (`pnpm api:gen`): yangi sxemalar `BusinessCardOut`,
`BusinessDetailOut`, `MembersOut`, `MemberIn`, `MemberPatch`, `CatalogOut`, `NetworksOut`,
`NetworkIn`, `HistoryOut`.

**2026-11-26 qo'shimchasi:** biznesga boshqa tarmoq ulash (8b), o'zgarishlar tarixi (8c),
`X-Business` Google va ChatGPT yo'llarida (8a), CRM ruxsati lid manbasi bo'yicha va ROP
kartani menejerga berishi (8-bo'lim). `GET /api/v1/crm` javobiga ikki maydon qo'shildi:
`may_assign`, `read_only`.

## 1. Nima o'zgardi

| Avval | Endi |
|---|---|
| Ish birligi: Facebook sahifa + reklama akkaunt juftligi | Ish birligi: **Biznes**. Har juftlik bitta biznes |
| Xodim = faqat CRM menejeri, bitta juftlikda | Xodim biznesga a'zo; **rol** va **ruxsatlar** bilan; bir nechta biznesda ishlay oladi, CRM'da ham |
| Menejer logini faqat `/api/v1/crm` ni ochadi | Xodim logini `/api/v3/businesses` ni ham ochadi |

Bitta sahifaga ikkita reklama akkaunti ulangan bo'lsa, ular **ikkita alohida biznes**
bo'lib keladi (nomi bir xil, Meta tarmog'ining `pair` har xil).

Profili hali to'ldirilmagan sahifaning juftligi ro'yxatda **chiqmaydi**. Egasi profilni
saqlagach (`PUT /api/v1/business/pages/{page_id}`), biznes o'zi paydo bo'ladi.

## 2. Umumiy qoidalar

- Avtorizatsiya avvalgidek: `Authorization: Bearer <access>`.
- Har yo'l kim so'rayotganini tekshiradi:
  - **ega** — hamma narsa;
  - **xodim** — faqat o'zi ishlaydigan biznesni o'qiydi;
  - **begona** — `404 unknown_business` (biznes bor-yo'qligi ham aytilmaydi).
- Xatolar avvalgi shaklda: `{"detail": "...", "code": "..."}`. `detail` foydalanuvchiga
  ko'rsatiladi, `code` bo'yicha shart yoziladi. Kodlar ro'yxati 7-bo'limda.
- Xodimlar ro'yxatini o'zgartiradigan har so'rov (qo'shish, o'zgartirish, o'chirish)
  javobida **yangi to'liq ro'yxat** qaytadi (`MembersOut`). Alohida qayta so'rash shart emas.

## 3. Bizneslar ro'yxati — almashtirgich uchun

`GET /api/v3/businesses`

Ega uchun: reklama manbai ulangan o'z bizneslari. Xodim uchun: o'zi ishlaydigan bizneslar.

```json
{
  "businesses": [
    {
      "id": "7c1e…",
      "name": "Shirin Non",
      "category_label": "Restoran / kafe",
      "city": "Toshkent",
      "networks": [
        {
          "provider": "meta",
          "kind": "meta_pair",
          "pair": "1029384756:act_55501",
          "page": {"id": "…", "external_id": "1029384756", "name": "Shirin Non", "instagram_username": "shirinnon"},
          "ad_account": {"id": "…", "external_id": "act_55501", "name": "Asosiy", "currency": "USD"},
          "bound_at": "2026-11-24T06:10:00Z"
        }
      ],
      "access": {
        "is_owner": true,
        "roles": [],
        "is_rop": false,
        "reads_all_leads": true,
        "grants": []
      }
    }
  ]
}
```

| Maydon | Ma'nosi |
|---|---|
| `networks[]` | Biznes reklama beradigan tarmoqlar. Hozir faqat `meta` |
| `networks[].pair` | Eski `?pair=` parametrlari qabul qiladigan qiymat. Shu biznesning CRM'ini ochish uchun: `GET /api/v1/crm/…?pair=<pair>` |
| `access.is_owner` | `true` bo'lsa hamma narsa ochiq; `grants` bo'sh keladi, uni tekshirmang |
| `access.roles` | Xodimning rollari: `targetolog`, `sales`. Ega uchun bo'sh |
| `access.is_rop` | ROP belgisi |
| `access.reads_all_leads` | Boshqa menejerlarning lidlarini ko'rishi mumkinmi (ega va ROP — `true`) |
| `access.grants[]` | Xodimning ruxsatlari, 5-bo'limga qarang |

Ro'yxat bo'sh kelsa: ega uchun «Biznes yo'q, sahifa ulang va profilni to'ldiring», xodim
uchun «Sizga biznes biriktirilmagan».

## 4. Bitta biznes

`GET /api/v3/businesses/{id}` — ro'yxatdagi karta + ikki maydon:

| Maydon | Ma'nosi |
|---|---|
| `profile` | Biznes profili, `/api/v1/business` dagi `BusinessOut` bilan bir xil shakl |
| `members_count` | Faol xodimlar soni. Faqat egaga keladi; xodimga `null` |

Profilni **tahrirlash** hozircha eski yo'llarda: `PUT /api/v1/business/pages/{page_id}`
(`page_id` — Meta tarmog'ining `page.id`). v3 da tahrirlash yo'li hali yo'q.

## 5. Rollar va ruxsatlar

Ruxsat — uch qismli yozuv: **bo'lim**, **tarmoq**, **daraja**.

| Qism | Qiymatlar |
|---|---|
| `area` | `ads` — reklama; `crm` — CRM |
| `provider` | biznesga ulangan tarmoq (`meta`, `google`, `chatgpt`), yoki `other` — tarmog'i yo'q lidlar (qo'lda kiritilgan, sayt formasi). `other` faqat `crm` uchun |
| `level` | `view` — ko'rish; `edit` — o'zgartirish. `edit` ichiga `view` kiradi |

Rol — tayyor ruxsatlar to'plami. Rol tanlanganda to'plam yoziladi, keyin ega har birini
alohida o'zgartira oladi.

| Rol | Tayyor to'plam |
|---|---|
| `targetolog` | `ads` · har tarmoq · `edit` |
| `sales` (Sotuv manageri) | `crm` · har tarmoq va `other` · `edit`; faqat o'z lidlari |
| `sales` + `is_rop` (ROP) | sotuv managerining to'plami; qo'shimcha boshqa menejerlar lidlarini ham ko'radi |

Bitta odam bitta biznesda ikkala rolda bo'lishi mumkin. `is_rop` faqat `sales` roli bilan
beriladi.

**Frontda tekshirish:** bo'lim yoki tugmani ko'rsatishdan oldin shu funksiya yetarli.

```ts
function may(access: AccessOut, area: "ads" | "crm", provider: string, level: "view" | "edit") {
  if (access.is_owner) return true;
  const g = access.grants.find(x => x.area === area && x.provider === provider);
  return !!g && (level === "view" || g.level === "edit");
}
```

Rol nomiga qarab `if` yozmang, faqat `grants` ga qarang: ega to'plamni o'zgartirgan bo'lishi
mumkin (masalan sotuv manageriga reklamani «ko'rish» berilgan).

### Forma uchun katalog

`GET /api/v3/businesses/catalog` — rollar, bo'limlar va darajalar nomlari bilan.

```json
{
  "roles": [
    {"key": "targetolog", "label": "Targetolog", "may_be_rop": false,
     "grants": [{"area": "ads", "provider": "*", "level": "edit"}]},
    {"key": "sales", "label": "Sotuv manageri", "may_be_rop": true,
     "grants": [{"area": "crm", "provider": "*", "level": "edit"},
                {"area": "crm", "provider": "other", "level": "edit"}]}
  ],
  "areas": [{"key": "ads", "label": "Reklama"}, {"key": "crm", "label": "CRM"}],
  "levels": [{"key": "view", "label": "Ko'rish"}, {"key": "edit", "label": "O'zgartirish"}],
  "other_source": {"key": "other", "label": "Boshqa manba"}
}
```

`provider: "*"` — «biznesning har tarmog'i» degani. Formada uni `MembersOut.networks`
dagi tarmoqlar bilan almashtirib ko'rsating.

## 6. Xodimlar — faqat ega uchun

### Ro'yxat

`GET /api/v3/businesses/{id}/members`

```json
{
  "members": [
    {
      "id": "b41f…",
      "user": {"id": "…", "full_name": "Ali Karimov", "email": "ali@example.com"},
      "roles": ["targetolog"],
      "is_rop": false,
      "is_active": true,
      "joined_at": "2026-11-25T09:00:00Z",
      "removed_at": null,
      "from_crm": false,
      "grants": [{"area": "ads", "provider": "meta", "level": "edit"}]
    }
  ],
  "seats": {"taken": 1, "capacity": 2, "free": 1},
  "candidates": [{"id": "…", "full_name": "Vali", "email": "vali@example.com"}],
  "networks": ["meta"]
}
```

| Maydon | Ma'nosi |
|---|---|
| `from_crm` | `true` — bu odam shu biznes CRM'ining menejeri (`sales` roli bor). Faqat ma'lumot uchun: uni ham shu yerdan o'zgartirish va o'chirish mumkin |
| `seats` | Joylar egasining **barcha** bizneslari bo'yicha umumiy. `free: 0` bo'lsa «Xodim qo'shish» o'rniga «Joy sotib olish» ko'rsating |
| `candidates` | Egasining boshqa biznesda ishlayotgan, bu biznesga hali qo'shilmagan odamlari. «Mavjud xodimni tanlash» ro'yxati |
| `networks` | Ruxsat berish mumkin bo'lgan tarmoqlar |

Joy qoidasi: **bitta biznesdagi bitta odam = bitta joy**, rollari nechta bo'lishidan qat'i
nazar. Ikki biznesda ishlagan odam ikki joy egallaydi.

### Qo'shish

`POST /api/v3/businesses/{id}/members` → `201`, javob `MembersOut`.

Ikki xil yuboriladi.

Yangi login bilan:

```json
{"name": "Ali Karimov", "email": "ali@example.com", "password": "…", "roles": ["targetolog"]}
```

Mavjud odamni tanlab (`candidates` dan):

```json
{"user_id": "…", "roles": ["targetolog"],
 "grants": [{"area": "ads", "provider": "meta", "level": "view"}]}
```

- `grants` yuborilmasa — rolning tayyor to'plami yoziladi.
- `grants` yuborilsa — **aynan shular** yoziladi, tayyor to'plam qo'llanmaydi.
- Parol qoidalari ro'yxatdan o'tishdagidek; xato matni `detail` da keladi.

**Sotuv manageri (`sales`)** shu yo'lning o'zida CRM menejeriga ham aylanadi: unga CRM
doskasi ochiladi, lidlar navbat bilan tusha boshlaydi. Alohida `POST /api/v1/crm/settings/members`
chaqirish shart emas. Yangi login birinchi kirishda parolni almashtirishi so'raladi
(avvalgidek); mavjud odam (`user_id`) dan so'ralmaydi.

Bir odam ikki biznesning CRM'ida ishlashi mumkin: ikkinchi biznesga `user_id` bilan
qo'shiladi. Har biznesning lid navbati alohida.

### O'zgartirish

`PATCH /api/v3/businesses/{id}/members/{member_id}`

```json
{"roles": ["sales", "targetolog"], "is_rop": true}
```

`grants` qoidasi qo'shishdagidek: yuborilmasa tayyor to'plam **qayta yoziladi** (avvalgi
qo'lda o'zgartirishlar yo'qoladi), yuborilsa aynan shular qoladi. Shuning uchun ruxsatlar
jadvalini tahrirlaganda har doim to'liq `grants` ni yuboring.

`sales` rolining qo'shilishi va olinishi CRM'ga ham ta'sir qiladi:

| O'zgarish | Natija |
|---|---|
| `sales` qo'shildi | Odam shu biznes CRM'ining menejeri bo'ladi |
| `sales` olindi | Odam CRM'dan chiqadi; ochiq kartalari birinchi ustunga, egasiz qaytadi |

CRM ruxsati darajasi ham ishlaydi (`area: "crm"`, `provider: "meta"`):

| Daraja | CRM doskasida |
|---|---|
| `edit` | Odatdagidek ishlaydi |
| `view` | Doskani ko'radi, hech narsani o'zgartira olmaydi (`403`) |
| yo'q | Doska ochilmaydi: `409`, `detail.crm = "closed"` (CRM'ning mavjud «yopiq» javobi) |

### O'chirish

`DELETE /api/v3/businesses/{id}/members/{member_id}`

Xodim shu zahoti biznesni ko'rmay qoladi (`404`). CRM menejeri bo'lsa, shu biznesning
CRM'idan ham chiqadi va shu biznesdagi ochiq kartalari egasiz qaytadi.

Login taqdiri:

| Holat | Login |
|---|---|
| Odam boshqa biznesda ham ishlaydi | saqlanadi, u yerda ishlashda davom etadi |
| Bu uning yagona ishi edi | yopiladi (avvalgi CRM qoidasi) |

O'chirishdan oldin tasdiq so'rang va ikkinchi holatda «login yopiladi» deb ogohlantiring:
`candidates` ro'yxatida va boshqa bizneslarda bu odam bo'lmasa, bu uning yagona ishi.

## 7. Xato kodlari

| HTTP | `code` | Qachon | Frontda |
|---|---|---|---|
| 404 | `unknown_business` | Biznes yo'q yoki sizniki emas | Ro'yxatga qaytaring |
| 403 | `no_access` | Xodim ega uchun yo'lni so'radi | Bo'limni yashiring |
| 404 | `unknown_member` | Xodim topilmadi yoki o'chirilgan | Ro'yxatni yangilang |
| 409 | `member_exists` | Bu odam biznesda allaqachon bor | Xabar |
| 409 | `no_seat` | Bo'sh joy yo'q | «Joy sotib olish» ga yo'naltiring |
| 409 | `no_pair_for_crm` | `sales` berilmoqda, lekin biznesning sahifa + akkaunt juftligi topilmadi | Ulanishlarga yo'naltiring |
| 400 | `login_required` | Na `user_id`, na ism+email+parol | Forma xatosi |
| 400 | `not_your_staff` | `user_id` egasining odami emas | Xabar |
| 400 | `rop_needs_sales` | `is_rop` `sales` rolisiz | Belgini o'chiring |
| 404 | `unknown_account` | Tarmoq ulashda: akkaunt yo'q yoki egasiniki emas | Ro'yxatni yangilang |
| 404 | `unknown_network` | Uzishda: bu tarmoq biznesga ulanmagan | Ro'yxatni yangilang |
| 400 | `meta_is_pair` | Meta shu yo'l bilan ulanmaydi/uzilmaydi | «Ulanishlar» ga yo'naltiring |
| 400 | `account_not_in_use` | Akkaunt «Ulanishlar» da yoqilmagan | «Ulanishlar» ga yo'naltiring |
| 409 | `network_taken` | Biznesda shu tarmoqning akkaunti allaqachon bor | Avval uzishni taklif qiling |
| 409 | `account_bound` | Akkaunt boshqa biznesga ulangan | Xabar |
| 400 | `member_lacks_source` | CRM: karta berilayotgan menejerda shu manba ruxsati yo'q | Xabar |
| 400 | `bad_grant` | Ulanmagan tarmoq, yoki `other` reklama uchun | `detail` ni ko'rsating |
| 409 | `conflict` | Bu email bilan akkaunt bor (`detail` da matni) | Forma xatosi |
| 422 | — | `roles` bo'sh yoki noto'g'ri qiymat | Forma xatosi |

## 8. Xodim logini bilan kirganda

Xodim logini (CRM menejeri yoki targetolog) uchun ochiq yo'llar:

| Yo'l | Ochiq |
|---|---|
| `/api/v1/auth/*`, `GET /api/v1/account`, `/api/v1/account/language` | ha, avvalgidek |
| `/api/v1/crm/*` | ha, avvalgidek (faqat CRM menejeri ishlay oladi). Bir nechta biznesda ishlasa — `?pair=` bilan tanlaydi, pastga qarang |
| `/api/v3/businesses`, `/{id}`, `/catalog` | **ha, yangi** |
| `/api/v3/businesses/{id}/members` | yo'q — `403 no_access` |
| boshqa hamma `/api/v1`, `/api/v2` | yo'q — `403`, avvalgidek |

Kirgandan keyin: `GET /api/v3/businesses` → ro'yxatda bitta bo'lsa to'g'ri o'sha biznesga,
bir nechta bo'lsa almashtirgichni ko'rsating.

`networks` ro'yxatida endi bir nechta tarmoq bo'lishi mumkin (tartib: tarmoq nomi bo'yicha).
Meta juftligini indeks bilan emas, `provider === "meta"` bo'yicha toping:

```ts
const metaPair = business.networks.find(n => n.provider === "meta")?.pair;
```

**CRM menejeri bir nechta biznesda ishlasa:** barcha `/api/v1/crm/*` so'rovlariga
tanlangan biznesning Meta tarmog'ining `pair` qiymatini `?pair=` qilib qo'shing. Parametrsiz
so'rov uning birinchi biznesini ochadi. Avval `?pair=` menejer uchun e'tiborga olinmas edi,
endi olinadi.

**ROP** (`access.reads_all_leads: true`) doskada boshqa menejerlarning kartalarini ham
ko'radi. Ularning ichini o'zgartira olmaydi (`403`), lekin **kartani menejerga bera oladi**:

- `GET /api/v1/crm` javobida `may_assign: true` — ega va ROP uchun.
- `POST /api/v1/crm/cards/{id}/assign` `{ "assignee": "<menejer user id>" }` — boshqa
  menejerga o'tkazish; `{ "assignee": "" }` — doskaga qaytarish.
- `POST /api/v1/crm/cards/bulk` da `action: "assign"` ham ROP uchun ochiq.
- ROP kartani egaga bera olmaydi (`403`), va shu lid manbasida ruxsati yo'q menejerga ham
  (`400 member_lacks_source`).

Filtrdagi «menejer» tanlovini va «Menejerga berish» tugmasini `may_assign` ga qarab ko'rsating.

**CRM ruxsati lid manbasi bo'yicha ishlaydi.** Har kartaning manbasi — lidni olib kelgan
tarmoq (`meta`, `google`, …) yoki `other` (qo'lda kiritilgan mijoz).

| Menejerning `crm` ruxsati | Natija |
|---|---|
| manba uchun `edit` | kartani ko'radi va o'zgartiradi |
| manba uchun `view` | ko'radi, o'zgartira olmaydi (`403`) |
| manba uchun ruxsat yo'q | karta unga ko'rinmaydi; lid unga taqsimlanmaydi |
| `other` uchun `edit` yo'q | «Mijoz qo'shish» (qo'lda) yopiq — `403` |
| hech bir `crm` ruxsati yo'q | doska yopiq (`409 {"crm": "closed"}`) |

`GET /api/v1/crm` javobidagi `read_only: true` — menejerning hamma ruxsati `view`:
doskadagi barcha yozish tugmalarini yashiring.

## 8a. Reklama: `X-Business` sarlavhasi

Reklama yo'llari (`/api/v1/campaigns`, `/api/v2/campaigns`, `/api/v1/launch`,
`/api/v1/metrics`) o'zgarmagan. Ularga bitta sarlavha qo'shildi:

```
X-Business: <biznes id>
```

| Kim | Sarlavha bilan | Sarlavhasiz |
|---|---|---|
| Ega | So'rov shu biznesning sahifa va akkauntida ishlaydi. Kabinetning «joriy juftligi» o'zgarmaydi | Avvalgidek: kabinetning joriy juftligi |
| Xodim (reklama ruxsati bor) | So'rov shu biznesda, egasi nomidan ishlaydi | `403` |
| Xodim (reklama ruxsati yo'q) | `403 no_access` | `403` |
| Begona biznes | `404 unknown_business` | — |

Ruxsat darajasi so'rov turiga qarab tekshiriladi (`area: "ads"`, `provider: "meta"`):

| So'rov | Kerakli daraja |
|---|---|
| `GET` | `view` |
| `POST`, `PUT`, `PATCH`, `DELETE` | `edit` |

Ba'zi o'qish amallari `POST` bilan qilinadi (masalan `/campaigns/sync`): ular ham `edit`
talab qiladi. `view` ruxsatli xodimga bunday tugmalarni ko'rsatmang.

**Frontda:** API mijoziga bitta joyda qo'shing — tanlangan biznes bo'lsa, yuqoridagi
prefikslardagi har so'rovga `X-Business` qo'yiladi. Shunda biznes almashtirgich
`POST /connections/meta/switch/pair` ni chaqirmasdan ishlaydi: almashtirish shunchaki
sarlavhadagi id ni o'zgartiradi va so'rovlarni qayta yuboradi (React Query kalitiga biznes
id sini qo'shing).

Xodim bajargan o'zgarishlar tarixda egasi hisobida, lekin xodim nomi bilan saqlanadi.

Bu sarlavha faqat shu bo'limdagi prefikslarda xodimga yo'l ochadi. To'lov, ulanishlar,
sozlamalar va boshqa hamma narsa xodimga avvalgidek yopiq.

**Boshqa tarmoqlar.** `X-Business` Google va ChatGPT Ads yo'llarida ham ishlaydi:

| Yo'l | Tekshiriladigan ruxsat |
|---|---|
| `/api/v1/campaigns`, `/api/v2/campaigns`, `/api/v1/launch`, `/api/v1/metrics` | `ads` · `meta` |
| `/api/v1/google/*` | `ads` · `google` |
| `/api/v1/chatgpt/*` | `ads` · `chatgpt` |
| `POST /api/v1/launch/drafts` | `flow` ga qarab: `google` → `ads` · `google`, aks holda `ads` · `meta` |
| `/api/v1/launch/drafts/{id}/…` | qoralama Google'niki bo'lsa `ads` · `google`, aks holda `ads` · `meta` |

Sarlavha bilan so'rov biznesga ulangan akkauntda ishlaydi. Biznesga shu tarmoq ulanmagan
bo'lsa, ega uchun ham «akkaunt yo'q» holati qaytadi (kabinetdagi joriy Google akkaunti
olinmaydi) — bu holda «Tarmoq ulash» ni taklif qiling (8b-bo'lim).

## 8b. Biznesga boshqa tarmoq ulash — faqat ega uchun

Meta juftligi «Ulanishlar» bo'limida boshqariladi va biznes shundan paydo bo'ladi. Qolgan
tarmoqlar (hozir Google va ChatGPT Ads) biznesga shu yerda ulanadi. Qoida: **bitta biznesda
har tarmoqdan bitta akkaunt; bitta akkaunt faqat bitta biznesda.**

Avval ega tarmoqqa avvalgidek ulanadi va akkauntni yoqadi (`/api/v1/connections/…`), keyin
uni biznesga biriktiradi.

### Ro'yxat

`GET /api/v3/businesses/{id}/networks`

```json
{
  "networks": [
    { "provider": "google", "kind": "ad_account", "pair": "1112223333",
      "page": null,
      "ad_account": { "id": "…", "external_id": "1112223333", "name": "Google akkaunt", "currency": "USD" },
      "bound_at": "2026-11-26T10:00:00Z" },
    { "provider": "meta", "kind": "meta_pair", "pair": "1234:act_5678", "page": { "…": "…" }, "ad_account": { "…": "…" }, "bound_at": "…" }
  ],
  "available": [
    { "id": "…", "provider": "chatgpt", "external_id": "…", "name": "…", "currency": "USD" }
  ]
}
```

`available` — egasining shu biznesga ulasa bo'ladigan akkauntlari: yoqilgan, hech bir
biznesga ulanmagan, va biznesda shu tarmoq hali yo'q. Bo'sh bo'lsa «Tarmoq ulash» tugmasi
o'rniga «Ulanishlar» ga havola ko'rsating.

### Ulash

`POST /api/v3/businesses/{id}/networks` → `201`, javob — yangilangan ro'yxat.

```json
{ "ad_account_id": "<available[].id>" }
```

Ulanganda:

- xodimlar yangi tarmoqda **boshqa tarmoqlardagi ruxsatini** oladi (eng past darajasi;
  biror tarmoqda ruxsati yo'q bo'lsa — hech narsa). Masalan Meta'da `ads · edit` bo'lgan
  targetolog Google'da ham `ads · edit` oladi. Ega keyin xodim formasida o'zgartira oladi;
- shu akkaunt olib kelgan lidlar biznesga yoziladi va biznesning CRM doskasiga tusha
  boshlaydi (`crm` · shu tarmoq ruxsati bor menejerlarga taqsimlanadi);
- `GET /businesses` va `/{id}` dagi `networks` da yangi tarmoq paydo bo'ladi, ruxsat
  jadvalida yangi qator chiqadi (`MembersOut.networks`).

### Uzish

`DELETE /api/v3/businesses/{id}/networks/{provider}` → `200`, javob — yangilangan ro'yxat.

Xodimlarning shu tarmoqdagi ruxsatlari olib tashlanadi. Avval kelgan lidlar va kartalar
biznesda qoladi. `meta` ni bu yo'l bilan uzib bo'lmaydi (`400 meta_is_pair`).

## 8c. O'zgarishlar tarixi — faqat ega uchun

`GET /api/v3/businesses/{id}/history?limit=100` — kim qo'shildi, kimning roli yoki ruxsati
o'zgardi, kim chiqarildi, qaysi tarmoq ulandi yoki uzildi. Yangisi birinchi.

```json
{
  "items": [
    { "id": "…", "at": "2026-11-26T10:05:00Z", "kind": "member_changed",
      "label": "Xodimning roli yoki ruxsati o'zgardi", "via": "",
      "member": { "member_id": "…", "user_id": "…", "full_name": "Ali" },
      "before": { "roles": ["targetolog"], "is_rop": false,
                  "grants": [{ "area": "ads", "provider": "meta", "level": "edit" }] },
      "after":  { "roles": ["targetolog"], "is_rop": false,
                  "grants": [{ "area": "ads", "provider": "meta", "level": "view" }] },
      "provider": "", "account_name": "" },
    { "id": "…", "at": "…", "kind": "network_bound", "label": "Biznesga tarmoq ulandi",
      "via": "", "member": null, "before": null, "after": null,
      "provider": "google", "account_name": "Google akkaunt" }
  ]
}
```

| `kind` | Ma'nosi | To'ldirilgan maydonlar |
|---|---|---|
| `member_added` | Xodim qo'shildi | `member`, `after` |
| `member_changed` | Rol yoki ruxsat o'zgardi | `member`, `before`, `after` |
| `member_removed` | Xodim chiqarildi | `member`, `before`, `after` |
| `network_bound` | Tarmoq ulandi | `provider`, `account_name` |
| `network_unbound` | Tarmoq uzildi | `provider`, `account_name` |

`via: "crm"` — o'zgarish CRM bo'limida qilingan (menejer o'sha yerda qo'shilgan yoki
o'chirilgan). Tarix shu funksiya chiqqan kundan boshlab yoziladi; undan oldingi
o'zgarishlar yo'q.

## 9. Frontda qilinadigan ishlar

| # | Ish | Qayerda |
|---|---|---|
| 1 | API qatlami: `packages/api/src/businesses.ts` + ko'prik + mock | `packages/api` |
| 2 | Biznes almashtirgich (yuqori panel): `GET /businesses`, tanlangan biznes `id` si saqlanadi | `apps/cabinet/src/shell.tsx` |
| 3 | Tanlangan biznesdan eski ekranlarga o'tish: reklama so'rovlariga `X-Business` (8a-bo'lim), CRM so'rovlariga `?pair=<Meta tarmog'ining pair qiymati>` | dashboard, reklama, CRM, lidlar |
| 4 | Sozlamalar → «Xodimlar» sahifasi: ro'yxat, joylar ko'rsatkichi, qo'shish (yangi login / mavjud odam), rol va ruxsat jadvali, o'chirish | `apps/cabinet/src/pages/settings` |
| 5 | Ruxsat jadvali: qatorlar — `networks` + «Boshqa manba»; ustunlar — Reklama, CRM; katak — yo'q / ko'rish / o'zgartirish | o'sha yerda |
| 6 | Xodim logini uchun kirish oqimi: bizneslar ro'yxati → biznes; ruxsati yo'q bo'limlar yashiriladi (`may()` funksiyasi) | `apps/cabinet` |
| 7 | Xato kodlari bo'yicha yo'naltirish (`no_seat`, `no_pair_for_crm`) | o'sha yerda |
| 8 | Biznes sahifasida «Tarmoqlar» bloki: ulangan tarmoqlar, «Tarmoq ulash» (`available` dan tanlash), uzish (tasdiq bilan) | biznes sozlamalari |
| 9 | Google va ChatGPT Ads ekranlari so'rovlariga ham `X-Business`; biznesda tarmoq yo'q bo'lsa «Tarmoq ulash» holati | Google, ChatGPT ekranlari |
| 10 | CRM: `may_assign` bo'lsa «Menejerga berish»; `read_only` bo'lsa yozish tugmalari yashiriladi; `other` ruxsati bo'lmasa «Mijoz qo'shish» yashiriladi | CRM doskasi |
| 11 | «Xodimlar» sahifasida «Tarix» yorlig'i (8c-bo'lim) | sozlamalar |

## 10. Hali yo'q narsalar

Bular keyingi bosqichlarda chiqadi; hozir ularga tayanib ekran qurmang.

- **Fon vazifalari.** `X-Business` so'rov davomida ishlaydi. So'rovdan keyin fonda
  bajariladigan ishlar (masalan sinxronlash) biznesni so'rov bergan ma'lumotdan oladi;
  sezilgan nomuvofiqlik bo'lsa xabar bering.
- **AI chat va agent** xodimga hali yopiq (`/api/v1/chat`, `/api/v1/agent`).
- **Profilni v3 dan tahrirlash.**
- **Yangi biznes yaratish.** Biznes hozircha sahifa ulanib, juftlik va profil saqlanganda
  o'zi paydo bo'ladi.
- **AI chat, hisobot, bot** hali juftlik bo'yicha.
- **Google profili.** Google akkauntining o'z profil yozuvi bor
  (`/api/v1/business/google/{account_id}`); biznesga ulanganda u biznes profili bilan
  birlashmaydi, Google reklamasi avvalgidek o'z profilidan o'qiydi.
- **Meta juftligisiz biznes.** Faqat Google'da ishlaydigan biznes hozircha yaratilmaydi:
  tarmoq mavjud (Meta juftligi bor) biznesga ulanadi.
- **Tarif limiti** boshqa tarmoqlar soniga hali qo'yilmagan (faqat Google akkauntlari soni
  avvalgidek tarifdan).
