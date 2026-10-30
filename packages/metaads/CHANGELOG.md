# metaads — o'zgarishlar tarixi

Semantik versiyalash. Meta API versiyasi (`v26.0`) paket versiyasidan
alohida — u `client.py` dagi konstantada.

## 0.43.0 — 2026-10-30

### Qo'shildi
- `metaads.audience_diff` — `audience_of`, `same_audience`: ikki auditoriya
  bir xil odamlarga qaratilganmi. Meta shahar kalitini to'liq joyga
  kengaytiradi va standart qiymatlar qo'shadi; solishtirish faqat
  auditoriyani belgilaydigan qismlar bo'yicha. Prod nusxasidagi 18 376 ta
  guruhda tekshirildi.
- `read_targeting` — guruh auditoriyasini o'qiydi; xato bo'lsa ko'taradi
  (yozishdan oldingi o'qish bo'sh javob bilan yozuvni o'tkazib yubormasin).
- `MetaAudiences.read_targeting`, `MetaAudiences.same_targeting`.

### O'zgardi
- `write_targeting` endi `TargetingWritten(dropped, returned)` qaytaradi;
  `MetaAudiences.apply` `applied["targeting"]` ga Meta saqlab qolganini yozadi.

## 0.42.1 — 2026-10-21

### Tuzatildi
- `list_ads` — akkauntdagi bitta Advantage+ kreativi (`100/2446211`) butun
  `/ads` ro'yxatini yiqitardi. Endi reklamalar kreativ mazmunisiz
  (`creative{id}`) qayta o'qiladi. `UNREADABLE_CREATIVE_SUBCODE` va
  `AD_FIELDS_WITHOUT_CONTENT` `metaads.campaigns` ga ko'chdi.
- `create_adset` va `write_targeting` — yozuvdan keyingi o'qish yiqilsa
  (masalan, limit tormozi), xato endi yozuvning xatosiga aylanmaydi: yangi
  guruh ID'si qaytadi, `dropped` bo'sh qoladi.
- Izdagi maxfiy kalitlar: `code`, `fb_exchange_token`, `input_token` ham
  yashiriladi.

## 0.42.0 — 2026-10-21

### Qo'shildi
- `PAGE_FIELDS` endi `connected_instagram_account{id,username}` ni ham
  so'raydi. `PageDTO.instagram_accounts` sahifaning ikkala Instagram'ini
  takrorsiz beradi; `instagram_id` birinchisiga, yo'q bo'lsa sozlamadagi
  ulanishga qaytadi.
- `TokenInfoDTO.granular_scopes` va `targets(scope)` — ruxsat qaysi
  akkauntlar uchun berilgani (`GranularScopeDTO`).

### O'zgardi
- `list_pages` yangi maydon `#10/#100/#200` bilan rad etilsa,
  `BASE_PAGE_FIELDS` bilan qayta so'raydi — sahifalar ro'yxati yo'qolmaydi.

## 0.41.2 — 2026-10-19

### Tuzatildi
- `upload_video` (bitta so'rovli, 25 MB gacha) videoni `title` bilan
  yuboradi. Avval faqat bo'laklab yuklash nom berardi, kichik video
  kutubxonada nomsiz qolardi va har sinxron plitkaning nomini o'chirardi.

## 0.41.1 — 2026-10-17

### Tuzatildi
- `metaads.objects` har obyektni o'z yo'lida (`GET /{id}`) o'qiydi. Graph
  v26.0 `?ids=` ni `code 100` bilan rad etadi va javobni `is_transient` deb
  belgilaydi, shuning uchun bittalab o'qishga o'tish ham ishlamas edi —
  `read_objects` har safar yiqilardi.
- O'z yo'lida o'qilgan yo'q obyekt `803` emas, `100/33` qaytaradi — u ham
  javobdan tushib qoladi, qolgan obyektlar o'qiladi. Yalang'och `100`
  (rad etilgan maydon) avvalgidek xato.

### Olib tashlandi
- `IDS_PER_READ`.

## 0.41.0 — 2026-10-16

### Qo'shildi
- `MetaCampaigns.read_objects` (`adskit` 0.24.0) va `metaads.objects` —
  kampaniya, guruh va reklamalarni `?ids=` bilan, 50 tadan o'qiydi. Akkaunt
  ro'yxatidagi bitta begona reklama endi bu o'qishni yiqitmaydi.
- Meta to'plamni rad etsa, har ID alohida so'raladi; `803` (yo'q) javobdan
  tushib qoladi. Reklama kreativini Meta o'qib bera olmasa (`100/2446211`,
  Advantage+ kreativining asset feed'i story spec'ga mos emas), reklama
  kreativ mazmunisiz qayta o'qiladi — holati va kreativ ID'si qoladi.

## 0.40.0 — 2026-10-15

### O'zgardi
- `lead_count(actions, *, goal)` — lid qaysi nomdan o'qilishini guruhning
  `optimization_goal` i hal qiladi, kunlik qatordagi nomlar emas. Sayt
  maqsadi (`OFFSITE_CONVERSIONS`) — `WEBSITE_LEAD_ACTIONS` (`lead` birinchi,
  Ads Manager'ning «Leads» ustuni); qolgani — `LEAD_ACTIONS` (forma birinchi).
  Sayt guruhiga tasodifan yozilgan bitta forma lidi endi kunning butun
  sonini almashtirmaydi. `lead_actions_for(goal)` — shu tanlov.
- `INSIGHT_FIELDS` va `BREAKDOWN_FIELDS` ga `optimization_goal` qo'shildi.
  Kampaniya qatorida Meta «Unknown Optimization Goal» deydi — u forma
  birinchi o'qiladi.

## 0.39.0 — 2026-10-13

### Qo'shildi
- `restage(..., lead_form_id=)` — reklama tugmasi ortidagi formani boshqasiga
  almashtiradi. Faqat allaqachon forma ochadigan reklamada; boshqasida
  `InvalidRequest(code="restage_form")`.

## 0.38.0 — 2026-10-08

### Qo'shildi
- `MetaMetrics.fetch_people` va `insights.fetch_people_counts` — `reach` va
  `estimated_ad_recallers` `time_ranges` bilan, `time_increment` siz:
  Meta davrni bir marta sanaydi (Ads Manager'dagi son).

## 0.37.0 — 2026-10-06

### Qo'shildi
- `100/1359188` («No Payment Method») → `adskit.PaymentMethodMissing`.
- `accounts.owes_payment` — akkaunt to'lanmagan qarz sababli to'xtaganmi
  (`account_status` 3).
- `accounts.billing_url` — Meta to'lov sahifasi, bitta akkaunt bilan.
- `accounts.ACCOUNT_QUALITY_URL`, `accounts.IDENTITY_URL` — Meta xato
  ma'lumotnomasi yuboradigan ikki manzil.

### Tuzatildi
- Tugmasiz video reklamaga `link_description` yuborilmaydi — Meta
  `100/1815614` bilan rad etardi.

### Olib tashlandi
- `CreativeSpec.enhancements` va u yuboradigan
  `degrees_of_freedom_spec.creative_features_spec.standard_enhancements`.
  Meta v22.0 dan beri `standard_enhancements` bilan reklama yaratmaydi;
  har bir xususiyat alohida so'ralishi kerak.

## 0.36.0 — 2026-10-02

### Qo'shildi
- 100/1487756 («Some locations conflict with each other») →
  `LocationsOverlap`. Avval `InvalidRequest` bo'lib, ekranda umumiy
  «Meta qabul qilmadi» degan matn chiqardi.
- `find_locations` shahar qatoriga `parent_id` ni Meta'ning `region_id`
  sidan yozadi.

## 0.35.0 — 2026-10-01

### Qo'shildi
- `MetaConnect.access_token(stored=)` — saqlangan token o'zgarishsiz qaytadi.

## 0.34.0 — 2026-10-01

MINOR: Meta ulanishi `ConnectPort` sifatida.

### Qo'shildi
- `MetaConnect(app_id=, app_secret=)` — kodni almashtirish, 60 kunga
  cho'zish va `debug_token` bitta `complete` ichida; Meta xatosi adskit
  xatosiga o'giriladi.
- `bundle(app_id=, app_secret=)` — `connect` portini to'ldiradi. Argumentsiz
  chaqiruv qolgan portlar uchun avvalgidek ishlaydi.

## 0.33.0 — 2026-09-30

MINOR: kampaniyadagi guruhlar soni.

### Qo'shildi
- `metaads.campaigns.count_campaign_adsets` — `/{campaign}/adsets` ni
  `id,effective_status` bilan o'qib, `DELETED` va `ARCHIVED` dan
  boshqasini sanaydi. Filtr parametri ishlatilmaydi: edge qabul qilmaydigan
  bitta qiymat butun o'qishni yiqitadi.
- `MetaAdapter.count_adsets` — `adskit` 0.17.0 porti.

## 0.32.0 — 2026-09-24

MINOR: katta videoni bo'laklab yuklash va faylni oqim bilan yuborish.

### Qo'shildi
- `metaads.chunks` — `/act_<id>/advideos` ning sessiyali yo'li:
  `upload_video_in_chunks`, `start_chunked_video`, `send_chunk`,
  `finish_chunked_video`, `cancel_chunked_video` va `VideoSession`.
  Bo'lak o'lchamini Meta aytadi (`start_offset`/`end_offset`), video id
  esa birinchi chaqiruvda beriladi.
- `CHUNKED_ABOVE_BYTES` (25 MB) — shu hajmdan katta video sessiya bilan
  ketadi. Bitta so'rovda yuborilgan katta fayl HTTP 413 oladi va javob
  tanasi bo'sh bo'ladi.
- `MetaAssets.upload_video` da `resume` va `remember`: uzilgan yuklash
  yangi video yaratmasdan davom ettiriladi. `remember` har bosqichda
  chaqiriladi, chaqiruvchi holatni o'zi saqlaydi.
- `MetaAssets.abandon_video` — tugatilmagan sessiyani bekor qiladi.
- `metaads.uploads.Readable` — paket ochiq fayldan faqat `read` va `seek`
  ni talab qiladi.

### O'zgardi
- **MAJOR emas, lekin imzo o'zgardi:** `uploads.upload_video` va
  `MetaAssets.upload_video` endi `data: bytes` emas, `file` (+ adapterda
  `file_size`) oladi. Fayl xotiraga to'liq o'qilmaydi — httpx uni
  bo'lak-bo'lak yuboradi. `upload_image` o'zgarmadi: `/adimages` da faylni
  oqim bilan oladigan yo'l yo'q.

## 0.31.0 — 2026-09-22

MINOR: lid formasi oxiridagi tugma.

### Qo'shildi
- `LeadFormSpec.thank_you_button` — Meta'ning `button_type` i
  (`THANK_YOU_BUTTONS` dagi 11 tasidan biri). Bo'sh bo'lsa eski qoida:
  `thank_you_url` bo'lsa `VIEW_WEBSITE`, bo'lmasa `NONE`.
- `LeadFormSpec.thank_you_button_text`, `thank_you_phone`,
  `thank_you_country` — tugma yozuvi va qo'ng'iroq tugmasining raqami
  (E.164) hamda mamlakati (ISO).
- Validator: tugma sarlavhasiz, havola tugmasi Meta tashqarisidagi
  manzilsiz, qo'ng'iroq tugmasi E.164 raqamsiz rad etiladi.
- `LeadFormRow.thank_you_button`, `thank_you_target`,
  `thank_you_button_text`; adapter ularni `LeadFormDTO.ending_*` ga o'giradi.

### O'zgardi
- `FORM_FIELDS` endi `thank_you_page{...}` ni ichki maydonlari bilan so'raydi:
  yalang'och nomlangan node faqat `id` qaytaradi.
- `_thank_you` har tugmaga faqat o'z maydonini qo'yadi (`website_url` yoki
  `business_phone_number` + `country_code`).

## 0.30.0 — 2026-09-21

MINOR: yangi o'qish va OAuth oynasiga yangi parametr.

### Qo'shildi
- `metaads.instagram.read_instagram_profile` — Instagram professional
  akkauntining profili (`GET /{ig-user-id}`): username, ism, bio, sayt,
  profil rasmi, obunachilar, obunalar va postlar soni. Javob
  `InstagramProfileDTO` ga o'giriladi; `id` dan boshqa hamma maydon
  ixtiyoriy, sonlar kelmasa `None` (nol emas).
- `metaads.instagram.read_instagram_account` — o'sha chaqiruv, xom holda
  (konsol uchun), `fields` parametri bilan.

### O'zgardi
- `oauth.authorize_url` endi har doim `auth_type=rerequest` yuboradi.
  Busiz Meta oynasi bir marta rad etilgan ruxsatni qayta so'ramaydi va
  «Qayta ulash» o'sha tokenni qaytaradi.

## 0.29.1 — 2026-09-19

PATCH: xato tuzatish.

### Tuzatildi
- `list_campaigns`, `list_adsets`, `list_ads` endi `MIRROR_PAGES` (100
  sahifa × 100 = 10 000 qator) gacha o'qiydi, klientning umumiy 25 sahifalik
  chegarasigacha emas. 2 500 dan ortiq guruh yoki reklamasi bor akkauntda
  o'qish har safar `ResultTruncated` bilan tugardi. Ko'zgu hammasi yoki
  hech narsa tamoyilida ishlagani uchun bunday akkauntdan birorta qator
  ham yozilmasdi. Chegara saqlanadi: o'ziga ishora qilgan kursor baribir
  to'xtaydi.

## 0.29.0 — 2026-09-16

MINOR: yangi o'qish, yangi ixtiyoriy parametr va xato tuzatish.

### Tuzatildi
- `list_media` endi reklama akkauntining **o'z** rasmlarinigina qaytaradi.
  `/act_<id>/adimages` boshqa egaga tegishli rasmlarni ham ro'yxatga
  qo'shadi (qator `id` si `<ega>:<hash>`). Bunday xesh bilan kreativ ham,
  reklama ham yaratiladi, lekin ko'rsatish boshlanganda Meta «Image Not
  Found» deydi. `describe_image` ham begona qatorni o'qimaydi.
- `IMAGE_FIELDS` ga `account_id` qo'shildi — `id` kelmagan qator uchun.

### Qo'shildi
- `belongs_to(row, account_id=)` — `adimages` qatori shu akkauntnikimi.
  Hech narsa aytmagan qator saqlanadi.
- `own_image_hashes(account_id=, hashes=, token=)` va
  `MetaAssets.own_images(account=, hashes=, token=)` — berilgan xeshlardan
  qaysilari shu akkauntning o'z rasmi. Kreativ qurishdan oldin so'raladi.
- `MetaLauncher.create_ad(status=)` — default `STATUS_PAUSED` (launch
  o'zgarmaydi). Ishlab turgan reklamani almashtiruvchi yangi reklama
  `STATUS_ACTIVE` bilan yaratiladi, aks holda eskisi o'chgach guruh jim
  qoladi. `applied` ga `status` qo'shildi.

## 0.28.1 — 2026-09-16

PATCH: xato tuzatish.

### Tuzatildi
- `LEAD_ACTIONS` ga `onsite_conversion.lead_grouped` qo'shildi. `region`
  kesimida Meta sayt konversiyalarini yubormaydi, `lead` ham ular bilan
  birga tushadi — instant forma lidi faqat shu nom bilan keladi. Usiz
  hudud kesimining har bir qatorida lid 0 edi. Boshqa kesimlar va umumiy
  qatorlar o'zgarmaydi: ularda `lead` birinchi bo'lib topiladi.

## 0.28.0 — 2026-09-16

MINOR: yangi o'qish.

### Qo'shildi
- `pixel_events(pixel_id=, token=)` — piksel qaysi hodisalarni yuborganini
  nomi va soni bilan qaytaradi (`PixelEventRow`). Meta javobni vaqt
  bo'laklariga bo'lib beradi, funksiya ularni qo'shib, soni bo'yicha
  tartiblab qaytaradi. `aggregation=event` bilan so'raladi — boshqa
  guruhlash (URL, qurilma) boshqa savolga javob beradi.
- `PIXEL_STATS_DAYS = 7` — Meta shu edge'da bir haftadan orqaga
  qaramaydi. Ko'proq so'ralsa ham o'sha hafta qaytadi, jimgina.

## 0.27.0 — 2026-09-15

MINOR: ixtiyoriy parametr.

### Qo'shildi
- `list_leads(..., until=)` va `MetaLeads.list_leads(..., until=)`. Berilsa
  filtrga ikkinchi `time_created LESS_THAN` sharti qo'shiladi.

## 0.26.0 — 2026-09-14

MINOR: ixtiyoriy parametr.

### Qo'shildi
- `upload_image(..., filename=)` va `MetaAssets.upload_image(..., filename=)`.
  Nom berilsa rasm multipart bilan (`filename` qismi, Meta misolidagi
  `-F filename=@...` shakli) shu nom ostida yuboriladi. Nom bo'lmasa
  avvalgidek base64 `bytes` maydonida ketadi — va Meta kutubxonadagi
  qatorni «bytes» deb ataydi, egasi yuklagan hamma rasm shu nom bilan
  ko'rinardi.

## 0.25.0 — 2026-09-14

MINOR: ikki yangi o'qiladigan son va konsol uchun yangi public funksiya.

### Qo'shildi
- `LANDING_PAGE_ACTIONS` (`landing_page_view`) va `VIDEO_VIEW_ACTIONS`
  (`video_view`, 3 soniyalik ko'rish) — `actions` massividan o'qiladi,
  qo'shimcha so'rov yo'q. Adapter ularni `MetricsDTO.landing_page_views`
  va `MetricsDTO.video_views_3s` ga yozadi.
- `fetch_action_totals(account_id=, since=, until=, token=)` — akkaunt
  oraliqda yuborgan hamma `action_type` yozuvi, xom holda. Meta hodisani
  qaysi nom bilan yuborishini hujjat emas, akkaunt aytadi.

## 0.24.0 — 2026-09-14

MINOR: yangi public funksiya va DTO'da ixtiyoriy maydon.

### Qo'shildi
- `changed_from(sent=, returned=)` — Meta targetingga o'zi qo'shgan kalit
  (masalan `age_max: 65`) va o'zgartirgan oddiy qiymat. `dropped_from`
  faqat yo'qolganni ko'radi; ro'yxat va joylashuvlarni Meta har safar qayta
  yozadi, shuning uchun ular solishtirilmaydi.
- `AdSetCreated.returned` — ad set yozilgandan keyin Meta qaytargan
  targeting.
- `MetaLauncher.create_adset` shu targetingni
  `ActionResult.raw_response["targeting"]` da qaytaradi.

## 0.23.1 — 2026-09-14

### Tuzatildi
- Lid forma yaratish (`POST {page}/leadgen_forms`) endi query'da
  `locale=en_US` yubormaydi. Graph query parametri bilan body maydonini
  bitta ro'yxat qilib o'qiydi, formaning esa o'z `locale` maydoni bor —
  forma inglizcha yaratilishi mumkin edi. Endi Meta formani o'quvchi
  tilida ko'rsatadi. Qolgan hamma so'rovda pin o'zgarmadi
  (`OWN_LOCALE_EDGES`).

## 0.23.0 — 2026-09-14

Ikki rad etish endi o'z domen xatosi bilan chiqadi. MINOR: yangi public
xato klassi, `adskit>=0.13` ning ikki yangi klassini ishlatadi.

### Qo'shildi
- `MetaPayloadTooLarge` — HTTP 413. Meta tanasi bo'sh keladi (kod ham,
  izoh ham yo'q), shuning uchun klient uni status bo'yicha taniydi.
  Adapter uni `adskit.MediaTooLarge` ga o'giradi.

### O'zgardi
- Subcode `1487851` («Location not recognized») → `LocationNotRecognized`.
- Kod `100` endi `NotFound` emas. U «Invalid parameter» — rad etilgan
  qiymat, yo'q obyekt emas — va maxsus subcode'siz `InvalidRequest`
  bo'ladi. `NotFound` faqat `803`.
- `previews.frame_of` kadrsiz javobni `803` bilan ko'taradi (avval `100`
  orqali `NotFound` ga tushardi) — domen xatosi o'zgarmadi.

## 0.22.0 — 2026-09-12

Instagram ruxsatining nomi endi konstanta. MINOR: yangi public nom,
qiymat va xulq o'zgarmadi.

### Qo'shildi
- `INSTAGRAM_SCOPE` — `OPTIONAL_SCOPES` ichidagi yagona ruxsat nomi.
  Loyiha qatlamiga «bu ulanishda Instagram ruxsati bormi» degan savol
  kerak bo'ldi (sahifaga Instagram ulanmagani ikki sababdan biri), va
  javob `holds(scopes, ...)` orqali beriladi. Konstantasiz chaqiruvchi
  `"instagram_basic"` ni qo'lda yozardi — ya'ni ruxsat nomi paketdan
  tashqarida ikkinchi nusxada yashardi.

## 0.21.1 — 2026-09-12

Custom audience'ning ikkita hujjat maydoni endi ikkala shaklda ham
o'qiladi. PATCH: xato tuzatish, imzo o'zgarmadi.

### Tuzatildi
- `CustomAudienceRow.rule` va `.lookalike_spec` matn ko'rinishida kelsa
  ham o'qiladi. Meta node hujjati `rule` turini **string** (ichiga JSON
  yozilgan) deb e'lon qiladi; DTO faqat obyekt qabul qilardi.
- Oqibati paket ichida emas, undan yuqorida edi: bu maydonlar
  `parsed_all` orqali o'qiladi, u esa «hammasi yoki hech narsa» — ya'ni
  Ads Manager'da qurilgan bitta auditoriya (aynan `rule` tashiydigan
  qator) butun akkauntning ro'yxatini o'qib bo'lmaydigan qilardi.
- O'qib bo'lmagan hujjat tashlanmaydi, `{RAW_KEY: matn}` bo'lib qoladi:
  bu maydonlardan so'raladigan yagona savol — «hujjat bormi» — va bo'sh
  dict unga noto'g'ri javob berardi.

## 0.21.0 — 2026-09-12

Reklama akkauntining kutubxonasiga to'g'ridan-to'g'ri havola. MINOR: yangi
maydon va yangi parametr, eskisi ishlashda qoladi.

### Qo'shildi
- `AD_ACCOUNT_FIELDS` ga `business{id}` qo'shildi; `AdAccountDTO.business`
  (`BusinessRefDTO`) va `AdAccountDTO.business_id` — Meta aytmasa bo'sh.
- Biznes orqali topilgan qatorlar o'sha biznes bilan belgilanadi
  (`_owned_by`): token `business` maydonini o'qiy olmasa ham id ma'lum
  bo'ladi. O'zi javob bergan qator tegilmaydi.

### O'zgardi
- `media_library_url(account_id, business_id="")` — ikkala id bo'lsa
  `business.facebook.com/asset_library/ad_accounts` manzilini quradi
  (egasining ishlayotgan havolasidan ko'chirildi; Meta buni hujjatlamagan).
  Biznesi yo'q akkaunt eski yo'lda — Ads Manager.

## 0.20.0 — 2026-09-12

Kampaniyani o'chirish. MINOR: adapterga yangi metod.

### Qo'shildi
- `MetaCampaigns.delete` — `writes.delete_object` orqali `DELETE /<id>`.
  Kampaniya o'chirilsa Meta ichidagi guruh va reklamalarni ham o'chiradi.
  Sinov rejimi va sinov id'lari qo'ng'iroqsiz `True` qaytaradi.

## 0.19.0 — 2026-09-12

Xato kodlari ikkiga ajratildi. MINOR: yangi konstantalar; code 1/2 ning
sinfi o'zgardi — bu xato tuzatish, lekin chaqiruvchi uni sezadi.

### O'zgardi
- `RETRYABLE_CODES` ikkiga bo'lindi: `TRANSIENT_CODES = {1, 2}` →
  `MetaTemporaryError`, `RATE_LIMIT_CODES = {4, 17, 613, 80004}` →
  `RateLimitApproaching`. Oldin code 1/2 ham rate limit bo'lib kelardi.
- `is_transient: true` belgisi rate limit bo'lmagan kodni
  `MetaTemporaryError` qiladi.
- `RateLimitApproaching` endi `subcode` ni ham saqlaydi.

### Qoldi
- `RETRYABLE_CODES` — ikkala to'plamning birlashmasi, faqat «retry
  qilinadimi» deb so'raydigan chaqiruvchilar uchun.

## 0.18.0 — 2026-09-10

Media kutubxonasidan o'chirish va rasm qayerda turganini so'rash. MINOR:
yangi funksiyalar, mavjud xatti-harakat o'zgarmadi.

### Qo'shildi
- `uploads.delete_image` (hash bo'yicha, `DELETE /act_<id>/adimages`) va
  `uploads.delete_video` (`DELETE /<video_id>`). Ikkalasida ham
  `dry_run=True` default; Meta `success: true` demasa — `MetaAPIError`.
- `creatives.image_creatives` — rasm qaysi kreativlarda turgani
  (`AdImage.creatives`), Ads Manager'da yasalganlari ham. O'chirishdan
  oldin so'raladi: Meta hujjati ishlatilayotgan rasmni o'chirish haqida
  hech narsa demaydi.
- `creatives.describe_image` — yuklangan rasmni hash bo'yicha qayta o'qish
  (havola, o'lcham, nom). Meta hech narsa qaytarmasa — faqat hash bilan DTO.
- `discovery.read_images` va `IMAGE_USAGE_FIELDS`.
- `MetaAssets` da to'rttasi ham `session()` ichida.

### O'zgarmadi
- Video uchun «qaysi kreativda» maydoni hujjatda topilmadi — so'ralmaydi.

## 0.17.0 — 2026-09-10

Token egasining ismi o'qiladi. MINOR: yangi funksiya va yangi DTO,
mavjud xatti-harakat o'zgarmadi.

### Qo'shildi
- `oauth.describe_person(token=...)` → `PersonDTO(id, name)`. `debug_token`
  egani faqat ID bilan aytadi, ID esa ekranda hech kimga hech narsa
  demaydi. Ism kerak bo'lgan joy — Meta profilni tasdiqlashni so'raganda
  «qaysi profil bilan kirish kerak» degan jumla: kabinetni ulagan odam
  va uni o'qiyotgan odam har doim bir kishi emas.
- Yangi ruxsat so'ralmaydi — `name` standart `public_profile` ichida.

## 0.16.0 — 2026-09-07

Ilova darajasidagi chaqiruv limiti ham o'qiladi. MINOR: yangi sarlavha
o'qiladi, mavjud xatti-harakat o'zgarmadi.

### Qo'shildi
- `X-App-Usage` — Meta har javobda **ikkita** byudjet haqida xabar beradi
  va ular boshqa-boshqa tugaydi. Biznes byudjeti reklama hisobi bo'yicha:
  bitta mijozning og'ir kechasi o'sha mijozni to'xtatadi. Ilova byudjeti
  esa butun deployment uchun **bitta** raqam — har bir obuna o'sha
  raqamni sarflaydi, ya'ni obunachilar soni o'sgan sari birinchi bo'lib
  aynan shu tugaydi. U umuman o'qilmasdi: birinchi belgi hamma hisobning
  bir vaqtda rad etilishi bo'lardi.
- `APP_USAGE_HEADER` konstantasi. To'xtash chegarasi o'zgarmadi —
  ikkalasi ham `USAGE_STOP_PERCENT` (80%), va yomonrog'i g'olib.

### O'zgarmadi
- `X-Ad-Account-Usage` ataylab o'qilmaydi: u boshqa narsani boshqaradi
  (nechta obyekt yaratish mumkinligini), va unga qarab o'qishni rad etish
  yozishni himoya qilish uchun sinxronni to'xtatish bo'lardi.

## 0.15.0 — 2026-09-06

`TokenInfoDTO` endi o'lgan tokenning **sababini** ham beradi. MINOR:
ikkita ixtiyoriy maydon, mavjud maydonlar o'zgarmadi.

### Qo'shildi
- `TokenInfoDTO.error_code` / `.error_subcode` — `debug_token` javobidagi
  ichma-ich `error: {code, subcode}` obyektidan yassilanadi. `extra="ignore"`
  uni jimgina tashlab yuborardi, ya'ni «muddati tugadi» va «odam ilovani
  Facebook sozlamalaridan olib tashladi» chaqiruvchiga bir xil
  `is_valid: false` bo'lib yetardi — ikki xil holat, ikki xil jumla va
  ikki xil sabab.
- Shakli buzilgan `error` (obyekt emas) xato ko'tarmaydi: nollar bilan
  qaytadi. Bu javob bizniki emas, unga qarab yiqilish ham bizniki emas.

## 0.14.0 — 2026-09-03

`boosts` — mavjud Instagram postidan reklama (A yo'l) va `previews` dagi
host tuzatuvi. MINOR: yangi modul, va allowlist kengaydi.

### Qo'shildi
- `boosts.BoostSpec` / `boosts.boost_payload(spec)` — yassi kreativ
  shakli: `object_id` (sahifa) + `instagram_user_id` (profil) +
  `source_instagram_media_id` (post) va **yuqori darajadagi**
  `call_to_action`. `object_story_spec` yonida **hech qachon**
  qurilmaydi: Meta ikkalasini qabul qiladi va story spec'ni reklama
  qiladi — ya'ni odam tanlagan post yonida yangi bo'sh post.
- `boosts.create_boost_creative(...)`, `boosts.read_creative(...)`,
  `BOOST_FIELDS` / `BOOST_FIELDS_MINIMAL`.
- `MetaLauncher.boost_creative(...)` — ketma-ketlikdagi o'sha qadam,
  faqat mavjud postdan. Alohida metod, `create_creative` ichida shart
  emas: ikkalasi ikki xil obyekt oladi va ikki xil narsani anglatadi.

### Isbotlangan shakl mahkamlandi
- **Tugma bo'lsa `value.link` majburiy.** `BoostSpec` uni konstruksiyada
  talab qiladi — Meta'ga bormasdan. Sabab: bu obyekt kampaniya, guruh va
  forma yaratilgandan **keyin** quriladi, forma esa rollback o'chira
  olmaydigan yagona narsa.
- **Forma va link bitta `value` da birga ketadi.** Bu `stories` dagi
  qoidaning teskarisi (u yerda ikkovini yuborish — reklama forma o'rniga
  saytni ochishi demak). Bu yerda Meta shunday talab qiladi.
- Suhbat (`app_destination`) va forma o'zaro istisno bo'lib qoladi.
  Messenger + link **hali sinalmagan** — u faqat linksiz rad etilgan.

### Tuzatildi
- `previews.PREVIEW_HOST` → `PREVIEW_HOSTS` (frozenset). Meta hujjatida
  `www.facebook.com` yozilgan, jonli akkaunt esa **hamma** preview'ni
  `business.facebook.com` bilan qaytardi. Bitta host bilan parse har bir
  freymni rad etardi va rad etish faqat log qatori — ya'ni mahsulotdagi
  «reklamani ko'rish» jimgina bo'sh edi. Suffiks tekshiruvi emas,
  ro'yxat: `evil-facebook.com` va `facebook.com.attacker.net` ikkalasi
  ham «facebook.com bilan tugaydi».

### Jonli sinovdan (2026-09-02)
`probe_boost_creative` buyrug'i shakllarni Meta'ga yubordi, har birini
o'qib qaytardi va o'chirdi:

- **Qabul qilindi:** tugmasiz · `SIGN_UP` + `value: {lead_gen_form_id,
  link}`. Ikkinchisi — lid formasi mavjud postda. Hujjatda yo'q, lekin
  o'qib qaytarilganda forma id joyida.
- **Rad etildi:** `value` da faqat forma (`100/2061015 — link majburiy`) ·
  `object_url` bilan har qanday shakl (`100/1487929 — Ambiguous Promoted
  Object Fields: object_url, source_instagram_media_id`) · Messenger ham
  linksiz (`100/2061015`).
- Ya'ni **link talabi yo'lning o'ziga tegishli**, formaga emas.
- Yaratilgan kreativ `object_type: "SHARE"` va `effective_object_story_id`
  (`<page_id>_<post_id>`) bilan qaytadi — Meta IG postining sahifadagi
  nusxasini o'zi chop etadi, Facebook joylashuvi shu tufayli ishlaydi.

## 0.12.0 — 2026-08-27

`previews` — reklamani ko'rish (B7.1). MINOR: yangi modul va adapterda
yangi metod.

### Qo'shildi
- `previews.get_preview(*, object_id, ad_format, token, client)` —
  `GET /{object_id}/previews?ad_format=…`. Bitta edge reklama uchun ham,
  kreativ uchun ham ishlaydi; qaysi id berilgani modulga ahamiyatsiz.
- `previews.frame_of(body)` — Meta'ning `<iframe>` markupidan manzil va
  o'lcham. Chaqiruvsiz sinaladi, chunki ikkita tuzoq shu yerda.
- `previews.PreviewFrame`, `PREVIEW_SCHEME`, `PREVIEW_HOST`,
  `PREVIEW_PATH`.
- `MetaCampaigns.get_preview` — `adskit.CampaignControlPort` ning yangi
  metodi.

### Hujjatda yozilmagan ikki narsa

1. **Manzil HTML-escape qilingan.** `&` → `&amp;`, ya'ni imzo tokeni `t`
   `unescape` siz oldingi parametr qiymatining bir qismi bo'lib qoladi va
   Meta freymni «The parameter t is required» bilan rad etadi — bu esa
   tashrif buyuruvchining brauzerida, bizning har qanday logimizdan
   tashqarida sodir bo'ladi.
2. **Manzil imzolangan va muddati e'lon qilinmagan.** Paket keshlamaydi;
   saqlaydigan chaqiruvchi uni eskiradigan narsa deb bilishi kerak.

`ad_format` qiymatlari ro'yxati **sanab chiqilmagan**: Meta yangi
placement qo'shganda paketni reliz qilish kerak bo'lardi, chaqiruvchi esa
baribir string uzatadi. Meta qo'llab-quvvatlamagan (kreativ, yuza) juftligi
xato 100 beradi — bo'sh javob emas.

## 0.11.0 — 2026-08-25

O'lik yuzalar olib tashlandi (B3.10). Hech biri hech qayerdan
chaqirilmasdi — testlardan ham; olib tashlash hech qanday chaqiruvchini
buzmaydi. Pre-1.0 odati bo'yicha MINOR.

### Olib tashlandi
- `MetaLauncher.activate()` — yoqish mahsulotda boshqa yo'ldan yashaydi
  (`adapter.set_status`, manage tizimi); launch ataylab PAUSED yaratadi.
- `AdSetSpec.end_time` — hech bir chaqiruvchi to'ldirmagan. Rejalashtirilgan
  yetkazish qurilsa, maydon o'sha ish bilan birga qaytadi.
- `client.MAX_ATTEMPTS` — «Celery task hurmat qiladigan retry byudjeti»
  deb e'lon qilingan edi; loyihadagi bironta task retry qilmaydi va bu
  hujjatlashtirilgan qaror.
- `client.BATCH_MAX_REQUESTS` — batch endpoint hech qachon qurilmagan.
- `client.LEAD_RETENTION_DAYS` — mahsulot siyosati paketga tegishli emas;
  tirik nusxa `apps/leads/constants.py` da. Meta o'z nusxasini 90 kunda
  tashlashi fakti `leads.py` modul docstring'iga ko'chdi.
- `leads.subscribed_fields()` — chaqiruvchisiz to'liq implementatsiya.
  O'qish yo'li (`GET /{page_id}/subscribed_apps`) modul docstring'ida
  yozib qoldirildi.

### Ichki (API o'zgarmadi)
- `dto.py` (1023 qator) olti mavzuli modulga bo'lindi:
  `connection_rows` · `account_rows` · `lead_rows` · `campaign_rows` ·
  `creative_rows` · `audience_rows`, umumiy baza `dto_base` da.
  `from metaads.dto import CampaignRow` avvalgidek ishlaydi — `dto.py`
  endi import yuzasi.

## 0.10.0 — 2026-08-25

Instagram akkaunti maydonining nomi. **MAJOR emas, lekin diqqat bilan
o'qing:** maydon nomi o'zgardi va eski nom bilan qurilgan kod jimgina
ishlashda davom etadi — natijasi noto'g'ri bo'ladi.

### O'zgardi
- `CreativeSpec.instagram_actor_id` → **`instagram_user_id`**.
- `stories.story_spec` `object_story_spec` ichiga `instagram_user_id`
  yozadi (`_INSTAGRAM_KEY`).
- `CreativeRow.instagram_actor_id` → **`instagram_user_id`**, va u
  javobdagi `object_story_spec.instagram_user_id` ni o'qiydi.
- `MetaCreatives` adapteri `CreativeDTO.instagram_user_id` ni to'ldiradi
  (`adskit` 0.8.0 talab qilinadi).

### Nega
Meta maydonni v22.0 da eskirtirgan va **2025-09-09 dan hamma API
versiyasida** olib tashlagan. v26.0 `AdCreativeObjectStorySpec`
ma'lumotnomasida `instagram_actor_id` **umuman yo'q** — faqat
`instagram_user_id` («The Instagram user account that the ad will be
posted to»).

**Nosozlik ovozsiz.** Meta nested spec ichidagi notanish kalitni rad
etmaydi, tashlab yuboradi: kreativ quriladi, reklama ishlaydi, va u
Instagram akkaunt nomidan emas, sahifa nomidan chiqadi. O'qish tomonida
esa ustun abadiy bo'sh qoladi.

### Ko'chirish
Nomni almashtirish kifoya — qiymat o'zgarmadi, u hamon sahifaning
`instagram_business_account.id` si. Eski nom **fallback sifatida ham
o'qilmaydi**: uni hamon qaytaradigan javob 2025-09-09 dan oldingi bo'lishi
kerak, va o'lgan kalitdan to'ladigan ustun jimgina eskiradi.

## 0.9.0 — 2026-08-25

Qo'ng'iroq reklamasi va tugmasiz reklama. MINOR: mavjud chaqiruvlar
o'zgarmadi — yangi maydon bo'sh sukutga ega, `NO_BUTTON` esa hech bir
mavjud chaqiruvchi yubormaydigan qiymat.

### Qo'shildi
- `CreativeSpec.phone_number` — E.164, sxemasiz. `tel:` Meta ning imlosi
  va u `stories` da qo'shiladi: chaqiruvchida telefon raqami bor, URI
  emas. Noto'g'ri shakl qurilish paytida rad etiladi.
- `CTA_NO_BUTTON` — Meta ning "tugma chizilmasin" so'zi. **Bo'shliq
  emas:** `call_to_action` yuborilmasa Meta o'zi qo'yadi va u qo'ygani
  havola bo'ladi.
- `TEL_SCHEME` — `tel:`. Bitta joyda ishlatiladi va shuning uchun nomi
  bor: raqamni URI ga aylantirish qarori paketning ichida qoladi.

### O'zgardi
- `stories._call_to_action` — endi beshta holat: tugmasiz, lid formasi,
  xabar manzili, **telefon raqami**, havola. Oxirgi shox eng xavflisi va
  u eng oqilona ko'ringani uchun shunday: tugmasiga aniq boshqa narsa
  berilmagan har bir reklama shu yerga tushib havola oladi — va bir yil
  davomida qo'ng'iroq preseti ham, xabar preseti ham shu yerga tushgan.
- `_call_to_action` `NO_BUTTON` da butun blokni tashlaydi.

### Meta hujjati — ikkita zid
- `destination_type: PHONE_CALL` AdSet ma'lumotnomasi enum'ida **yo'q**,
  lekin Call Ads qo'llanmasi ham, ODAX solishtirish jadvali ham beradi.
  Bir-biriga rozi bo'lgan ikkitasiga ergashildi.
- `AdCreativeLinkDataCallToActionValue.link` — *"This is required to be
  same as the link url of the creative"*, lekin Call Ads qo'llanmasining
  o'z misolida `value.link` = `tel:…` va `link_data.link` = sahifa
  manzili. Aniqroq sahifaga (qo'llanma) ergashildi.

## 0.8.0 — 2026-08-25

Xabar reklamasi: tugma havola emas, suhbat ochadi. MINOR: mavjud
chaqiruvlar o'zgarmadi — ikkala yangi maydon ham bo'sh sukutga ega va
bo'sh bo'lsa spec bir baytga ham farq qilmaydi.

### Qo'shildi
- `CreativeSpec.app_destination` — `MESSENGER`, `INSTAGRAM_DIRECT` yoki
  `WHATSAPP`. Noma'lum qiymat qurilish paytida rad etiladi
  (`APP_DESTINATIONS`).
- `CreativeSpec.welcome_text` va `.autofill_text` — suhbatda mijoz
  kelgunicha yozilgan ikki matn. Ikkalasi ham oddiy satr: ichma-ich
  obyektning shakli paketning ishi.
- `stories.welcome_message` — `page_welcome_message` ning JSON i.
  `story_spec` kabi eksport qilingan, chunki uni test ushlab turishi
  kerak.
- `MAX_WELCOME_TEXT`, `MAX_AUTOFILL_TEXT` — Meta ning 300 belgilik
  chegarasi.

### O'zgardi
- `stories._call_to_action` — endi uchta holat: lid formasi, xabar
  manzili, havola. Tartib aniqlikdan umumiylikka, va bitta kalitda
  faqat bitta qiymat bo'ladi.
- `link_data` va `video_data` — ikkalasiga ham `page_welcome_message`.
  Bo'sh bo'lsa `_without_empties` uni allaqachon tashlaydi.

### Hujjat tekshiruvi — uchta topilma

**1. Tugma `app_destination` ko'taradi, havola emas.** Xabar
reklamasining CTA si:
`{"type": "MESSAGE_PAGE", "value": {"app_destination": "MESSENGER"}}`.
Bu yerga qadar paket forma bo'lmasa **doim** `{"link": …}` yozardi —
ya'ni xabar preseti suhbat emas, sayt ochadigan ishlaydigan reklama
qurardi. Nosozlik jim: reklama yuradi, hisobotda bosishlar ko'rinadi.

**2. `page_welcome_message` — String, ichma-ich obyekt emas.**
`AdCreativeLinkData` ma'lumotnomasi: *«For click to Whatsapp ads, this
string is a JSON object passed as a string»*. Click-to-Messenger
qo'llanmasining misolida esa u obyekt sifatida turibdi. **Ikki sahifa
zid.** Tur haqidagi yarmi (ma'lumotnoma) tanlandi; ikkinchisi
`BLOK3-LOG.md` da tekshirilmagan taxmin sifatida qayd etildi.

Shakli (Meta ning o'z misoli): `type: VISUAL_EDITOR`, `version: 2`,
`landing_screen_type: welcome_message`, `media_type: text`,
`text_format.customer_action_type: autofill_message`,
`text_format.message.text` va `.autofill_message.content`.

**3. Salomlashish ixtiyoriy.** Yuborilmasa Meta o'zinikini yozadi
(*«Hello! Can I get more info on this?»*). Ya'ni bo'sh salomlashish —
ishlaydigan reklama, rad etilgan launch emas. Shuning uchun qaror
salomlashishga bog'langan: u bo'sh bo'lsa maydon umuman yuborilmaydi,
autofill yolg'iz qolmaydi.

## 0.7.0 — 2026-08-25

Manfiy qamrov — son emas, rad javobi. PATCH emas, MINOR: adapter yangi
DTO maydonini to'ldiradi.

### O'zgardi
- `MetaAudiences.estimate_reach` — chegaralardan biri manfiy bo'lsa
  `ReachDTO(available=False)` qaytaradi, `-1` ni son sifatida uzatmaydi.

### Hujjat tekshiruvi

*«Updates to Reach Estimation Availability for Custom Audiences»*:
`reachestimate`, `delivery_estimate` va `audienceoverlap` endi
**bir nechta kalitli mijoz faylidan** qurilgan auditoriya, data file
auditoriyasi va offline conversion auditoriyasi nomlangan spec'ni
o'lchamaydi. Xato qaytarmaydi — **`-1`** qaytaradi, ya'ni tekshirilmasa
u butun zanjir bo'ylab son sifatida oqib o'tadi.

## 0.6.0 — 2026-08-25

Lookalike auditoriyasi. MINOR: mavjud chaqiruvlar o'zgarmadi.

### Qo'shildi
- `lookalikes.py` — `RATIOS`, `SUBTYPE_LOOKALIKE`, `lookalike_spec`,
  `ratio_of`.
- `audiences.create_lookalike_audience` — uchinchi create, uchinchi
  repetitsiya ID si (`dryrun-lookalike`).
- `AUDIENCE_FIELDS` ga `lookalike_spec`; `CustomAudienceRow.lookalike_spec`
  va `.can_seed`.
- `MetaAudienceSources.create_lookalike_audience`.

### Hujjat tekshiruvi — beshta topilma

**1. `subtype` bu yerda YUBORILADI va majburiy.** Bu qo'shni create'ning
aynan teskarisi. B3.2 topilmasi — «`subtype` yuborilmaydi» — website va
engagement auditoriyalari haqida edi, `subtype` haqida umumiy qoida emas.
Meta ning o'z `curl` misoli `subtype=LOOKALIKE` ni `name` yonida olib
yuradi va usiz create rad etiladi.

**2. `origin_audience_id` — yuqori darajadagi maydon**, `lookalike_spec`
a'zosi emas, garchi u yerga tegishlidek o'qilsa ham. Spec ichida faqat
«qanchalik keng» va «qayerda».

**3. `origin_audience_id` ni QAYTARIB O'QIB BO'LMAYDI.** Custom Audience
node'ning maydonlar ro'yxatida u yo'q. O'qiladigani — bolada
`lookalike_spec`, manbada `lookalike_audience_ids`: ota bolalarini sanaydi,
bola otasini nomlay olmaydi. Ya'ni auditoriya nima'dan qurilganini bilib
qolish uchun uni **o'zimiz yozib qo'yishimiz** kerak.

**4. `ratio` 0.01 dan 0.20 gacha** — Meta ning o'z interfeysi taklif
qiladiganidan ikki barobar keng. `RATIOS` o'ninchida to'xtaydi: Ads
Manager ko'rsatmaydigan qiymat natijasini hech kim hech qayerda tekshira
olmaydigan qiymatdir.

**5. `retention_days` bu yerda umuman tegishli emas.** Meta uni customer
file maydoni deb hujjatlaydi. Qoida auditoriyalari uni 180 chegarasi
tufayli yubormaydi; bu esa uning ma'nosi yo'qligi uchun yubormaydi.

`allow_international_seeds` ham yuborilmaydi va bu qaror. Hujjatlangan
sukuti `false` — ya'ni manbada tanlangan mamlakatdan 100 kishi bo'lmasa
Meta rad etadi. `true` yuborish o'rniga auditoriyani boshqa mamlakatdagi
odamlardan qurardi: bir mamlakat uchun mo'ljallangan auditoriya boshqasining
mijozlari asosida modellashtirilgan bo'lardi. Buni hech kim so'ramagan va
hech qaysi ekran tushuntira olmaydi. B3.2 dagi `prefill` qarorining ayni
o'zi.

## 0.5.0 — 2026-08-25

Ayirib quriladigan auditoriya. MINOR.

### Qo'shildi
- `audience_rules.EXCLUDED_EVENTS` — qaysi harakat kimni qaytarib
  chiqarishi. Uchta: `visited_not_purchased` va
  `added_to_cart_not_purchased` (`Purchase`), `engaged_not_messaged`
  (`page_messaged`).
- `audience_rules.excluded_event_of` — Meta'ning o'z so'zi, ko'zguga.
- `rule_document` endi harakat ayirsa `exclusions` blokini yozadi. Ikkala
  blok **bir manba** va **bir oyna**: hujjatda manbalar aralashgan misol
  yo'q, va ikki xil oyna hech kim so'ramagan savolga javob berardi.
- Adapter `applied` ga `excluded_event_raw` qo'shadi. Faqat yig'adigan
  harakatlarda bo'sh — «hech kim chiqarilmaydi», «noma'lum» emas.

### Tuzatildi
- **Hodisa `eq` bilan solishtiriladi, hamma manbada.** 0.4.0 da pixel
  uchun `i_contains` yozilgan edi. Audience-rules ma'lumotnomasi aniq
  aytadi: *«if `field` set to `event`, must use `=`»*. Website
  qo'llanmasidagi `i_contains` misollari ikkinchi qoida emas — ulardagi
  qiymatlar `SignUp` va `ViewProduct`, ya'ni **maxsus** hodisa nomlari, va
  qisman moslash o'sha yerda maqsad. Standart hodisada u faqat
  so'ralgandan ko'proq narsani tutadi: `i_contains "Purchase"` maxsus
  `SubscriptionPurchase` ni ham tutadi va ayirish tomonida hech qachon
  xarid qilmagan odamni jimgina auditoriyadan chiqarib yuboradi.
- `OPERATORS` jadvali `EVENT_OPERATOR` konstantasiga aylandi. Bitta
  qiymatli jadval noto'g'ri qiymatdan battarroq yolg'on: u solishtirish
  manbaga qarab o'zgaradi deb va'da beradi, hujjatda esa bunday gap yo'q.

## 0.4.0 — 2026-08-25

Retargeting auditoriyalari. MINOR.

### Qo'shildi
- `audience_rules.py` — domen niyatini Meta hujjatiga aylantiradigan
  yagona joy. `META_CURRENCY_PLACES` bo'linishining uchinchi ishlatilishi.
- `audiences.create_rule_audience` — `rule` bilan yaratish.
- `dto.CustomAudienceRow.rule`, `.retention_days`; `AUDIENCE_FIELDS` ham.
- `adapter.MetaAudienceSources.supported_rules`, `.create_rule_audience`.

### Hujjat tekshiruvidan to'rtta topilma (v26.0)
1. **`subtype` yuborilmaydi** — 2018-yil sentabrdan beri website va
   engagement auditoriyalari uchun qo'llab-quvvatlanmaydi. Meta uni
   o'qishda o'zi hosil qiladi.
2. **Lid forma manba turi — `lead`**, `lead_gen_form` emas. Ikkinchisi —
   mahsulotning o'z lug'ati va Meta uni bilmaydi.
3. **Operator manbaga qarab farq qiladi**: pixel `i_contains`,
   sahifa va lid forma `eq`. Bittasi hammaga qo'llansa ikkitasida
   jimgina hech kim mos kelmaydi.
4. **Oyna qoida ichida, soniyada.** Yuqori darajadagi `retention_days`
   180 kun bilan cheklangan va **yuborilmaydi** — Meta hujjati aytadi:
   yo'q bo'lsa u `retention_seconds` dan olinadi.

`prefill` ham yuborilmaydi: u faqat website auditoriyasida bor, hujjatdagi
ikki jumla uning sukut qiymati haqida bir-biriga zid, va e'lon qilingan
sukut (`true`) aynan retargetingga kerak narsa.

### Qurilmadi
- **Video** — joriy hujjatda manba turi ham, namuna ham yo'q. Yagona
  manba — v2.6 da arxivlangan sahifalar. Tekshirish yo'li
  `adapter.MetaAudienceSources.supported_rules` docstring'ida.
- **Instagram** (`ig_business`) — hujjatlashtirilgan, lekin loyihada
  Instagram akkaunt ID sini saqlaydigan jadval yo'q.

## 0.3.0 — 2026-08-25

Auditoriyadan bitta odamni chiqarish. MINOR.

### Qo'shildi
- `customer_lists.remove_members` — `DELETE {audience_id}/users`,
  xeshlangan qatorlar bilan. `add_members` bilan **bitta kod**:
  ikkalasi ham `_send` orqali o'tadi. Ikki nusxa yozilsa sxema
  qurilishi ajralib ketardi va bu jimgina xato bo'lardi — odam
  hech qachon qo'yilmagan ustundan chiqariladi.
- `client.GraphClient.delete_body` — tanasi bor DELETE. Kerak, chunki
  10 000 ta 64-belgili digest so'rov satriga sig'maydi.
- `writing.delete_payload` — `post_object` ning egizagi, xuddi shu
  kodlash qoidalari bilan. Alohida, chunki fe'l detal emas: shaxsiy
  ma'lumot olib tashlanganini access log POST deb ko'rsatsa, o'chirish
  tekshiruvida javob beradigan hech narsa qolmaydi.
- `adapter.MetaAudienceSources.remove_members`.

### Eslatma
Meta chiqarishga ham qo'shishdagi kabi javob beradi (`num_received`,
`num_invalid_entries`), shuning uchun `MemberUploadDTO` ikkala
yo'nalishga xizmat qiladi. Chiqarishda `session` yuborilmaydi: session
bir necha so'rovni bitta yuklash deb hisoblash uchun, chiqarishda esa
bunday jamlanma yo'q.

## 0.2.0 — 2026-08-25

Custom Audience. `adskit` 0.2.0 dagi `AudienceSourcePort` implementatsiyasi.

### Qo'shildi
- `audiences` — obyektning o'zi: `list_audiences`, `get_audience`,
  `create_audience`, `delete_audience`, `terms_url`
- `customer_lists` — **PII ko'taradigan yagona modul**: `add_members`.
  Alohida fayl, chunki shaxsiy ma'lumot bilan ishlaydigan kod boshdan
  oxirigacha o'qib chiqiladigan bitta joyda turishi kerak
- `dto.CustomAudienceRow`, `dto.AudienceStateRow`, `dto.MemberUploadRow`
- `adapter.MetaAudienceSources`, `bundle()` da `audience_sources`
- `AdAccountDTO.tos_accepted` va `user_tos_accepted` +
  `custom_audience_terms_accepted` xossasi (uch holat: ha / yo'q /
  so'ralmagan)

### Meta v26.0 haqida uchta topilma
- **`approximate_count` iste'moldan chiqarilgan.** O'rniga
  `approximate_count_lower_bound` va `_upper_bound` — qiziqishlar
  katalogidagi `audience_size` bilan aynan bir xil hikoya. Ikkalasi ham
  hisoblash tugamaguncha **`-1`**, bu esa to'g'ridan-to'g'ri uzatilsa
  «manfiy odam», nolga aylantirilsa «bo'sh auditoriya» bo'lib o'qiladi
- **Vaqt tamg'alari unix butun son.** Paketning qolgan joyida Meta
  `created_time` da ISO string beradi; bu yerda `time_created` da soniya
- **Holat lug'ati e'lon qilinmagan.** Hujjatlangani ikkita kod, qolgani
  uchrab bilinadi — shuning uchun sanab chiqilmadi: `is_ready` faqat
  ma'lum «tayyor» kodiga qaraydi, qolgani «hali emas»
- Yuklash chegarasi: bitta so'rovda **10 000** qator; kattaroq ro'yxat
  paketda bo'linadi va `session` bilan bog'lanadi

### Qasddan qilinmagani
- **2654 xatosi `TermsNotAccepted` ga o'girilmadi.** U kamida uchta
  sababni qamraydi (shartlar, manba ruxsati, hajm), ya'ni o'girish
  advertiserga noto'g'ri tashxis aytardi. O'rniga shartlar **oldindan**
  `tos_accepted` orqali tekshiriladi

## 0.1.0 — 2026-08-16

Birinchi versiya. Paket `core/meta/` dan ajratildi.

### Qo'shildi
- `client` — API versiyasi, base URL, timeout va retry konstantalari
- `errors` — Meta xato kodlari taksonomiyasi, retry qilinadiganlar ro'yxati
- `signed_request` — Data Deletion callback imzosini tekshirish
  (HMAC-SHA256). Django'dan mustaqil, app secret parametr sifatida keladi
