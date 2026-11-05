# CRM integratsiyalari va CAPI — ish rejasi

Holat: reja, kod hali yozilmagan. Tuzilgan sana: 2026-11-01.

Maqsad: mijoz qaysi CRM'da ishlashidan qat'i nazar, lidning sifati tunda Meta'ga
borsin va dashboard'da ko'rinsin.

Fokus: **ichki CRM, amoCRM/Kommo, Bitrix24, Custom CRM**. HubSpot keyinga qoldi.

Har etap oxirida shu faylning «Yurish jadvali» bo'limi yangilanadi.

---

## 1. Qat'iy qarorlar

Ish davomida qayta muhokama qilinmaydi. O'zgartirish faqat egasi bilan.

| # | Qaror |
|---|---|
| 1 | Har CRM o'z paketida. `packages/*` ichida framework yo'q: faqat stdlib, `httpx`, `pydantic`. `fastapi`, `sqlalchemy`, `celery`, `app.*` importi taqiqlanadi. |
| 2 | `crmkit` umumiy kontrakt. U bilan ishlaydi: `amocrmkit`, `bitrixkit`, `customcrmkit`. Qolgan ilova faqat `crmkit`ni biladi; aniq paket nomi faqat `app/bootstrap.py`da. |
| 3 | Meta'ga bitta yo'l: `lead_signals` navbati va bitta tungi yuborish. Boshqa yuborish yo'li qolmaydi. |
| 4 | Bitta juftlik (sahifa + reklama akkaunti), bitta signal manbasi. |
| 5 | Lid CRM'ga standart holatda yozilmaydi. Yozish alohida sozlama va o'chiq turadi. |
| 6 | Telefon raqam CRM'dan olinib saqlanmaydi: faqat xotirada solishtiriladi. |
| 7 | Hech bir yuborishda hodisa vaqti soxtalashtirilmaydi. 7 kundan eski signal `expired` bo'ladi. |
| 8 | Dashboard'da narx (CPQL) chiqmaydi, mavjud mahsulot qoidasi saqlanadi. |
| 9 | Tarif cheklovi qo'yilmaydi: CRM hamma uchun ochiq qoidasi amal qiladi. |
| 10 | Kabinet API va front eng oxirgi etapda. |

### Custom CRM adapteri qanday tushunildi

Custom CRM ham amoCRM kabi oddiy provayder bo'ladi, faqat protokolni biz yozamiz:

- **Pull rejimi (`customcrmkit` adapteri).** Mijoz o'z tomonida bizning hujjat
  bo'yicha bir nechta endpoint ochadi, adapter ularni tunda o'qiydi. Voronka va
  ustun tanlash ekrani amoCRM bilan bir xil ishlaydi.
- **Push rejimi (ochiq API).** Endpoint ochishning iloji bo'lmagan mijoz natijani
  o'zi `POST /crm-api/v1/events` bilan yuboradi.

Ikkala rejim bitta `ingest` funksiyasiga tushadi. Tanlovni mijoz qiladi.

---

## 2. Tuzilma

```
packages/crmkit            kontrakt: port, DTO, xatolar, registry
packages/amocrmkit         amoCRM va Kommo
packages/bitrixkit         Bitrix24
packages/customcrmkit      Custom CRM pull protokoli

app/modules/crmlinks       ulanish, voronka, tungi o'qish, moslash, ochiq API
app/modules/leads          lead_signals navbati va Meta'ga yuborish
app/modules/crm            ichki doska, navbatga yozadi
app/modules/metrics        CAPI raqamlari dashboard uchun

core/leads/reporting.py    sof qoidalar: qachon, nima yuboriladi
core/crm/matching.py       sof qoida: bitim qaysi lidga tegishli
```

Oqim:

```
01:40  sweep_crm_links_task      CRM o'qiladi, bitim lidga bog'lanadi, navbatga yoziladi
kun    ichki CRM, qo'lda belgilash, push API  navbatga yozadi
02:40  sweep_lead_signals_task   navbat Meta'ga yuboriladi
04:08  sync_all_pixel_events     Meta'dan qabul qilingan son o'qiladi (mavjud)
```

Vaqtlar egasining soatida (`owner_clocks`, `owners_at_hour`). Beat har soat ishlaydi.

---

## 3. Boshlashdan oldin kerak (0-etap)

### Egasining javobi

- [ ] `QUALITY_LEAD`ni hozir yoqamizmi? Tavsiya: yo'q. Avval signal yig'iladi.
      `core/targeting/quality.py` `is_available` doim `False`. Bu yoqilmaguncha
      hodisa reklama xaridini o'zgartirmaydi.
- [ ] Xom lid hodisasini yuboramizmi? Tavsiya: ha. Meta barcha bosqichni, jumladan
      boshlang'ichni so'raydi. `adskit/refs.py`dagi izoh buni ataylab taqiqlagan,
      shuning uchun bu egasining qarori bilan o'zgaradi.
- [ ] Mijozlar `amocrm.ru`da yoki `kommo.com`da? `platform` 1 va 2 ni qaytaradi;
      bitta integratsiya ikkalasida ishlashi tasdiqlanmagan.

### Tashqi hisoblar

- [ ] amoCRM hisobi va External integration: `client_id`, `client_secret`,
      `redirect_uri` = `https://targetolog.ai/api/v1/connections/crm/amocrm/callback`.
- [ ] Sinov amoCRM akkaunti.
- [ ] Bitrix24 partner hisobi va **mass-market** ilova. Local ilova faqat bitta
      portalda ishlaydi va boshqa portalga o'rnatilmaydi.
- [ ] Bitrix24 sinov portali. Moderatsiyaga test kirish talab qilinadi.
- [ ] Meta sinov piksellari, Events Manager'dagi test kodi.

### Texnik boshlang'ich

- [ ] Fresh dump bilan staging yangilanadi, raqamlar qayta o'lchanadi (5-bo'lim).
- [ ] `main` 11 commit `origin/main`dan oldinda: push qilinadimi, hal qilinadi.
- [ ] `feat/audience-and-center` migratsiyasi `0010` bor. Birinchi migratsiya
      yozishdan oldin `alembic heads` tekshiriladi. Raqam shundan keyin beriladi.

Bitrix24 moderatsiyasi 1-3 ish kuni deyilgan, boshqa manbada muddat belgilanmagan,
rad etish ham mumkin. Shu sababli moderatsiya 5-etap kodi bilan parallel boshlanadi.

---

## 4. Ishlash qoidalari

- Bir etap, bir branch: `feat/crm-1-kits`, `feat/crm-2-signals` va hokazo.
  Egasi ko'rib chiqmaguncha keyingisi boshlanmaydi.
- Avval yiqiladigan test, keyin kod.
- Etap tugashi uchun: testlar, `ruff`, `mypy` o'tadi va har da'vo kodga solishtiriladi.
- Migratsiya idempotent, ORM modelga bog'lanmaydi, ma'lumot o'chirmaydi.
- `deploy/copy-db.sh` va `DROP DATABASE` hech qachon ishlatilmaydi.
- Meta'ga yozish `ADS_DRY_RUN` ostida. Rehearsal paytida qator `pending` qoladi.
- Token, kalit, telefon logga tushmaydi.
- Xato xabarlari uch tilda: uz, ru, en.
- Paket o'zgarsa, `CHANGELOG.md` va versiya yangilanadi.
- Yangi jadval uchun: akkaunt o'chirish yo'li (`backoffice/services/accounts.py`
  `delete_account`, `app/common/deletion.py`) tekshiriladi va test qo'shiladi.

---

## 5. O'lchangan boshlang'ich holat

Staging, dump 2026-10-29. Production emas. 0-etapda qayta o'lchanadi.

| Ko'rsatkich | Qiymat |
|---|---|
| Yoqilgan CRM juftliklari | 37 (23 ega) |
| Faol piksel bor juftliklar | 7 / 37 |
| Faol Meta akkauntlari | 268 (215 ega) |
| Faol pikselli akkauntlar | 43 |
| Pikseli bor, lekin faol emas | 22 |
| Bir nechta faol akkauntli egalar | 33 |
| Kartalar / sifatli / Meta'ga yuborilgan | 424 / 89 / 57 |
| `lead_outcomes` qatorlari | 0 |
| 30 kunlik lidlar | 51 766 |
| Telefonli | 37 800 (73%) |
| Emailli | 46 |

---

## 6. Etaplar

### 1-etap. `crmkit` va `amocrmkit`

Branch: `feat/crm-1-kits`. Ilova kodi o'zgarmaydi.

**`crmkit` tarkibi**

| Fayl | Mazmuni |
|---|---|
| `ports.py` | `CrmPort` protokoli |
| `dto.py` | `Grant`, `AccountInfo`, `Funnel`, `Stage`, `Deal`, `StageChange`, `ChangesPage`, `NewDeal` |
| `refs.py` | `ProviderName`, `StageSemantic` (`open`, `won`, `lost`), `Capability` |
| `errors.py` | `CrmError`, `AccessRevoked`, `RateLimited`, `AccountUnpaid`, `Unavailable`, `InvalidAnswer`, `OutcomeUnknown` |
| `registry.py` | `paykit/registry.py` naqshi: `register`, `get`, `available`, `clear` |

**`CrmPort` metodlari**

| Metod | Vazifasi |
|---|---|
| `authorize_url` | Mijozni CRM ruxsat oynasiga yuboradi |
| `exchange` | Kodni `Grant`ga almashtiradi |
| `refresh` | Yangi `Grant` qaytaradi, eski refresh token bekor deb hisoblanadi |
| `account` | Barqaror akkaunt id, manzil, valyuta |
| `funnels` | Voronkalar |
| `stages` | Voronka bosqichlari va ma'nosi |
| `stage_changes` | `cursor`dan keyingi o'zgarishlar va keyingi `cursor` |
| `deals` | Id bo'yicha bitimlar: telefon, summa, valyuta, joriy bosqich |
| `create_deal` | Faqat `Capability.CREATE_DEAL` bo'lsa |
| `revoke` | Uzish, imkon bo'lsa |

`stage_changes` port ichidagi eng muhim metod: provayder tarixi har xil, ilova
faqat `StageChange` ko'radi. Sahifalash `cursor` bilan, ilova uni har sahifadan
keyin saqlaydi.

**`amocrmkit` tarkibi**

| Fayl | Mazmuni |
|---|---|
| `oauth.py` | `https://www.amocrm.ru/oauth`, `/oauth2/access_token`, `referer` tekshiruvi |
| `transport.py` | Bearer, 401/402/403/429/504 xaritasi, soxta transport bilan testlanadi |
| `pipelines.py` | `/api/v4/leads/pipelines`, `.../statuses`; 142 = won, 143 = lost |
| `leads.py` | ro'yxat, olish, `leads/complex` (50 tagacha), `PATCH` |
| `contacts.py` | `query` qidiruvi, `with=leads`, `PHONE` maydoni |
| `events.py` | `/api/v4/events`, `lead_status_changed`, `lead_added`, sahifa 100 |
| `webhooks.py` | obuna va o'qish. Ilova hozircha ishlatmaydi |
| `adapter.py` | `CrmPort` amalga oshirilishi |

Testlar: `tests/packages/test_crmkit_*.py`, `test_amocrmkit_*.py`, `httpx.MockTransport`.

Tuzoqlar:

- `referer` faqat `*.amocrm.ru`, `*.amocrm.com`, `*.kommo.com`. Bo'lmasa
  `client_secret` begona serverga ketadi.
- Kod 20 daqiqa yashaydi.
- Refresh token faqat bir marta ishlaydi.
- Status bilan yaratilgan bitim `lead_status_changed` bermaydi, `lead_added`
  ham o'qiladi. Sinov akkauntida tasdiqlanadi.
- `query` telefon formatiga sezgirligi hujjatda aniq emas, sinovda tekshiriladi.
- 402 da yozish darhol to'xtaydi, o'qish 30 kungacha ishlaydi.
- 429 ko'p takrorlansa akkaunt 403 bilan bloklanadi: orqaga chekinish majburiy.

**Tugash mezoni:** port amoCRM, Bitrix24 hujjatiga solishtirilgan; `amocrmkit`
testlari o'tadi; `pyproject.toml` workspace'ga qo'shilgan; import tekshiruvi
paketda framework yo'qligini tasdiqlaydi.

---

### 2-etap. Yagona Meta navbati

Branch: `feat/crm-2-signals`. Migratsiya A.

**`lead_signals` jadvali**

| Ustun | Izoh |
|---|---|
| `id`, `created_at`, `updated_at` | Standart |
| `owner_id` | FK `users` |
| `lead_id` | FK `leads`, `CASCADE` |
| `ad_account_id` | Qaysi akkauntning pikseliga boradi |
| `stage` | `qualified`, `unqualified`, `converted` (0-etap javobiga qarab `received`) |
| `source` | `internal`, `amocrm`, `bitrix24`, `custom`, `manual` |
| `source_ref` | CRM bitim id, tekshirish uchun |
| `occurred_at` | Bosqich haqiqatda o'zgargan vaqt |
| `value_minor`, `currency` | Faqat `converted` |
| `status` | `pending`, `sent`, `expired`, `failed`, `withdrawn` |
| `sent_at`, `attempts` | |
| `dataset_id`, `trace_id`, `last_error` | Meta javobi |

Unique: `(lead_id, stage)`. Index: `(owner_id, status)`, `(status, occurred_at)`.

**Yuborish tartibi `report_signals`**

1. `pending` qatorlar `ad_account_id` bo'yicha guruhlanadi.
2. `reporting_dataset` yo'q bo'lsa, qator `pending` qoladi, sabab hisobga olinadi.
3. Token olinadi. Ishlamasa, keyingi tun.
4. Filtrlar qayta tekshiriladi: test, organik, anonimlashgan, `leadgen_id` bo'sh.
5. `occurred_at` 7 kunlik chegaraga xavfsiz zaxira bilan solishtiriladi. Eskisi `expired`.
6. `occurred_at` `submitted_at`dan oldin bo'lmasligi ta'minlanadi.
7. Paket yuboriladi. Paket 200 tadan: Meta paketni butunlay rad etadi.
8. Rad etilsa, paket ikkiga bo'linadi. Bitta qatorga tushsa, `failed` va `last_error`.
9. `accepted` paket uzunligidan kam bo'lsa, log yoziladi.
10. Muvaffaqiyatda `sent`, audit hodisasi `CRM_QUALITY_SENT`.

**O'zgaradigan kod**

| Joy | O'zgarish |
|---|---|
| `leads/services/__init__.py` `report_outcomes`, `sweep_lead_verdicts` | Olib tashlanadi, `report_signals`, `sweep_lead_signals` keladi |
| `leads/schedule.py` | «Lid natijalarini Meta'ga yuborish» o'rniga soatlik `40` daqiqada |
| `leads/services` `mark_outcome`, `clear_outcome` | Navbatga yozadi va `pending`ni bekor qiladi |
| `leads/selectors/reads.py` `qualified_since` | `lead_signals`dan hisoblaydi, barcha manba |
| `metaads/conversions.py` izohi | 200 degan noto'g'ri da'vo tuzatiladi |
| `app/bootstrap.py`, `env.py` | `META_CONVERSIONS_TEST_CODE` ulanadi |
| `core/leads/reporting.py` | Oyna zaxirasi, bosqich tartibi, `converted` oldidan `qualified` qoidasi |

Migratsiya: `quality_sent_at` to'la kartalar `lead_signals`ga `sent` bo'lib ko'chadi
(xom SQL, staging'da 57 ta). Tarixni saqlaydi, qayta yuborishga olib kelmaydi.

Testlar: bir nechta akkauntli ega, piksel yo'q, eski hodisa, yomon qator bo'linishi,
dry-run, takroriy ishga tushirish, migratsiya ikki marta.

Tuzoq: beat'dan olib tashlangan vazifa RedBeat'da qolmasligi tekshiriladi
(`tests/test_beat_schedule.py`).

**Tugash mezoni:** Meta'ga yuboradigan yagona joy `report_signals`, bu `grep` bilan
tasdiqlanadi; har lid o'z akkauntining pikseliga boradi; Meta Test Events'da bitta
hodisa ko'rindi.

---

### 3-etap. Ichki CRM

Branch: `feat/crm-3-internal`. Migratsiya B.

**Ma'lumot:** `crm_stages.counts_as_unqualified` (bool, default false).

**Qoidalar**

| Ustun turi | Sifatli | Sifatsiz |
|---|---|---|
| `new` | yo'q | yo'q |
| `open` | ha | ha |
| `won` | ha, doim `converted` ham | yo'q |
| `lost` | yo'q | ha |

Bitta ustun ikkala belgida bo'lmaydi. Sabab bo'yicha emas, ustun bo'yicha belgilanadi.

**O'zgaradigan kod** (`crm/services/__init__.py`)

| Funksiya | O'zgarish |
|---|---|
| `save_quality` | Sifatsiz ro'yxatni ham qabul qiladi, tekshiradi, audit yozadi |
| `enable_crm` | Xuddi shu |
| `move_card` | Sifatli va sifatsiz belgisini navbatga yozadi |
| `take_card` | Xuddi shu |
| `win_card` | `qualified` va `converted`, summa bilan |
| `lose_card` | Rad etildi ustuni belgilangan bo'lsa `unqualified` |
| Qayta ochish | Kun tugamagan `pending` tekshiruvi tun paytida ishlaydi |

**Tunda tekshirish:** `internal` signal yuborilishidan oldin karta joriy holatga
solishtiriladi. Karta shu ustunda bo'lmasa, qator `withdrawn`. Shunday kunduzgi xato
Meta'ga bormaydi.

**Manba qoidasi:** juftlikda tashqi voronka saqlangan bo'lsa, ichki doska yozmaydi.
Bu yerda tekshiruv tayyor turadi, ishlatilishi 4-etapda.

**Tugash mezoni:** kartaning har yo'li test bilan yopilgan; `sent_to_meta` tarixga
yoziladi; `CRM_API.md` eslatmasi yangilangan.

---

### 4-etap. `crmlinks` moduli va amoCRM ulanishi

Branch: `feat/crm-4-links`. Migratsiya C.

**Modul tuzilmasi:** `models/`, `constants.py`, `exceptions.py`, `selectors/`,
`services/`, `tasks.py`, `schedule.py`. Router bu etapda yo'q.

**Jadvallar**

`crm_links` — ulanish:

| Ustun | Izoh |
|---|---|
| `owner_id`, `provider` | Unique, bitta egada bitta provayder bitta marta |
| `external_account_id` | amoCRM id yoki Bitrix `member_id` |
| `base_url`, `account_name`, `currency` | |
| `token_encrypted`, `refresh_encrypted` | `app/common/crypto.py` |
| `expires_at` | |
| `status` | `active`, `broken`, `unpaid`, `disconnected` |
| `broken_reason`, `last_error_code` | |
| `cursor` | CRM o'qish joyi |
| `last_synced_at`, `last_ok_at` | |
| `mode` | `oauth`, `pull`, `push` |

`crm_link_funnels` — juftlik sozlamasi:

| Ustun | Izoh |
|---|---|
| `link_id`, `owner_id`, `page_id`, `ad_account_id` | Unique juftlik |
| `funnel_id`, `funnel_kind` | Bitrix uchun `deal` yoki `lead` |
| `verdicts` | Bosqich → `qualified`, `sold`, `unqualified`, `unworked` |
| `writes_leads` | Default false |
| `enabled_at` | |

`crm_deals` — bog'lanish:

| Ustun | Izoh |
|---|---|
| `link_id`, `external_id` | Unique |
| `owner_id`, `lead_id` | Lid NULL bo'lishi mumkin |
| `matched_by` | `phone`, `pushed`, `lead_id` |
| `stage_id`, `amount_minor`, `currency` | |
| `url`, `seen_at` | |

Shaxsiy ma'lumot ustuni yo'q.

**Xizmatlar**

| Fayl | Vazifasi |
|---|---|
| `services/tokens.py` | `valid_token`: `SELECT FOR UPDATE`, muddati yaqin bo'lsa yangilaydi, shu tranzaksiyada saqlaydi |
| `services/connect.py` | ulash, qayta ulash, uzish |
| `services/funnel.py` | voronka va bosqich belgilarini saqlash |
| `services/read_link.py` | bitta ulanishning tungi o'qishi |
| `services/ingest.py` | **yagona kirish**: `StageChange` → moslash → `crm_deals` → `lead_signals` |
| `services/write_lead.py` | `writes_leads` yoqiq bo'lsa, bitim yaratish |

**O'qish qoidalari**

- Harakat `cursor`dan davom etadi, har sahifadan keyin `commit`.
- Vazifa `task_time_limit=600` bilan ishlaydi. Vaqt tugasa, o'zini davom ettiradi.
- Tezlik chegarasi Redis'da, umumiy deb hisoblanadi: amoCRM 7 so'rov/soniya.
- Beat `01:40`: `owners_at_hour` bilan.
- Refresh tokenning 3 oylik muddati tungi o'qish bilan yashab turadi. Ulanish
  uzilsa `broken`, `NoticeKind.CONNECTION` xabari.

**Moslash qoidalari** (`core/crm/matching.py`)

1. Telefon E.164 ga keltiriladi (`phonenumbers`).
2. Shu ega lidlari orasidan, juftlik sahifasi bo'yicha qidiriladi.
3. O'zgarish vaqtidan oldin kelgan eng yangi lid olinadi, 30 kun ichida.
4. Avval `pushed` bog'lanishi tekshiriladi, keyin telefon.
5. Topilmasa, `crm_deals.lead_id` bo'sh, «topilmadi» hisobiga tushadi.

**Bosqich qoidalari**

- Kun tugagan, bitim hali shu darajada: signal yoziladi.
- `sold` oldin `qualified` ham yozadi.
- Bitim bir kunda sifatlidan sifatsizga o'tsa, faqat sifatsiz yoziladi.
- Yuborilgan signal qaytarib olinmaydi.
- Yangi ulanishda eski tarix o'qilmaydi: `cursor` 7 kundan eski emas.
- Bitim yopilgani summa bilan: `converted` valyuta CRM akkauntidan olinadi.

**Infratuzilma:** `app/worker.py`ga `crm` navbati, `compose.yaml`ga
`worker-crm` (`--concurrency 2`). Celery vaqtida bitta navbatni to'ldirib qo'ymaslik
uchun ega bo'yicha alohida vazifa.

**Tartib:** `crm_link_funnels` bor juftlikda ichki doska signal yozmaydi.
`app/modules/crm` buni `crmlinks.selectors.signal_source` orqali o'qiydi.

**Sozlama:** `CRM_LINKS_ENABLED`, `CRM_LINKS_USERS`, `AMOCRM_CLIENT_ID`,
`AMOCRM_CLIENT_SECRET`. `.env.example`ga qo'shiladi.

Testlar: `tests/pg/`da bir vaqtda ikki token yangilash, uzish, 401, 402, 429,
sahifa o'rtasida to'xtash, bir telefon ikki lid, ikki juftlik bitta voronka,
akkaunt o'chirish.

**Tugash mezoni:** sinov amoCRM akkauntida haqiqiy bitim ko'chirildi, tunda lidga
bog'landi, Meta Test Events'da paydo bo'ldi.

---

### 5-etap. Bitrix24

Branch: `feat/crm-5-bitrix`. Migratsiya kerak emas.

**Bu etap kontraktning sinovi.** `crmlinks` ichida `if provider == "bitrix24"`
paydo bo'lsa, kontrakt tuzatiladi.

**`bitrixkit` tarkibi**

| Fayl | Mazmuni |
|---|---|
| `oauth.py` | `https://portal/oauth/authorize/`, `https://oauth.bitrix.info/oauth/token/` |
| `transport.py` | `client_endpoint`, `QUERY_LIMIT_EXCEEDED` (503), `start` sahifalash |
| `funnels.py` | `crm.category.list`, `crm.status.list` (`DEAL_STAGE`, `DEAL_STAGE_{id}`) |
| `items.py` | `crm.item.*`, zarur joyda `crm.deal.*`, `crm.contact.*` |
| `history.py` | `crm.stagehistory.list` (`entityTypeId` 1 va 2) |
| `events.py` | hodisalarga obuna, ilova hozircha ishlatmaydi |
| `adapter.py` | `CrmPort` |

Farqlar:

- Kod **30 soniya** yashaydi: callback ichida sinxron almashtiriladi, Celery'ga
  o'tkazilmaydi. Bu qoida 8-etapdagi umumiy callback uchun ham to'g'ri.
- Access token 1 soat, refresh 180 kun.
- Bitrix'da Lead ham, Deal ham voronka. Mijoz qaysi birida ishlashi `funnel_kind`.
- Bosqich ma'nosi: `P`, `S`, `F` → `open`, `won`, `lost`.
- Tarix qatori: `TYPE_ID` 1 yaratilish, 2 oraliq, 3 yakuniy, 5 voronka almashishi.
- Filter `CREATED_TIME` hujjatda aniq emas: sinov portalida tekshiriladi.
- Sahifa 50 ta, chegara tarifga va IP'ga bog'liq, hamma mijoz bitta server IP'dan.

Ilova **mass-market** bo'ladi. Dasturchi moderatsiyasiz sinov portaliga o'rnata oladi.
Marketplace'ga chiqish `CRM_LINKS_USERS` cheklovini olish sharti.

**Tugash mezoni:** sinov portalida Deal va Lead ikkalasi ham lidga bog'lanib, Meta
Test Events'ga yetdi; `crmlinks`da provayder sharti yo'q.

---

### 6-etap. Custom CRM: adapter, ochiq API, hujjat

Branch: `feat/crm-6-custom`. Migratsiya D.

**`packages/customcrmkit`**

Adapter «TargetologAI CRM Protocol v1» bo'yicha mijoz serveridan o'qiydi:

| Mijoz endpointi | Vazifasi |
|---|---|
| `GET /funnels` | Voronkalar |
| `GET /funnels/{id}/stages` | Bosqichlar va ma'nosi |
| `GET /stage-changes?cursor=` | Yangi o'zgarishlar |
| `GET /deals?ids=` | Telefon yoki bizning `lead_id` |
| `POST /deals` | Ixtiyoriy, `CREATE_DEAL` |
| `GET /health` | Ulanish tekshiruvi |

Ulanishda mijoz manzil va kalit beradi, kalit shifrlanib saqlanadi.

**Xavfsizlik, chunki biz begona manzilga so'rov yuboramiz (SSRF)**

- Faqat `https`.
- Har so'rovda DNS tekshiriladi, ichki va maxsus IP'lar rad etiladi.
- Redirect kuzatilmaydi.
- Timeout, javob hajmi chegarasi, sxema tekshiruvi.
- `customcrmkit` shu qoidalarni o'zi bajaradi, ilovaga ishonmaydi.

**Ochiq API `/crm-api/v1`**

`public_router`da, JWT'siz, alohida kalit bilan. Baza: `crm_api_keys` va
`crm_webhook_deliveries`.

| Endpoint | Vazifasi |
|---|---|
| `GET /leads?cursor=` | Lidlar: id, ism, telefon, forma, vaqt |
| `GET /leads/{id}` | Bitta lid |
| `POST /events` | Natijalar, 100 tagacha, har qatorga alohida javob |
| `GET /events/{external_id}` | Yuborilgan holat |
| `GET /me` | Kalit tekshiruvi |

`POST /events` qatori: `lead_id` yoki `phone`, `stage`, `occurred_at`, `external_id`,
`value`, `currency`. Javob holatlari: `queued`, `duplicate`, `expired`,
`unknown_lead`, `invalid`.

Qoidalar:

- Kalit `tgcrm_live_...` va `tgcrm_test_...`, bir marta ko'rinadi, SHA-256 bilan saqlanadi.
- Kalit juftlikka bog'langan: boshqa juftlik lidi `unknown_lead`.
- `throttle.py` bilan kalit bo'yicha chegara.
- Test kaliti soxta lid beradi, Meta'ga hech narsa bormaydi.
- Natija `ingest` orqali o'tadi.
- Telefon bo'yicha moslashda 4-etap qoidasi ishlaydi.

**Chiquvchi webhook:** `lead.created`, HMAC-SHA256 imzo, vaqt belgisi, qayta urinish
(1 daqiqa, 5 daqiqa, 30 daqiqa, 2 soat, 12 soat), SSRF qoidalari, ketma-ket
xatolarda to'xtatish va xabar.

**Hujjat:** `docs/custom-crm/` ichida, 8-etapda saytga chiqadi.

| Bo'lim | Mazmuni |
|---|---|
| Tez boshlash | 15 daqiqada birinchi hodisa |
| Rejim tanlash | Push yoki pull, qaysi biri kimga |
| Kalit | Olish, saqlash, almashtirish |
| Lidlarni olish | API va webhook, imzoni tekshirish |
| Natija yuborish | Bosqichlar ma'nosi, summa, valyuta |
| Protokol v1 | Pull endpointlari, javob sxemalari |
| 7 kun qoidasi | Nega kechikkan signal olinmaydi |
| Xatolar | Kodlar va amallar |
| Sinov | Test kaliti, tekshiruv ro'yxati |
| Misollar | curl, PHP, Python, JavaScript |
| Versiyalash | O'zgarish qoidasi, changelog |

OpenAPI faqat `/crm-api` routeridan alohida chiqariladi: kabinet API sizib chiqmaydi.

**Tugash mezoni:** hujjatni o'qib, alohida kichik namuna skript push va pull
rejimida ishladi; imzo, kalit, chegara, SSRF testlari o'tadi.

---

### 7-etap. CAPI hisob-kitobi va ogohlantirishlar

Branch: `feat/crm-7-capi`. Router bu etapda ham yo'q.

`app/modules/metrics/selectors/lead_quality.py` juftlik va davr bo'yicha:

| Maydon | Manba |
|---|---|
| `crm` | Faol manba bormi |
| `source` | `internal`, `amocrm`, `bitrix24`, `custom` |
| `leads` | Davrdagi lidlar |
| `marked` | Biror natija olgan lidlar |
| `qualified`, `unqualified`, `sold` | `lead_signals` |
| `sent` | `status = sent` |
| `pending`, `expired`, `failed` | `lead_signals` |
| `not_found` | `crm_deals.lead_id` bo'sh |
| `accepted_by_meta` | `pixel_accounts.recent_events` |
| `last_sent_at` | |
| `problem` | Bitta eng muhim sabab |

Sabablar tartibi: `no_pixel`, `link_broken`, `meta_connection`, `no_marks`,
`low_match`, `none`.

Piksel:

- Yagona piksel `integrations/services/sync.py`da allaqachon o'zi tanlanadi.
- 22 ta akkauntda piksel bor, lekin faol emas. Bir nechta piksel bo'lgani uchun
  tanlanmagan bo'lishi mumkin, bu o'lchanadi. Tasdiqlansa, egasiga tanlash
  so'raladi, tizim o'zi tanlamaydi: noto'g'ri pikselga ketgan signal qaytmaydi.
- Pikseli umuman yo'q akkauntga Events Manager'ga yo'l ko'rsatiladi. `metaads`da
  piksel yaratish yo'q, bu rejaga kirmaydi.

Bildirishnoma: `broken`, piksel yo'q, past moslik, custom CRM N kun jim. Har biri
markazga tushadi, bir holat bir marta.

Kunlik hisobotga `sent_by_page` qatori: Django'dagi hisobotda bor edi, FastAPI'da
ko'rib chiqiladi.

**Tugash mezoni:** hisob har manbada bir xil natija beradi; selector soni bilan
Events Manager soni solishtirilgan.

---

### 8-etap. Kabinet API, Front, yoqish

Backend branch: `feat/crm-8-api`. Front branch: shu nom bilan frontend reposida.

**Backend**

Router `integrations`dan **oldin** ulanadi: `/connections/{net}` yo'llari yutib
yubormasin.

| Yo'l | Vazifasi |
|---|---|
| `GET /connections/crm?pair=` | Provayderlar, voronkalar, bosqichlar, moslik |
| `PUT /connections/crm?pair=` | `funnelId`, `stages` |
| `POST /connections/crm/sync?pair=` | Qo'lda o'qish, chegaralangan |
| `POST /connections/crm/{id}/start` | Ruxsat oynasi |
| `GET /connections/crm/{id}/callback` | Kod almashtirish, JWT'siz, `state` Redis'da |
| `POST /connections/crm/{id}/disconnect` | Uzish |
| `POST /connections/crm/custom/keys` va tegishlilari | Kalit, webhook, sinov, oxirgi hodisalar |
| `POST /crm/settings/quality` | Sifatsiz ro'yxat qo'shiladi |
| `GET /metrics/numbers` | `lead_quality` qo'shiladi |
| `GET /leads/{id}` va lid manbalari | `crm` bloki |

Nginx: `/api/` allaqachon backendga boradi, `/crm-api/` qo'shiladi.

**Front** (`targetolog-ai-frontend`)

| Joy | O'zgarish |
|---|---|
| `packages/api/src/features.ts` | `crmLinks`ni `PENDING`dan olish |
| `packages/api/src/live/pending.ts` | `connections/crm` soxtasini olish |
| `packages/api/src/live/bridges/dashboard.ts:256` | `leadQuality: null` o'rniga jonli qiymat |
| `packages/api/src/connections.ts` | `?pair=`, custom turlari, `gen/openapi.ts` |
| `apps/cabinet/src/pages/settings/Crm.tsx` | Juftlik tanlovi, «hech narsa yozmaymiz» jumlasi `writesLeads` bilan to'g'rilanadi, Custom bo'limi |
| `apps/cabinet/src/pages/settings/status.ts:105` | «Tez orada» olinadi |
| `apps/cabinet/src/pages/dashboard/LeadQuality.tsx` | Manba, muammo, jumlalar `QUALITY_LEAD` yo'q paytga moslanadi, «CRM'ni ochish» tashqi CRM uchun |
| `apps/cabinet/src/pages/dashboard/Figures.tsx` | «CRM yoqilmagan» tashqi CRM'ni ham hisobga oladi |
| `apps/cabinet/src/pages/crm/blocks.tsx` `QualityFields`, `Settings.tsx`, `Setup.tsx` | Sifatsiz tanlov |
| `apps/cabinet/src/pages/leads/*` | `crm` bloki, `qualifiedCost` chiqmaydi |
| `apps/site/app/routes/` | Hujjat sahifasi |
| `packages/i18n` | uz, ru, en |

**Hujjatlar:** `CRM_API.md`, `DASHBOARD_API.md`, `ARXITEKTURA.md`,
`FRONTEND_INTEGRATSIYA.md`.

**Yoqish tartibi**

1. `targetolog-api:prev` image tegi saqlanadi.
2. Migratsiyalar, deploy, `worker-crm` ishga tushadi.
3. `ADS_DRY_RUN` holati tekshiriladi.
4. Staging'da to'liq yo'l: ichki CRM, amoCRM, Bitrix24, Custom push, Custom pull.
5. Meta Test Events.
6. `CRM_LINKS_USERS` bilan bitta akkauntda haqiqiy tun.
7. Ertalab Events Manager, dashboard, loglar solishtiriladi.
8. Bir necha mijoz, keyin hamma.

**Tugash mezoni:** barcha ekranlar brauzerda ko'rilgan, soxta bridge qolmagan,
dashboard raqami Events Manager bilan mos.

---

## 7. Provayder farqlari

| | amoCRM | Bitrix24 | Custom |
|---|---|---|---|
| Ruxsat | External integration | Mass-market ilova, moderatsiya | Kalit |
| Kod muddati | 20 daqiqa | 30 soniya | yo'q |
| Access token | `expires_in`, namunada 24 soat | 1 soat | Doimiy kalit |
| Refresh | 3 oy, bir martalik | 180 kun | yo'q |
| Akkaunt id | `/api/v4/account` | `member_id` | Ulanish id |
| Manzil | `referer` | `client_endpoint` | Mijoz beradi |
| Tarix | `/api/v4/events` | `crm.stagehistory.list` | `/stage-changes` yoki push |
| Sahifa | Hodisa 100, bitim 250 | 50 | Protokolda belgilanadi |
| Chegara | 7 so'rov/s, 50 akkauntga | Tarif va IP bo'yicha | Bizning limit |
| Yozuvni rad etish | 402 | Tekshiriladi | Protokol xatosi |

## 8. Bu rejaga kirmaydi

- HubSpot, Zoho, Pipedrive, Salesforce. Yangi paket qo'shish yetadi.
- `QUALITY_LEAD`ni yoqish, 0-etap javobi boshqacha bo'lmasa.
- Meta'da piksel yaratish.
- amoCRM va Bitrix24 real vaqt webhooklari: paketda bor, ilova ishlatmaydi.
- Sayt lidlari: Meta bu oqimni faqat lid reklamalari uchun qabul qiladi.

## 9. Yurish jadvali

| Etap | Holat | Branch | Commit | Izoh |
|---|---|---|---|---|
| 0. Tayyorgarlik | Kutilmoqda | | | |
| 1. `crmkit`, `amocrmkit` | Boshlanmagan | | | |
| 2. Meta navbati | Kod tayyor, commit yo'q | `feat/crm-capi` | | `lead_signals`, tungi yuborish; xom lid ham ketadi; haqiqiy Meta'da sinalmagan |
| 3. Ichki CRM | Kod tayyor, commit yo'q | `feat/crm-capi` | | Bayroq o'rniga o'chmaydigan «Sifatsiz lid» ustuni (`kind: junk`) |
| 4. `crmlinks`, amoCRM | Boshlanmagan | | | |
| 5. Bitrix24 | Boshlanmagan | | | |
| 6. Custom CRM | Boshlanmagan | | | |
| 7. CAPI hisobi | Ichki CRM uchun tayyor | `feat/crm-capi` | | `lead_quality`; bildirishnomalar va `sent_by_page` qilinmagan |
| 8. API, Front, yoqish | Ichki CRM uchun kod tayyor, yoqilmagan | `feat/crm-capi` | | Tashqi CRM ekranlari keyin |

## 10. Manbalar

- [amoCRM OAuth](https://www.amocrm.ru/developers/content/oauth/step-by-step)
- [amoCRM cheklovlari](https://www.amocrm.ru/developers/content/api/recommendations)
- [amoCRM integratsiya turlari](https://www.amocrm.ru/developers/content/integrations/intro)
- [amoCRM hodisalari](https://www.amocrm.ru/developers/content/crm_platform/events-and-notes)
- [amoCRM voronkalari](https://www.amocrm.ru/developers/content/crm_platform/leads_pipelines)
- [amoCRM kontaktlari](https://www.amocrm.ru/developers/content/crm_platform/contacts-api)
- [Bitrix24 OAuth](https://apidocs.bitrix24.com/settings/oauth/index.html)
- [Bitrix24 local ilovalar](https://apidocs.bitrix24.com/local-integrations/local-apps.html)
- [Bitrix24 nashr tartibi](https://apidocs.bitrix24.com/market/preparing-to-publish/publication-requirements.html)
- [Bitrix24 bosqich tarixi](https://apidocs.bitrix24.com/api-reference/crm/crm-stage-history-list.html)
- [Bitrix24 limitlari](https://apidocs.bitrix24.com/limits.html)
- [Meta CRM integratsiyasi](https://developers.facebook.com/documentation/ads-commerce/conversions-api/conversion-leads-integration/crm-integration/3-implementing-the-crm-integration)
- [Meta payload](https://developers.facebook.com/documentation/ads-commerce/conversions-api/conversion-leads-integration/payload-specification.md)
- [Meta Using the API](https://developers.facebook.com/documentation/ads-commerce/conversions-api/using-the-api)
