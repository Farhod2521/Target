# Ofis «Statistika» — backend va frontend qo'llanmasi

Backend: `feat/office-stats` shoxi. Migratsiya yo'q, yangi jadval yo'q: hamma raqam
mavjud jadvallardan o'qiladi. Fayllar:

- `app/modules/backoffice/selectors/stats.py`: barcha hisob-kitob
- `app/modules/backoffice/routers/stats.py`: `GET /office/stats` va `GET /office/stats/start-lost`
- `app/modules/backoffice/schemas.py`: `StatsOut`, `StatsLostOut` (OpenAPI shu yerdan)
- `tests/pg/test_office_stats.py`: raqamlar, ruxsat va N+1 yo'qligi

## 0. Deploy qoidasi: backend va front BIRGA chiqadi

Front'da `apps/office/src/pages/stats/Stats.tsx` sahifasi bor. U Django'dan ko'chirilgan
(«har bir mijozning reklamasi», `?davr=&tartib=`) va faqat mock bilan ishlaydi. U ham
`GET /office/stats` ni chaqiradi, lekin boshqa shakl kutadi (`StatsPage`, `items`).

Backend endi `/office/me` → `sections` ichida `"stats"` ni yuboradi (Finance va Owner).
Shu zahoti menyuda «Statistika» paydo bo'ladi. Eski front esa yangi javobni o'qiy olmay
sinadi. Shuning uchun:

1. Eski `Stats.tsx`, `packages/api/src/officeStats.ts` va mock'idagi `officeStats.ts`
   handler yangi sahifa bilan almashtiriladi. Eski «har bir reklama» jadvali kerak emas:
   mijozning reklamalari mijoz kartasida bor.
2. Backend va front bitta deploy'da chiqadi.

## 1. Kim ko'radi va qayerda

| | |
|---|---|
| Ruxsat | Finance va Owner (`MONEY_ROLES`). Boshqalarga **404** |
| `/office/me` → `sections` | `"stats"`. Tartibda `"home"` dan keyin keladi |
| Menyu | Mavjud `["stats", "chart", "Statistika"]` qatori, route `/ofis/statistika/` |
| Dashboard | Alohida qoladi (6-bo'limga qarang) |

## 2. So'rov

```
GET /api/v1/office/stats?period=30
GET /api/v1/office/stats?period=range&since=2026-10-01&until=2026-10-31
```

`period`, `since`, `until` Dashboard'dagi bilan bir xil: `today`, `7`, `30` (default),
`month`, `year`, `range`. Javobdagi `window` ham Dashboard'niki bilan bir xil
(`window.periods` tugmalar ro'yxati, `window.refused` sana noto'g'ri bo'lganda sabab).
Davr tanlagichini Dashboard'dagi `Takings.tsx` dan qayta ishlating.

Ekran URL'i: `/ofis/statistika/?davr=30`, `?davr=range&dan=…&gacha=…`. Bu Dashboard
bilan bir xil kalitlar.

Javob bitta so'rovda keladi: backendda taxminan 40 ta SQL so'rov, bu son mijozlar soniga
bog'liq emas (test buni tekshiradi). Bloklarni alohida yuklash shart emas. Lekin
`keepPreviousData` qo'ying: davr almashganda sahifa sakramasin.

### Pul va dollar qanday keladi

| Maydon | Birlik | Ko'rsatish |
|---|---|---|
| `*_minor` | Valyutaning tiyini (`money.currency`, `plans.currency`, odatda UZS) | `formatMoney({minor, exponent})`, Dashboard'dagi kabi |
| `*_micros` (faqat `ai`) | USD'ning 1/100 000 000 qismi | `dollar = micros / ai.micros_per_unit`. 1 dollardan kichik bo'lsa 2–4 kasr xona: `$0.0312`, kattasi `$12.40` |
| `*_pct` | Foiz, bir kasr xona, **yoki `null`** | `null` = «hisoblab bo'lmaydi» (bo'luvchi 0). «—» deb ko'rsating, **0%** deb emas |

## 3. Ekran tuzilishi (tavsiya)

Tepada sarlavha «Statistika» va davr tanlagich. Keyin bloklar shu tartibda keladi:
eng muhimi tepada, tafsilot pastda.

```
┌───────────────────────────────────────────────────────────────┐
│ KPI qatori (`headline`): 6 ta raqam, oldingi davrga nisbatan ↑↓ │
├───────────────────────────────────────────────────────────────┤
│ Dinamika (`series`): ustunli grafik, ko'rsatkich tanlanadi     │
├──────────────────────────────┬────────────────────────────────┤
│ Hozirgi holat (`statuses`)    │ Yaqin uzaytirishlar: 7/30 kun,  │
│ to'layapti/sinov/tugagan/yo'q │ kartasi borlari                 │
├──────────────────────────────┬────────────────────────────────┤
│ A. Tarif zinapoyasi (donut)  │ B. Start → Standart            │
│    qizil / sariq / yashil     │    konversiya + yo'qotish       │
│                               │    sabablari (bosiladi)         │
├──────────────────────────────┴────────────────────────────────┤
│ C. Mijoz yo'li (voronka): 9 qadam, har birida "tushib qoldi"   │
├──────────────────────────────┬────────────────────────────────┤
│ D. Tariflar: kim, necha marta │ E. Doimiy mijozlar + saqlanish │
│    (jadval + 1/2/3+ bar)      │    (churn, qaytganlar, kogorta) │
├──────────────────────────────┴────────────────────────────────┤
│ F. AI xarajati ($): oyma-oy, maqsad, model, tarif, top-10      │
├──────────────────────────────┬────────────────────────────────┤
│ G. Biznes turlari (donut/bar) │ H. Mijoz turlari: rol, kirish   │
│    + shaharlar                │    usuli, til, UTM manba        │
├──────────────────────────────┴────────────────────────────────┤
│ I. Pul: nima sotildi, qanday to'landi, ARPU, LTV, avtoto'lov   │
│ J. Foydalanish: to'layotganlar qaysi qismdan foydalanadi        │
└───────────────────────────────────────────────────────────────┘
```

Telefonda hammasi bitta ustun bo'ladi, tartib o'zgarmaydi. Jadvallar gorizontal
siljiydi, sahifa siljimaydi.

### UI/UX talablari

- **Ranglar** (foydalanuvchi qarori): qizil, sariq, yashil. `--danger`/`--warn`/`--ok`
  matn uchun mo'ljallangan, yorug' rejimda grafik bo'yog'i sifatida bir-biridan
  ajralmaydi (rang ko'rligi tekshiruvidan o'tmadi). Shuning uchun `stats.css`'da
  grafik uchun alohida tokenlar bor: `--st-red`, `--st-yellow`, `--st-green`. Ular
  yorug' va dark rejim uchun alohida qiymatga ega. Komponentlar rangni faqat shu
  tokenlar orqali oladi, hex yozilmaydi.
- **Rangning o'zi yetmaydi**: har bo'lak yonida yorliq, son va foiz bo'lsin
  («Faqat Start · 412 · 57%»). Rang ajrata olmaydigan foydalanuvchi ham o'qiy olishi kerak.
- **Donut**: `packages/ui/src/charts` da donut yo'q. `LineChart`/`BarChart` uslubida SVG
  `DonutChart` qo'shing (yangi kutubxonasiz). Markazda jami son turadi, bo'lak ustiga
  borganda tooltip chiqadi, bo'lakka bosilsa legend qatori ajralib turadi.
  `aria-label`'da hamma bo'laklar matn bilan yozilsin.
- **Bo'sh holat**: ma'lumot yo'q bo'lsa (masalan `ladder.total = 0`), bo'sh grafik
  chizmang: «Bu davrda to'lov yo'q» degan qisqa matn chiqsin.
- **Yuklanish**: har blok o'z skeleton'i bilan chiqadi (Home'dagi `Loading` kabi).
- **Izohlar**: har blok sarlavhasi yonida `ⓘ` tooltip turadi. Matnlari 5-bo'limdagi
  «Ta'riflar»da. Raqamni noto'g'ri tushunmaslik uchun bu muhim.
- **Davr va «holat»**: ba'zi bloklar davrga emas, **davr oxiri** yoki **hozirgi holat**
  bo'yicha. Ular sarlavhada kichik yozuv bilan belgilanadi: «davr oxiriga», «hozir».
  Qaysi blok qanaqaligi 4-bo'limda.
- **Raqamlar**: `formatNumber` bilan, foizlar `formatPercent` bilan.

## 4. Bloklar va maydonlar

### KPI. `headline`: tepadagi qator

6 ta raqam, har birida `value` (shu davr), `before` (oldingi xuddi shuncha kun) va
`change_pct` keladi:
`plan_takings_minor` (tarif tushumi), `signups`, `first_buyers` (birinchi marta
to'laganlar), `reached_yellow` (Standart yoki undan yuqoriga birinchi marta
chiqqanlar, to'g'ridan Pro olgan ham), `reached_green`,
`ai_per_customer_month_micros`.
↑ yashil, ↓ qizil bilan ko'rsating. Faqat AI'da teskari: oshsa qizil. `change_pct: null`
bo'lsa strelka chiqmaydi.

### Dinamika. `series`: davr ichida ustunma-ustun

`unit` (`day`/`week`/`month`) Dashboard'dagi kabi. `bars[]` har bir ustun uchun:
`key`, `label`, `hint`, `signups`, `first_buyers`, `reached_yellow`, `reached_green`,
`plan_takings_minor`. Grafik tepasida segment turadi: «Ro'yxatdan o'tish · Yangi
xaridor · Standart'ga o'tish · Yashil · Tushum». Mavjud `BarChart` ishlatiladi.

### Holat. `statuses`: hamma mijozlar hozir

`rows[]`: `paying` (to'layapti), `trial` (sinovda), `ended` (muddati tugagan), `never`
(hech qachon obuna bo'lmagan). Har birida `customers` va `share_pct`, jami `total`.
Yonida: `ending_7` / `ending_30` (pullik muddati 7 / 30 kunda tugaydiganlar) va
`ending_7_with_card` / `ending_30_with_card` (ulardan kartasi bog'langan, ya'ni o'zi
uzayadiganlar). «30 kunda 42 ta tugaydi, 30 tasida karta bor» deb ko'rsating.

### O'sish. `growth`: promo va referal (davr ichida)

`promo_used`, `promo_customers`, `promo_discount_minor`, `promo_days` (promo bergan
kunlar); `referred` (referal havola bilan kelganlar), `referred_paid`,
`referred_paid_pct`, `referrers` (taklif qilganlar), `rewards`, `rewards_minor`
(to'langan referal mukofotlari). Kichik kartochka ko'rinishida chiziladi. 3-ustundagi
`I. money` yonida turadi.

### A. `ladder`: tarif zinapoyasi (donut, davr oxiriga)

Davr oxirigacha kamida bitta pullik tarif to'lagan har mijoz bitta rangga tushadi:

| `key` | Rang | Kim |
|---|---|---|
| `red` | Qizil | Start olgan, Standart va undan yuqorisini olmagan |
| `yellow` | Sariq | Standart'ni **bir marta** olgan |
| `green` | Yashil | Standart'ni **2+ marta** olgan **yoki** Pro/Enterprise olgan |
| `other` | Kulrang | Boshqa tarif (test). Faqat 0 bo'lmasa keladi |

`segments[]`: `customers`, `share_pct`, `new_in_window` (shu rangga aynan shu davrda
yetganlar). Legend'da «+N shu davrda» deb ko'rsating.
`yellow_from_start` / `yellow_direct`: sariqlarning nechtasi Start orqali kelgan,
nechtasi to'g'ri Standart olgan. Sariq bo'lak tooltip'ida ko'rsating.

### B. `start`: Start → Standart (davrdagi Start xaridorlari)

Kogorta: **birinchi Start'ini shu davrda to'laganlar**.

| Maydon | Ma'no |
|---|---|
| `started` | Kogortadagi mijozlar |
| `in_start` | Start'i hali tugamagan, ular hali hisobga olinmaydi |
| `due` | Standart'ga o'tgan yoki Start'i tugagan mijozlar |
| `moved` / `moved_pct` | O'tganlar; foiz = `moved / due`. **Asosiy KPI** |
| `moved_to[]` | Qaysi tarifga o'tgan (Standart / Pro) |
| `median_days_to_move` | Start'dan keyin necha kunda o'tgan (median) |
| `lost` | O'tmagan va Start'i tugagan |
| `lost_reasons[]` | Har biri **birinchi qilinmagan qadam** bo'yicha bir marta sanaladi |

`lost_reasons[].key` tartibi: `deleted` (hisobini o'chirgan), `meta` (Meta'ni
ulamagan), `setup` (tayyorgarlikni yakunlamagan), `launch` (reklama chiqarmagan),
`lead` (lid kelmagan), `tried` (lid kelgan, tarif hisobi ochilgan, lekin to'lov
o'tmagan: qo'lda urinish ham, kartadan avtoto'lov rad etilgani ham shu yerga tushadi),
`silent` (lid kelgan, hisob ochilmagan). `meta` va voronkadagi «Meta'ni uladi» faqat
Meta ulanishini sanaydi, Google Ads ulanishi kirmaydi. Gorizontal bar bilan ko'rsating. Har qatorga bosilganda drawer
ochiladi:

```
GET /api/v1/office/stats/start-lost?reason=meta&period=30
→ {window, reason, label, total, deleted, rows:[{customer:{id,name,email}, email, phone, joined_at}]}
```

`rows` ko'pi bilan 100 ta, eng yangi ro'yxatdan o'tgan tepada. `deleted` ro'yxatda
yo'q, faqat soni bor. Qatorga bosilsa mijoz kartasi ochiladi (`clientUrl(id)`).
Noma'lum `reason` → 404.

### C. `funnel`: mijoz yo'li (davrda ro'yxatdan o'tganlar)

`steps[]` doim 9 ta, shu tartibda: `joined`, `profile` (telefon va rol), `meta`,
`setup`, `launch` (birinchi reklama), `lead`, `paid` (birinchi to'lov), `standard`
(Standart yoki yuqori), `green`.

Har qadamda: `customers`, `of_joined_pct`, `of_previous_pct`, `dropped` (shu qadamdan
**oldin** to'xtaganlar). Keyingi qadamga yetgan mijoz oldingilarni ham o'tgan deb
sanaladi. Shuning uchun voronka doim kamayib boradi va `dropped` aniq «shu yerda
yo'qoldi» degani.

Ko'rinishi: gorizontal pog'onali voronka. Qadamlar orasida qizil «−N (X%)» belgisi
turadi. Eng katta `dropped` qadami ajratib ko'rsatiladi: «Eng ko'p shu yerda
yo'qolyapti».

### D. `plans`: tariflar (davr ichida)

`rows[]`, har tarif uchun: `buyers` (alohida mijozlar), `bills`, `share_pct` (davrdagi
tarif to'lovlaridan ulushi; soni har qanday valyutadagi to'lov bo'yicha), `amount_minor`
(faqat `plans.currency`'da, tarif hisobidagi qo'shimcha sahifa va CRM o'rni puli
kirmaydi), `first_time` (mijozning
birinchi to'lovi), `second_time`, `third_or_later`, `same_plan_again` (oldingi to'lovi
ham shu tarif bo'lgan).
Jadval ko'rinishida: Tarif · Xaridor · To'lov · Summa · 1-marta · 2-marta · 3+ ·
Shu tarifni yana.

`times[]` (davr oxiriga): har mijoz necha marta tarif to'lagan, `1` / `2` / `3+`.
Kichik ustunli grafik.

### E. `loyal` va `keeping`: doimiy mijozlar va saqlanish

`loyal` (davr oxiriga): «Doimiy» = **bitta tarifni ketma-ket 3 marta** sotib olgan.
Bu foydalanuvchi qarori, `run = 3`. Maydonlari: `customers`, `share_pct` (to'lagan
hamma mijozdan), `still_live` (ulardan hozir obunasi bor), `new_in_window`, `plans[]`.

`keeping` (davr ichida):

| Maydon | Ma'no |
|---|---|
| `paid_at_start` / `paid_at_end` | Davr boshida / oxirida to'langan muddati bor mijozlar |
| `lost` | Davr boshida to'lov muddati bor edi, davr oxirida yo'q |
| `churn_pct` | `lost / paid_at_start` (bir guruh ichida). Boshida hech kim bo'lmasa `null` |
| `came_back` | Uzilishdan keyin qayta sotib olganlar |
| `cohorts[]` | Oxirgi 6 oy. Har oy birinchi marta to'laganlar (`customers`) va ulardan 30, 60 … 180 kundan keyin hali to'langan muddati borlari (`kept_pct[6]`). `null` = hali vaqti kelmagan |

Kogorta jadvali issiqlik xaritasi ko'rinishida chiziladi: foiz qancha baland bo'lsa,
yashil shuncha to'q. `null` katak bo'sh qoladi.

### F. `ai`: AI xarajati, dollarda (davr ichida)

| Maydon | Ma'no |
|---|---|
| `cost_micros` | Mijozlar uchun jami xarajat |
| `staff_cost_micros` | Xodimlar hisoblari, alohida. Asosiy raqamga qo'shilmaydi |
| `per_customer_month_micros` | **Mijoz boshiga oyiga o'rtacha**: jami ÷ `customer_months` (2 oy ishlatgan mijoz 2 marta sanaladi). 28 kundan qisqa davrda (bugun, 7 kun): mijoz boshiga xarajat 30 kunga keltiriladi, shunda raqam har davrda bir xil ma'noda |
| `customers`, `calls`, `tokens{input,output,cache_read,cache_write}` | |
| `months[]` | Har kalendar oy: mijozlar, jami, o'rtacha, **median** |
| `purposes[]` | Nimaga ketgan (Suhbat, Kunlik hisobot, Rad etish izohi…) |
| `models[]` | Qaysi model |
| `plans[]` | Mijozning **hozirgi** tarifi bo'yicha: «Sinov», «Obunasiz» ham bor; har birida oyiga o'rtacha |
| `top[]` | Eng qimmat 10 mijoz (`id`, `email`) |

KPI'da `per_customer_month_micros` turadi. Oyma-oy ko'rinish uchun `BarChart`
(o'rtacha va median) ishlatiladi. `purposes` va `plans` jadval ko'rinishida.

### G. `businesses`: biznes turlari (hozir)

`directions[]`: `key` (yo'nalish kaliti, `custom` = o'zi yozgan, `none` = tanlanmagan),
`label`, `businesses`, `share_pct`, `owners`, `paying_owners`, `paying_pct`,
`new_in_window`. `custom` va `none` ro'yxat oxirida keladi.
Bir mijozda bir nechta biznes bo'lishi mumkin. Shuning uchun `total` (bizneslar) va
`owners` (mijozlar) alohida keladi. Ekranda ikkalasini ham yozing.

`custom_top[]`: o'zi yozgan turlarning eng ko'p uchraydigan 10 tasi.
`cities[]`: top-10 shahar, `no_city` esa shahri kiritilmaganlar soni.

Ko'rinishi: yo'nalishlar uchun donut, 8 tadan ko'p bo'lsa gorizontal bar. Yonida
«To'layotgan %» ustuni turadi.

### H. `people`: mijoz turlari (hozir, davrdagi yangilari bilan)

To'rtta bir xil shakldagi kesim: `roles` (Biznes egasi / Targetolog / «—»),
`signup_via` (Email / Google / Telegram), `languages`, `utm_sources` (top-10,
qolganlari `_rest` «Boshqalar» qatorida).
Har `rows[]` qatorida: `customers`, `share_pct`, `joined_in_window`, `ever_paid`,
`paid_pct` (shu turdan to'laganlar foizi), `paying_now`.
Ko'rinishi: tab yoki segment bilan almashadigan bitta kartochka, ichida foizli bar va
«to'lash %» ustuni.

### I. `money`: pul (davr ichida, asosiy valyutada)

| Maydon | Ma'no |
|---|---|
| `takings_minor`, `bills` | Tushum: tarif + qo'shimcha sahifa + CRM o'rni |
| `kinds[]` | `plan` / `pages` / `seats` ulushi. Uzaytirish hisobi sahifa va CRM o'rnini ham o'z ichiga oladi: ularning puli `pages`/`seats`ga ajratiladi, `bills` esa hisob turi bo'yicha |
| `methods[]` | Qanday to'langan: `payme`, `multicard` (Rahmat karta), `manual:cash`/`transfer`/`card`, `wallet`, `other` |
| `per_payer_minor` | **ARPU**: tarif tushumi ÷ to'lagan mijozlar |
| `lifetime_per_customer_minor` | **LTV**: davr oxirigacha bir xaridor olib kelgan tarif puli |
| `wallet_minor`, `discount_minor` | Hamyondan to'langani, berilgan chegirmalar |
| `refunded`, `refunded_minor` | Qaytarilganlar |
| `paying_now`, `autopay_now`, `autopay_pct` | Hozir to'layotganlar va ulardan kartasi bog'langanlar |

Bu raqamlar Dashboard tushumidan biroz farq qilishi mumkin: Statistika xodimlarning
to'lovlarini sanamaydi, Dashboard esa sanaydi.

### J. `usage`: foydalanish

`parts[]` hozir to'layotgan mijozlar ichidan: `launch` (30 kunda reklama chiqargan),
`leads` (30 kunda lid olgan), `crm`, `templates`, `sheets`, `lead_chats`, `montage`,
`telephony`, `google`, `autopay`. Har birida `customers` va `share_pct`. Foizli
progress bar bilan ko'rsating.
Davr ichida: `launched`, `failed`, `failed_pct`, `launchers`, `leads`, `lead_owners`,
`leads_per_owner`.

## 5. Ta'riflar (ⓘ tooltip matnlari)

- **Mijoz**: xodim ham, CRM menejer logini ham emas. O'chirilgan hisobning to'lovi
  email bo'yicha sanaladi.
- **Tarif xaridi**: to'langan, arxivlanmagan tarif hisobi. Pul yoki hamyon orqali
  to'langan bo'lishi kerak. Promo bilan 0 ga tushgan hisob sovg'a, xarid emas.
  Sahifa va CRM o'rni hisoblari tarif xaridi emas.
- **Doimiy**: bitta tarifni ketma-ket 3 marta sotib olgan.
- **To'langan muddat**: to'lovlar ketma-ket qo'shiladi. Muddat tugaganidan keyin 3 kun
  ichida uzaytirilgani uzilish hisoblanmaydi. Ofis bergan kunlar va sinov kunlari
  hisobga kirmaydi.
- **Voronka**: keyingi qadamga yetgan mijoz oldingilarni ham o'tgan hisoblanadi. Meta
  uzilganda ulanish va tayyorgarlik belgisi o'chadi. Shuning uchun reklama chiqargan
  mijoz ikkalasini ham qilgan deb sanaladi.
- **AI oyiga o'rtacha**: mijozlar xarajati ÷ mijoz-oylar soni.

## 6. Dashboard bilan munosabat

Statistika **alohida sahifa** bo'ladi. Dashboard «hozir nima qilish kerak» ekrani
bo'lib qoladi: navbatlar, muammolar, so'nggi to'lovlar, bugungi tushum. Statistika esa
«biznes qanday ketyapti» ekrani. Ikkalasini bitta sahifaga qo'shib bo'lmaydi: Support
Dashboard'ni ko'radi, pul raqamlarini ko'rmaydi.

Dashboard'dan olib tashlanadigan yagona narsa: «Loyiha statistikasi · Tez orada»
kartochkasi (`Home.tsx`). Uning o'rniga kichik «Statistika» kartochkasi qo'yiladi:
mini-donut, Start→Standart % va AI/mijoz/oy, hammasi `/ofis/statistika/` ga havola.
Bu kartochka faqat `sections` ichida `"stats"` bo'lsa chiqadi. Ma'lumotini
`GET /office/stats?period=30` dan oladi.

## 7. Front tekshiruv ro'yxati

- [ ] Eski `Stats.tsx`, `officeStats.ts` va mock handler yangi sahifa bilan almashtirildi
- [ ] OpenAPI qayta generatsiya qilindi (`StatsOut`, `StatsLostOut`)
- [ ] Live bridge va mock handler yangi shaklda
- [ ] Davr tanlagich Dashboard'niki, URL kalitlari `davr`, `dan`, `gacha`
- [ ] `null` foizlar «—» bo'lib ko'rinadi
- [ ] Dollar `micros / micros_per_unit`, kichik summalarda kasr xona bor
- [ ] Donut: qizil/sariq/yashil tokenlar, matnli legend, `aria-label`
- [ ] `start-lost` drawer: 100 tagacha qator, mijoz kartasiga havola, `deleted` soni
- [ ] Bo'sh holat va skeleton har blokda
- [ ] Telefon kengligida bitta ustun, sahifa gorizontal siljimaydi
- [ ] Support roli: menyuda «Statistika» yo'q, URL to'g'ridan ochilsa 404 sahifasi
- [ ] Dark mode va real brauzerda ko'zdan kechirildi
- [ ] `pnpm -r typecheck` exit kodi 0
