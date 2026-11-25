# Biznes: yangi API (`/api/v3/businesses`) — frontend qo'llanmasi

Backend: `feat/business-structure` shoxi, migratsiyalar `0081`, `0082`. Avval backend deploy
qilinadi, keyin `python -m app.modules.businesses.backfill --apply` bir marta yurgiziladi.

**Eski API o'zgarmagan.** `/api/v1` va `/api/v2` dagi hech bir yo'l, maydon yoki javob
o'zgarmadi. Eski front yangi backend bilan avvalgidek ishlaydi. Bu hujjatdagi hamma narsa
yangi, yonma-yon qo'shilgan.

OpenAPI'ni qayta generatsiya qiling (`pnpm api:gen`): yangi sxemalar `BusinessCardOut`,
`BusinessDetailOut`, `MembersOut`, `MemberIn`, `MemberPatch`, `CatalogOut`.

## 1. Nima o'zgardi

| Avval | Endi |
|---|---|
| Ish birligi: Facebook sahifa + reklama akkaunt juftligi | Ish birligi: **Biznes**. Har juftlik bitta biznes |
| Xodim = faqat CRM menejeri, bitta juftlikda | Xodim biznesga a'zo; **rol** va **ruxsatlar** bilan; bir nechta biznesda ishlay oladi |
| Menejer logini faqat `/api/v1/crm` ni ochadi | Xodim logini `/api/v3/businesses` ni ham ochadi |

Bitta sahifaga ikkita reklama akkaunti ulangan bo'lsa, ular **ikkita alohida biznes**
bo'lib keladi (nomi bir xil, `networks[0].pair` har xil).

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
(`page_id` — `networks[0].page.id`). v3 da tahrirlash yo'li hali yo'q.

## 5. Rollar va ruxsatlar

Ruxsat — uch qismli yozuv: **bo'lim**, **tarmoq**, **daraja**.

| Qism | Qiymatlar |
|---|---|
| `area` | `ads` — reklama; `crm` — CRM |
| `provider` | tarmoq (`meta`), yoki `other` — tarmog'i yo'q lidlar (qo'lda kiritilgan, sayt formasi). `other` faqat `crm` uchun |
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
| `from_crm` | `true` — bu sotuv manageri CRM bo'limida qo'shilgan. Uni bu yerdan o'chirib bo'lmaydi va `sales` rolini olib bo'lmaydi (`409 managed_by_crm`). «O'chirish» tugmasini yashiring, o'rniga «CRM bo'limida boshqariladi» deb yozing |
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

**Muhim cheklov (hozircha):** `sales` rolini bu yerdan yangi odamga berib bo'lmaydi —
`409 sales_through_crm`. Sotuv manageri avvalgidek CRM bo'limida qo'shiladi
(`POST /api/v1/crm/settings/members`) va bu ro'yxatda o'zi paydo bo'ladi (`from_crm: true`). Shundan
keyin unga shu yerdan ROP belgisi yoki `targetolog` roli qo'shish mumkin. Formada «Sotuv
manageri» tanlansa, CRM bo'limiga yo'naltiring.

### O'zgartirish

`PATCH /api/v3/businesses/{id}/members/{member_id}`

```json
{"roles": ["sales", "targetolog"], "is_rop": true}
```

`grants` qoidasi qo'shishdagidek: yuborilmasa tayyor to'plam **qayta yoziladi** (avvalgi
qo'lda o'zgartirishlar yo'qoladi), yuborilsa aynan shular qoladi. Shuning uchun ruxsatlar
jadvalini tahrirlaganda har doim to'liq `grants` ni yuboring.

### O'chirish

`DELETE /api/v3/businesses/{id}/members/{member_id}`

Xodim shu zahoti biznesni ko'rmay qoladi (`404`). Yozuvi saqlanadi, qayta qo'shilsa
o'sha yozuvda tiklanadi. Login o'chirilmaydi: odam boshqa bizneslarda ishlashda davom etadi.

## 7. Xato kodlari

| HTTP | `code` | Qachon | Frontda |
|---|---|---|---|
| 404 | `unknown_business` | Biznes yo'q yoki sizniki emas | Ro'yxatga qaytaring |
| 403 | `no_access` | Xodim ega uchun yo'lni so'radi | Bo'limni yashiring |
| 404 | `unknown_member` | Xodim topilmadi yoki o'chirilgan | Ro'yxatni yangilang |
| 409 | `member_exists` | Bu odam biznesda allaqachon bor | Xabar |
| 409 | `no_seat` | Bo'sh joy yo'q | «Joy sotib olish» ga yo'naltiring |
| 409 | `sales_through_crm` | `sales` roli CRM'da qo'shilmagan odamga berildi | CRM bo'limiga yo'naltiring |
| 409 | `managed_by_crm` | CRM menejerini bu yerdan o'chirish yoki `sales` ni olib tashlash | Xabar |
| 400 | `login_required` | Na `user_id`, na ism+email+parol | Forma xatosi |
| 400 | `not_your_staff` | `user_id` egasining odami emas | Xabar |
| 400 | `rop_needs_sales` | `is_rop` `sales` rolisiz | Belgini o'chiring |
| 400 | `bad_grant` | Ulanmagan tarmoq, yoki `other` reklama uchun | `detail` ni ko'rsating |
| 409 | `conflict` | Bu email bilan akkaunt bor (`detail` da matni) | Forma xatosi |
| 422 | — | `roles` bo'sh yoki noto'g'ri qiymat | Forma xatosi |

## 8. Xodim logini bilan kirganda

Xodim logini (CRM menejeri yoki targetolog) uchun ochiq yo'llar:

| Yo'l | Ochiq |
|---|---|
| `/api/v1/auth/*`, `GET /api/v1/account`, `/api/v1/account/language` | ha, avvalgidek |
| `/api/v1/crm/*` | ha, avvalgidek (faqat CRM menejeri ishlay oladi) |
| `/api/v3/businesses`, `/{id}`, `/catalog` | **ha, yangi** |
| `/api/v3/businesses/{id}/members` | yo'q — `403 no_access` |
| boshqa hamma `/api/v1`, `/api/v2` | yo'q — `403`, avvalgidek |

Kirgandan keyin: `GET /api/v3/businesses` → ro'yxatda bitta bo'lsa to'g'ri o'sha biznesga,
bir nechta bo'lsa almashtirgichni ko'rsating.

## 9. Frontda qilinadigan ishlar

| # | Ish | Qayerda |
|---|---|---|
| 1 | API qatlami: `packages/api/src/businesses.ts` + ko'prik + mock | `packages/api` |
| 2 | Biznes almashtirgich (yuqori panel): `GET /businesses`, tanlangan biznes `id` si saqlanadi | `apps/cabinet/src/shell.tsx` |
| 3 | Tanlangan biznesdan eski ekranlarga o'tish: `networks[0].pair` ni mavjud `?pair=` ga bering; ega uchun kerak bo'lsa `POST /api/v1/connections/meta/switch/pair` | dashboard, CRM, lidlar |
| 4 | Sozlamalar → «Xodimlar» sahifasi: ro'yxat, joylar ko'rsatkichi, qo'shish (yangi login / mavjud odam), rol va ruxsat jadvali, o'chirish | `apps/cabinet/src/pages/settings` |
| 5 | Ruxsat jadvali: qatorlar — `networks` + «Boshqa manba»; ustunlar — Reklama, CRM; katak — yo'q / ko'rish / o'zgartirish | o'sha yerda |
| 6 | Xodim logini uchun kirish oqimi: bizneslar ro'yxati → biznes; ruxsati yo'q bo'limlar yashiriladi (`may()` funksiyasi) | `apps/cabinet` |
| 7 | Xato kodlari bo'yicha yo'naltirish (`no_seat`, `sales_through_crm`) | o'sha yerda |

## 10. Hali yo'q narsalar

Bular keyingi bosqichlarda chiqadi; hozir ularga tayanib ekran qurmang.

- **Reklama yo'llari xodim uchun.** Targetolog qo'shiladi va biznesni ko'radi, lekin
  kampaniyalar yo'llari (`/api/v1/campaigns`, `/api/v2/…`) xodim loginiga hali yopiq.
  Ya'ni targetolog hozircha reklamani boshqara olmaydi.
- **CRM biznes bo'yicha.** CRM hali `/api/v1/crm` da va juftlik bo'yicha ishlaydi. Bitta
  odam CRM'da faqat bitta juftlikda ishlay oladi.
- **ROP ko'rinishi.** `reads_all_leads` belgisi keladi, lekin CRM hali uni hisobga olmaydi.
- **Sotuv managerini v3 dan qo'shish** va **profilni v3 dan tahrirlash**.
- **Yangi biznes yaratish.** Biznes hozircha sahifa ulanib, juftlik va profil saqlanganda
  o'zi paydo bo'ladi.
- **AI chat, hisobot, bot** hali juftlik bo'yicha.
- Ruxsat o'zgarishlari tarixga (audit) hali yozilmaydi.
