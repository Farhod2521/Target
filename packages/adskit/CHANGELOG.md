# adskit — o'zgarishlar tarixi

Semantik versiyalash. `adskit` MAJOR versiyasi qolgan hamma narsani
buzadi — kamdan-kam va ogohlantirish bilan.

| O'zgarish | Versiya |
|---|---|
| Port imzosi o'zgardi, DTO maydoni olib tashlandi | MAJOR |
| Yangi port, yangi metod, ixtiyoriy maydon | MINOR |
| Xato tuzatish, ichki refactoring | PATCH |

## 0.25.0 — 2026-10-30

MINOR: `AudiencePort.read_targeting`, `AudiencePort.same_targeting`.

### Qo'shildi
- `AudiencePort.read_targeting` — guruh hozir ushlab turgan auditoriya.
  `apply` dan oldin o'qiladi: auditoriya butunligicha almashtiriladi, eski
  nusxa ustiga qurilgan tahrir Ads Manager'da qilingan o'zgarishni o'chiradi.
- `AudiencePort.same_targeting` — ikki auditoriya bir xil odamlarga
  qaratilganmi. Provayderning o'z savoli: qaysi kalit auditoriya, qaysi biri
  uning o'z yozuvi ekanini faqat u biladi.
- `Unavailable` ikkala metodni ham rad etadi.

### O'zgardi
- `ActionResult.applied["targeting"]` — `AudiencePort.apply` dan keyin
  provayder saqlab qolgan auditoriya (o'qib bo'lmasa — yuborilgani).

## 0.24.0 — 2026-10-16

MINOR: `CampaignControlPort.read_objects`.

### Qo'shildi
- `CampaignControlPort.read_objects` — kampaniya, guruh va reklamalarni
  faqat berilgan ref'lar bo'yicha o'qiydi. Akkaunt ro'yxatlari butun
  akkaunt uchun javob beradi va undagi bitta begona obyekt hammasini
  yiqitadi; bu o'qish faqat so'ralgan obyektlar uchun javob beradi. Yo'q
  bo'lgan ref xato emas, javobda shunchaki bo'lmaydi.
- `ObjectsDTO`.

## 0.23.0 — 2026-10-08

MINOR: `MetricsPort.fetch_people`.

### Qo'shildi
- `MetricsPort.fetch_people` — bir nechta davr uchun obyekt qamrovi va
  eslab qolganlar soni, har davr uchun bitta qator. Kunlik qatorlardan
  yig'ib bo'lmaydi: bir odam har kuni qayta sanaladi.
- `PeopleCountDTO`.

## 0.22.0 — 2026-10-06

MINOR: `PaymentMethodMissing`.

### Qo'shildi
- `PaymentMethodMissing` — reklama akkauntida provayder pul yecha oladigan
  to'lov usuli yo'q. Tuzatish provayderning to'lov sahifasida, matnda emas.

## 0.21.0 — 2026-10-02

MINOR: `LocationsOverlap` va `LocationDTO.parent_id`.

### Qo'shildi
- `LocationsOverlap` — auditoriyadagi ikki joy bir hududni qoplaydi
  (shahar va u joylashgan viloyat). Har biri o'zicha to'g'ri, shuning
  uchun `LocationNotRecognized` emas.
- `LocationDTO.parent_id` — shahar joylashgan viloyatning provayderdagi
  kaliti. Shahar va uning viloyati birga yuborilmasligi uchun.

## 0.20.0 — 2026-10-02

MINOR: `CampaignDTO.shared_budget_id`.

### Qo'shildi
- Kampaniya byudjeti boshqa kampaniyalar bilan umumiy bo'lsa, o'sha
  byudjetning provayderdagi ID'si. Bo'sh — byudjet kampaniyaning o'ziniki.
  Summani o'zgartirish hammasiga tegishini ekran oldindan aytishi uchun.

## 0.19.0 — 2026-10-01

MINOR: `ConnectPort.access_token(stored=)`.

### Qo'shildi
- Saqlangan tokendan chaqiruv tokeni. Meta'da o'zi qaytadi, Google'da
  refresh token bir soatlik access tokenga almashtiriladi. Chaqiruvchi
  qaysi turdagi tokenni saqlaganini bilmaydi.

### Tuzatildi
- `Unavailable.get_preview` — `CampaignControlPort` ga qo'shilganda
  o'rinbosarda yo'q edi, shuning uchun u portni to'liq qoplamasdi.

## 0.18.0 — 2026-10-01

MINOR: yangi port `ConnectPort`.

### Qo'shildi
- `ConnectPort` — `authorize_url(redirect_uri=, state=)` va
  `complete(redirect_uri=, code=)`: rozilik oynasi va kodni uzoq
  yashaydigan tokenga almashtirish. Ilovaning id va sirini konstruktor
  oladi. Google uchun ikkinchi provayder shu port orqali ulanadi.
- `GrantDTO` — token (repr'da ko'rinmaydi), `expires_in` soniyada,
  berilgan `scopes`, rozilik bergan odamning `external_user_id`.
- `ProviderBundle.connect` — majburiy; tayyor bo'lmagan provayder
  `Unavailable(port="connect")` beradi.

## 0.17.0 — 2026-09-30

MINOR: `CampaignControlPort.count_adsets`.

### Qo'shildi
- `count_adsets(campaign=, token=)` — bitta kampaniyada o'chirilmagan va
  arxivlanmagan nechta guruh borligi. Kabinet bo'yicha emas, kampaniya
  bo'yicha: kabinet o'qishi sahifalanadi va katta kabinetda sahifalar
  guruhlardan oldin tugaydi. Google'da ham bir so'rov (`status != REMOVED`).
- `Unavailable` ham shu metodni rad etadi.

## 0.16.0 — 2026-09-22

MINOR: `LeadFormDTO` da uchta ixtiyoriy maydon.

### Qo'shildi
- `LeadFormDTO.ending_kind` — forma yuborilgandan keyingi ekrandagi tugma,
  domen so'zi bilan: `none`, `website`, `call` yoki `other`. Bo'sh —
  provayder aytmadi.
- `LeadFormDTO.ending_target` — tugma ortidagi manzil yoki raqam.
- `LeadFormDTO.ending_button_text` — tugmadagi yozuv.
- `FormEndingKind` — `ending_kind` ning `Literal` turi.

## 0.15.0 — 2026-09-15

MINOR: ixtiyoriy parametr.

### Qo'shildi
- `LeadSourcePort.list_leads(..., until=)` — oynaning oxiri. Bitta o'qishga
  sig'maydigan formani (`ResultTruncated`) kunlarga bo'lib o'qish uchun.
  `None` — hozirgacha, avvalgidek.

## 0.14.0 — 2026-09-14

MINOR: `MetricsDTO` da ikki ixtiyoriy maydon.

### Qo'shildi
- `MetricsDTO.landing_page_views` — reklama yuborgan sahifasi ochilgan
  odamlar soni. Sahifada provayder tegi bo'lmasa nol.
- `MetricsDTO.video_views_3s` — kamida 3 soniyalik ko'rishlar.
  `video_plays` dan farqi: boshlanish emas, qolib ko'rgan odam.

## 0.13.0 — 2026-09-14

Ikki rad etish o'z nomini oldi. MINOR: yangi xato klasslari, mavjudlari
o'zgarmadi.

### Qo'shildi
- `LocationNotRecognized` — auditoriyadagi joyni provayder tanimadi
  (dengizdagi nuqta, katalogda yo'q kalit). Tuzatish faqat geografiyada.
- `MediaTooLarge` — provayder faylni yuborilgan so'rovda hajmi sabab
  qabul qilmadi. Faylning o'zi yaroqsiz degani emas.

Ikkalasi ham avval `InvalidRequest` bo'lib kelardi va ekranda «matn yoki
rasmni o'zgartiring» bo'lib chiqardi.

## 0.12.0 — 2026-09-12

Kampaniyani o'chirish. MINOR: `CampaignControlPort` ga yangi metod.

### Qo'shildi
- `CampaignControlPort.delete(ref, token, dry_run=True)` — obyektni
  akkauntdan butunlay olib tashlaydi. Meta kampaniyani ichidagi guruh va
  reklamalar bilan o'chiradi, Google `REMOVED` qiladi; ikkalasi ham
  qaytarilmaydi. Qaytarish tugmasi yo'q — domen yozishdan oldin
  `previous_state` ga surat oladi.
- `Unavailable` ga `delete`, `set_end_time` va `set_spend_cap` stub'lari
  (oxirgi ikkitasi avval tushib qolgan edi).

## 0.10.0 — 2026-08-27

Reklamani ko'rish (B7.1). MINOR: yangi DTO va portga yangi metod.

### Qo'shildi
- `AdPreviewDTO` — bitta reklama bitta yuzada qanday ko'rinishi: `ref`,
  `ad_format`, `src`, `width`, `height`. Rasm emas, **freym**: har
  platforma bu savolga saqlanadigan tasvir bilan emas, joylashtiriladigan
  manzil bilan javob beradi, chunki render ularniki.
- `CampaignControlPort.get_preview(*, ref, ad_format, token)`. Alohida
  port emas — portning o'zi `list_ads` uchun «the content is part of the
  ad's answer» deb yozgan va `AdDTO.creative` ni allaqachon qaytaradi,
  ya'ni kreativ mazmuni shu portning ishi. Bitta metodli port esa
  `ProviderBundle` majburiy talab qilgani uchun har provayderni bitta
  tugma uchun `raise` qiluvchi stub yozishga majburlardi.

`src` ning absolut `https` ekanini **adapter** kafolatlaydi: qiymat
`iframe` ga tushadi, va qaysi host qonuniy ekanini faqat provayder
tomoni biladi.

## 0.9.0 — 2026-08-25

### Olib tashlandi
- `registry.names()` — docstring'i va'da qilgan «admin ekranlari va
  diagnostika» hech qachon qurilmagan; yagona chaqiruvchisi o'zining unit
  testi edi (B3.10). `registry.clear()` qoladi — u test infratuzilmasi va
  docstring'i shuni aytadi.

## 0.8.0 — 2026-08-25

Provayder maydonining nomi o'zgardi. MINOR: DTO maydoni qayta nomlandi
va uni to'ldiradigan yagona adapter shu relizda yangilanadi.

### O'zgardi
- `dto.CreativeDTO.instagram_actor_id` → **`instagram_user_id`**.

Meta maydonni v22.0 da eskirtirgan va 2025-09-09 dan hamma versiyada olib
tashlagan. DTO provayder atamasini olib yuradi, ya'ni o'lik nom bilan
qolgan DTO — yarim bajarilgan ko'chirish: adapter yangi kalitni o'qiydi,
domen esa eski nom ostida bo'sh qiymat ko'radi va sabab hech qayerda
ko'rinmaydi.

## 0.7.0 — 2026-08-25

Qamrov javobining uchinchi holati. MINOR: mavjud imzolar o'zgarmadi,
yangi maydon sukut bo'yicha `True`.

### Qo'shildi
- `dto.ReachDTO.available` — provayder **bu spec'ni umuman o'lchamaydi**.

**`ready` bilan bir xil emas, va farq kutishda.** `ready=False` — «hali
hisoblanmoqda», bir daqiqadan keyin javob bo'ladi. `available=False` —
«hech qachon»: Meta bir nechta kalitli mijoz faylidan qurilgan auditoriya
nomlangan spec'ni o'lchashni to'xtatgan va buni **`-1`** qaytarib aytadi:
*«The API returns a '-1' value as an audience size estimate.»*

Ikkalasini nol deb qabul qilgan chaqiruvchi yo bekorga kutadi, yo
ekranda «taxminan −1 kishi» yozadi. Bu mahsulot aynan ko'p kalit yuklaydi
(telefon + email + ism + shahar), ya'ni bu holat kamdan-kam emas —
mijoz ro'yxatiga qaratilgan har bir kampaniya uchun odatiy.

## 0.6.0 — 2026-08-25

Auditoriyadan auditoriya qurish. MINOR: mavjud imzolar o'zgarmadi.

### Qo'shildi
- `refs.AudienceBreadth` — `closest` · `balanced` · `broad`.
- `dto.LookalikeSpecDTO` — `origin` · `breadth` · `country`.
- `ports.AudienceSourcePort.create_lookalike_audience`.
- `dto.AudienceDTO.can_seed` va `dto.AudienceDTO.lookalike_raw`.
- `Unavailable` yangi metodni ham qamraydi.

**Foiz yo'q, va bu butun qarorning o'zi.** Meta kenglikni 0.01 dan 0.20
gacha nisbat bilan oladi; Google'da foiz **umuman yo'q** —
`expansion_level` uch qiymatli enum (`NARROW`/`BALANCED`/`BROAD`). Domen
foizni saqlasa, u ikkinchi platformaga aytib bo'lmaydigan raqamni saqlagan
bo'lardi va Google adapteri birinchi navbatda undan teskari jadval
o'ylab topishi kerak bo'lardi. Niyatni nomlash ikkala adapterni ham
jadval qidiruviga aylantiradi — va bu mahsulot uchun ham to'g'riroq
javob: do'kon egasi mamlakat aholisining eng yaxshi besh foizi nima
ekanini bilmaydi.

**`can_seed` — `accepts_members` ning inkori emas.** Provayder o'zi
to'ldiradigan auditoriyaga odam yuklab bo'lmaydi, lekin u mukammal manba.
Ikkalasini bitta ustundan o'qish pikerdan foydaliroq yarmini olib
tashlardi. Notanish subtype bu yerda `True` beradi —
`accepts_members` dagi teskari yo'nalish, chunki bu tomonda hech qanday
shaxsiy ma'lumot harakat qilmaydi.

**`origin` — `ExternalRef`, yalang'och ID emas**, va bu bu paketda
boshqa hech qayerda bunchalik muhim emas. Qolgan har bir ID noto'g'ri
chaqiruvga tushsa tanib olinadi — sahifa ID si pixel ID siga o'xshamaydi.
Ikkita auditoriya ID si esa bir-biridan farq qilmaydi.

## 0.5.0 — 2026-08-25

Ayirib quriladigan auditoriya. MINOR: mavjud qiymatlar o'zgarmadi.

### Qo'shildi
- `refs.AudienceAction` ga uchta qiymat: `visited_not_purchased`,
  `added_to_cart_not_purchased`, `engaged_not_messaged`.

**Har biri bitta harakat, ikkita emas.** «Kirgan va xarid qilmagan» — biznes
so'raydigan bitta narsa, va u shu yerda bitta `action` bo'lib qoladi. Buni
ikkita blokli hujjat bilan ifodalash provayderning ishi. Muqobili —
ikkinchi ixtiyoriy `action` maydoni — ayirishni domen obyektiga, u yerdan
esa uni chizadigan har bir ekranga olib chiqardi: ikkita ro'yxat va
orasida «bundan tashqari» degan so'z aynan mahsulot qochadigan lug'at.

Juftlikni chaqiruvchi o'zi qo'shishiga ruxsat berilmagani ataylab: to'qqiz
harakatning kvadrati — ma'nosi yo'q sakson bitta auditoriya. Uchtasi —
haqiqatan so'raladiganlari.

## 0.4.0 — 2026-08-25

Qoida bilan quriladigan auditoriya. MINOR.

### Qo'shildi
- `dto.AudienceRuleDTO` — auditoriya nimadan qurilishi: manba turi, odam
  nima qilgani, manba ref'i, necha kun. **To'rtta maydon ham domen
  so'zi.** `dict` emas: shaffof o'tkazilgan qoida hujjati neytral nom
  ostidagi Meta JSON'i bo'lardi va ikkinchi provayder uni ishlatolmasligini
  bilish uchun parse qilishi kerak bo'lardi.
- `dto.RuleSupportDTO` — provayder qaysi juftlikni quradi va necha kungacha
  qaraydi. Statik javob, chaqiruvsiz: forma **hech kim tugma bosmasdan
  oldin** chizilishi kerak.
- `ports.AudienceSourcePort.supported_rules`, `.create_rule_audience` —
  `create_audience` kengaytirilmadi, chunki post-shartlar teskari: u
  **bo'sh** idish quradi, bu esa provayder to'ldiradigan va hech qachon
  yuklab bo'lmaydigan obyekt.
- `refs.AudienceSource` (`pixel` · `page` · `lead_form`),
  `refs.AudienceAction` (9 ta), `refs.Level` ga `"pixel"`.
- `dto.AudienceDTO.rule_raw`, `.retention_days` — ko'zguda xom saqlanadi.
  Qaytishda parse qilinmaydi: bularning ko'pi Ads Manager'da Meta'ning
  butun lug'ati bilan qurilgan va parser yo hammasini tushunishi, yo
  tushunmaganini jimgina tashlashi kerak bo'lardi.
- `unavailable.Unavailable` — ikkala yangi metod.

## 0.3.0 — 2026-08-25

Bitta odamni auditoriyadan chiqarish. MINOR: portga metod qo'shildi,
mavjud imzolar o'zgarmadi.

### Qo'shildi
- `ports.AudienceSourcePort.remove_members` — yuborilgan odamni qaytarib
  olish. `delete_audience` hammani o'chiradi, bu bittasini chiqaradi.
  Xeshlangan holda, chunki plaintext yo'qolgan bo'lsa chiqarish ham
  imkonsiz: provayder ro'yxatni qaytarib o'qitmaydi, ya'ni yagona dastak —
  odamni u yerga qo'ygan digest'ning o'zi.
- `unavailable.Unavailable.remove_members`.

### O'zgardi
- `dto.MemberUploadDTO` — endi ikkala yo'nalishga javob beradi (qo'shish
  va chiqarish bir xil ikkita sonni qaytaradi). Maydonlar o'zgarmadi,
  faqat docstring.

## 0.2.0 — 2026-08-25

Beshinchi port. `ProviderBundle` endi beshta portni talab qiladi — MINOR,
chunki port qo'shilgani mavjud imzolarni o'zgartirmaydi.

### Qo'shildi
- `ports.AudienceSourcePort` — advertiser egalik qiladigan auditoriyalar:
  `list_audiences`, `get_audience`, `create_audience`, `add_members`,
  `delete_audience`. `AudiencePort` dan alohida, chunki chegara umr va
  egalikda: u bitta adsetning spec'i haqida, bu akkauntga tegishli va
  undan uzoq yashaydigan obyekt haqida
- `dto.AudienceDTO`, `dto.AudienceStateDTO` — auditoriya va provayderning
  ikki holati (`processing`, `readiness`), kodlar sanab chiqilmagan
- `dto.AudienceMemberDTO` — **faqat SHA-256 hex digest.** Validator ochiq
  matnni qabul qilmaydi: xeshlanmagan PII provayder paketiga tipning o'zi
  tufayli yeta olmaydi
- `dto.MemberUploadDTO` — yuklash natijasi (`received`, `invalid`).
  `ActionResult` emas: u «nima qo'llandi va nima jim tashlandi» ga javob
  beradi, bu esa sanoq
- `refs.Level` ga `"audience"`
- `registry.ProviderBundle.audience_sources` (default'siz)

### Tuzatildi
- `Unavailable` endi `AudiencePort` ning **to'rttala** metodini ham
  implement qiladi. Ilgari faqat `apply` bor edi, ya'ni `find_interests`,
  `find_locations` va `estimate_reach` protokolni qanoatlantirgandek
  ko'rinib, chaqirilganda `AttributeError` bilan yiqilardi — aynan shu
  klass oldini olish uchun yozilgan xato

## 0.1.0 — 2026-08-16

Birinchi versiya. Paket `core/contracts.py` dan ajratildi.

### Qo'shildi
- `refs.ExternalRef` — provayder, daraja va tashqi ID uchun yagona tip
- `dto` — `CampaignDTO`, `StatusDTO`, `MetricsDTO`, `LeadDTO`,
  `ActionResult`
- `ports` — `CampaignControlPort`, `MetricsPort`, `LeadSourcePort`,
  `AudiencePort`
- `registry` — provayder ro'yxati. Provayder solishtirish faqat shu yerda
- `errors` — provayderdan mustaqil xato ierarxiyasi
