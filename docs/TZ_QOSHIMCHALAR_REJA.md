# TZ qo'shimchalari: TZ ↔ kod solishtiruvi va ish rejasi

Manba: `tz-qoshimchalar.md` (7 band). Asosiy qoida: **hamma narsa TZ'ga mos bo'ladi.**
Kod holati 2026-11-07 dagi backend `origin/main fb28022` va front `origin/main 5f73881` bo'yicha. Meta hujjati Marketing API v26.0 bo'yicha. Raqamlar prod nusxasidan (`prodcopy-db`, ma'lumot 2026-11-05 gacha).
Kod yozilmagan.

Belgilar:
- **Holat:** ✅ TZ'ga mos · 🟡 qisman bor, o'zgartirish kerak · ❌ yo'q, yangidan qilinadi.
- **Front** ustuni: shu backend o'zgarishi uchun frontda ham ish kerakmi. "—" = frontda ish yo'q.

---

## 0. Kod yozishdan oldin

### 0.1. Meta hujjatida yo'q narsalar: prod bazasidan tekshirildi (2026-11-07)

Alohida test akkaunti kerak emas. Javoblar prod bazasidagi (nusxa 2026-11-05) Ads Manager'da yaratilgan reklamalardan olindi. Bazadan javobi chiqmaganlari TZ va Meta hujjati bo'yicha quriladi va deploy'dan keyin prod'da kuzatiladi: Meta rad etsa, xato action jurnaliga yoziladi va userga ko'rinadi.

| # | Savol | Natija |
|---|---|---|
| T5 | `explore`, `explore_home` qabul qilinadimi? | ✅ Ha. Oxirgi 30 kunda boshlangan faol guruhlarda `explore` 42 ta, `explore_home` 90 ta. Bizning `RETIRED_POSITIONS` xato — tuzatiladi. Jami bazada: story 10 432, stream 10 401, reels 10 381, profile_feed 9 225, explore_home 6 519, explore 5 171, ig_search 4 346, profile_reels 2 009, reels_overlay 404. |
| T6 | Tez savolga avtomatik javob ishlaydimi? | ✅ Ha. 4 669 ta kreativda `ice_breakers[].response` bor. Ko'pi bilan nechta savol bo'lishini bazadan aniq sanab bo'lmadi; prod'da ishlayotgan 4 ta chegarasi qoladi. |
| T7 | Qaysi maqsad qaysi event'ni oladi? | ✅ `OUTCOME_LEADS`: LEAD 1 185, COMPLETE_REGISTRATION 281, OTHER 128, SUBMIT_APPLICATION 4. `OUTCOME_SALES`: PURCHASE 21, CONTENT_VIEW 7, OTHER 4, COMPLETE_REGISTRATION 3, START_TRIAL 2. Custom conversion shakli: `{"pixel_id", "custom_conversion_id", "custom_event_type"}` (3 ta guruhda). |
| T1 | E'londa creative almashtirilsa nima bo'ladi? | Bazadan javob yo'q. Hujjat bo'yicha quriladi; UI'da TZ 2.4 dagi ogohlantirish chiqadi. |
| T2, T3 | `/copies` nimani nusxalaydi, boshqa maqsadli kampaniyaga ham bo'ladimi? | Bazadan javob yo'q. Hujjat bo'yicha quriladi, Meta xatosi userga ko'rsatiladi. |
| T4 | Bo'sh `audios` e'lonni dinamik qilib qo'yadimi? | Bazadan javob yo'q (`asset_feed_spec` bazada saqlanmaydi). Yaratilgach GET bilan tekshiriladi (TZ 7.1). |

### 0.2. TZ yozganidan farq qiladigan Meta faktlari
- **7.4.** `GET /act_{id}/recommendations` endpointi yo'q: 404 qaytadi, hujjatda ham yo'q. Opportunity score API orqali berilmaydi. Tavsiyalar faqat kampaniya va guruhdagi `recommendations` maydonida keladi. Prod nusxasida bunday tavsiya jami 35 ta: "Ad Set Ended" (21) va "Targets Multiple Countries" (14).
- **2.1–2.3.** Sinxron nusxa ichida ko'pi bilan 3 ta e'lon bo'ladi, asinxron batch bilan 51 tagacha. Undan ko'p bo'lsa, `/copies` bilan nusxalab bo'lmaydi.
- **3.** Meta'dagi nom `INITIATED_CHECKOUT`. Pixel statistikasini faqat oxirgi 7 kun uchun olish mumkin.
- **4.** Meta'da kampaniya nomi uzunligiga chegara hujjatlanmagan. TZ'dagi 100 belgi bizning cheklovimiz bo'ladi.
- **7.1.** Joriy 23 ta kalit: adapt_to_placement, add_text_overlay, creative_stickers, description_automation, enhance_cta, image_animation, image_background_gen, image_brightness_and_contrast, image_templates, image_text_translation, image_touchups, image_uncrop, inline_comment, media_type_automation, pac_relaxation, product_extensions, reveal_details_over_time, text_optimizations, text_translation, translate_voiceover, video_auto_crop, video_filtering, video_uncrop. Musiqa bu ro'yxatda emas, u `asset_feed_spec.audios` orqali boshqariladi.

### 0.3. Qarorlar va TZ'da yozilmagan joylar

| # | Savol | Holat |
|---|---|---|
| Q1 | 3× xabar hozirgi 2× "Qimmatlashdi" bilan birga ishlaydimi? | **Qaror:** 3× xabar uning o'rnini oladi. |
| Q2 | Tarix yetmasa, odatiy narx qayerdan olinadi? | **TZ bo'yicha:** 1) onboarding'dagi maqsadli narx; 2) soha o'rtachasi. ⚠️ O'lchov: bir soha ichida lid narxi 25 baravargacha farq qiladi (Ta'lim markazi: $0.11–$2.78). 306 biznesdan 84 tasining sohasi o'zi yozgan nom (yo'nalishi yo'q). Yechilmagan: shunday biznes uchun soha o'rtachasi qayerdan olinadi? |
| Q2a | Sohalar ro'yxati | 13 ta soha bor. Userlar 88 ta o'z nomini kiritgan (84 tasi biznesda ishlatiladi), hammasi "services" presetiga tushgan. Nomlarni o'qib guruhladim: 48 tasi mavjud sohaga to'g'ri keladi (eng ko'pi: do'kon/mebel 18, qurilish 10), ya'ni user ro'yxatdan topa olmagan. 36 tasi yangi guruh: marketing va agentlik 15, IT/dasturlar 7, BAD 4, ishlab chiqarish va ulgurji 4, boshqa 6. **Taklif v2 (tasdiq kutilmoqda):** yo'nalish ham joylashuv kabi qidiruv orqali tanlanadi, lekin faqat **o'zimizning yopiq katalogimizdan**. Erkin matn yo'nalish bo'lmaydi.
- Katalog: Soha (mavjud 18 ta AI preseti) → Yo'nalish. Har bir yo'nalishda uz/ru/en nomlari va sinonimlar bor (lotin va kirill, xato yozilishlar).
- Topilmasa: user eng yaqin sohani tanlaydi (preset ishlaydi) va matn yuboradi. Matn ofis navbatiga tushadi; ofis sinonim yoki yangi yo'nalish qo'shadi va biznes avtomatik bog'lanadi.
- Katalog uchun manba: **Overture Maps taxonomy** (2026-10-21; 2 302 ta kategoriya, ulardan 298 tasi "basic"; faqat inglizcha; schema CC BY 4.0 — atribut ko'rsatiladi; taxonomy faylining o'z litsenziyasi alohida tasdiqlanadi). Ruscha nomlar uchun Wikidata (CC0) va OSM presetlari (ISC). O'zbekcha nomlarni o'zimiz yozamiz: hech bir ochiq manbada yo'q. Yelp, 2GIS, Yandex va Google ma'lumotini saqlash ularning shartlarida taqiqlangan.
- Ishlatilmaydiganlar: Google (saqlash taqiqlangan), Meta `fb_page_categories` (tarjima yo'q, faqat bog'lash uchun), OKED (juda rasmiy).
- Hozir hech bir yo'nalish ulanmagan presetlar: furniture, it_software, agriculture, kids, logistics.
- Mavjud 84 ta erkin matnni ofis xaritalaydi.
- Soha o'rtachasi: yo'nalishda ≥N biznes bo'lsa yo'nalish bo'yicha, aks holda soha bo'yicha; bir mamlakat va valyuta ichida. |
| Q3 | Faqat Instagram | **TZ bo'yicha:** hamma kampaniya turida, xabar kampaniyasida ham (suhbat Instagram Direct'da). **Qaror (user):** odatiy tanlov Instagram. Sahifada Instagram bo'lmasa, userga ogohlantirish: "Instagram ulanmagan. Instagram'da yoqmoqchi bo'lsangiz, Instagram'ni ulang yoki supportga yozing", ikkala yo'lga tugma bilan. **Ochiq:** Instagram ulamagan user reklamani Facebook'da yoqa oladimi yoki launch to'xtaydimi? |
| Q4 | Chastota chegarasi | **TZ bo'yicha:** §6 eski 1.70 / 2.00 / 2.50 qoidaning o'rniga keladi (2.00 / 2.50 / 3.00). §1.4 dagi "Charchoq" esa nisbat bilan o'lchanadi (≥ 2.0). **TZ'da yo'q:** eski AI diagnozidagi chastota signali va "auditoriyani kengaytirish" qoidasi qaysi chegarani oladi? Taklif: 2.00. 30 kunda bu ikkalasi bir marta ham ishlamagan. |
| Q5 | Meta tavsiyalari | **TZ bo'yicha:** userga ko'rsatilmaydi. AI'ga faqat texnik tavsiyalar beriladi. Byudjet, placement va Advantage+ tavsiyalari olib tashlanadi. |

Kod yozishdan oldin javob kerak: Q2 (o'z sohasini yozgan biznes), Q3 (Instagram'siz sahifa), Q4 (eski diagnoz).

---

## 1. TZ ↔ kod solishtiruvi va o'zgarishlar ro'yxati

### 1-band. Lid narxi oshganda ogohlantirish

| § | TZ talabi | Kodda hozir | Holat | O'zgarish (backend) | Front |
|---|---|---|---|---|---|
| 1.1 | Reklama o'chirilmaydi, faqat ogohlantirish beriladi | AI'da avtomatik to'xtatish bor (`agent/services/stop_fruitless.py`, `core/agent/auto_stop.py`). Bu boshqa qoida, 1-bandga tegishli emas | ✅ | — | — |
| 1.2 | Odatiy narx: 90 kun, shu akkauntning oldingi reklamalari, bir xil natija turi (3.3: bir xil event), ≥1000 ko'rsatish va ≥5 natija, CPR va har bir bosqichning medianasi | 14 kunlik kunlar medianasi (`core/agent/usual.py`) va qo'shni guruhlar (`benchmark.peers`). E'lon darajasidagi kunlik metrikalar 180 kun saqlanadi (`AD_METRICS_RETENTION_DAYS`) | ❌ | Yangi hisob: 90 kunlik e'lon medianasi (CPR, CPM, Frequency, Hook, Hold, link CTR, link CPC, forma konversiyasi). O'lchov: hozir ishlayotgan natijali e'lonlarning 87 foizida bu tarix yetarli | — |
| 1.2 | Zaxira 1: onboarding'dagi maqsadli narx | Bunday maydon yo'q (`businesses` modeli) | ❌ | `business`'ga maydon va migratsiya, onboarding API | Onboarding va profilga maydon |
| 1.2 | Zaxira 2: soha o'rtachasi | Hisoblanmaydi. Soha = `business.direction_id` | ❌ | Soha bo'yicha median (Q2 ⚠️) | — |
| 1.3 | Guruh va e'lon darajasi, 3 kunlik oyna, CPR ≥ 3×, natija 0 bo'lsa sarf ≥ 3× | 2× "Qimmatlashdi", faqat guruh, faqat o'z byudjeti bo'lmagan guruh uchun (`core/agent/running_watch.py`) | 🟡 | Yangi qoida. 2× "Qimmatlashdi" olib tashlanadi (Q1) | — |
| 1.3 | Kuniga bir marta tunda tekshiriladi, xabar 09:00–10:00 da | Chastota xabari shu soatda (`FREQUENCY_HOUR = 9`) | 🟡 | Yangi vazifa shu jadvalga qo'shiladi | — |
| 1.3 | Istisnolar: 48 soat bo'lmagan, 72 soat ichida o'zgartirilgan, yetkazishda muammo bor (avval shu muammo haqida xabar) | Bunday istisnolar yo'q. Muammo xabarlari alohida bor (`troubled`, Meta xatolari) | ❌ | Uchala istisno | — |
| 1.4 | Sabab = nisbat (hozirgi ÷ odatiy). 8 qator chegara: CPM ≥1.5, Freq ≥2.0, Hook ≤0.7, Hold ≤0.7, CTR ≤0.7, CPC ≥1.5, forma konv. ≤0.7, Ranking ≤ BELOW_AVERAGE_20 | Diagnoz bor, lekin boshqa qoida: qo'shnilar yoki doimiy chegaralar (`core/agent/signals.py`), har doim bitta sabab | ❌ | Yangi sabab hisobi | — |
| 1.4 | Xabar kampaniyasida Results ÷ Clicks(all), Hook/Hold faqat videoda, ko'pi bilan 2 ta sabab, sabab topilmasa "aniq bitta sabab yo'q" | Yo'q | ❌ | Shu qoidalar | — |
| 1.5 | Xabar matni va 3 ta tugma: yangi kreativ (2.3), to'xtatish (guruh PAUSED), "Kuzataman" | Yo'q | ❌ | Xabar, tugmalar va javob API'si (ilova va Telegram) | Yangi xabar turi va 3 ta tugma |
| 1.6 | Bir guruhga 72 soatda bitta xabar. Narx 2× dan tushsa holat noldan. Bir kunlik xabarlar bitta xabarda | Yo'q | ❌ | Shu qoidalar | — |
| 1.7 | Saqlanadi: adset_id, ad_id, cpr_current, cpr_baseline, baseline_source, causes, response, response_at, cpr_after_7d | Yo'q | ❌ | Yangi jadval va migratsiya | — |

### 2-band. Duplikat va e'lonni tahrirlash

| § | TZ talabi | Kodda hozir | Holat | O'zgarish (backend) | Front |
|---|---|---|---|---|---|
| 2.1 | Kampaniya nusxasi: `/copies` deep_copy, PAUSED, nomga " — nusxa", ko'p bo'lsa fon rejimida va xabar | Yo'q. Meta adapterida `/copies` umuman yo'q | ❌ | Adapter (`/copies`, asinxron batch) va API | "Duplikat" tugmasi va "tayyorlanmoqda" holati |
| 2.2 | Guruh nusxasi: shu yoki boshqa kampaniyaga, ichidagi e'lonlar bilan, PAUSED | Faqat shu kampaniya ichida, mirror'dan qayta yig'iladi, **e'lonlarsiz** (`services/additions.py` → `create_adset`) | 🟡 | `/copies` orqali, boshqa kampaniyaga ham (T3) | Kampaniya tanlovi qo'shiladi |
| 2.3 | E'lon nusxasi: shu, boshqa yoki yangi guruhga. "O'sha kreativ" → `/copies`. "Yangi kreativ" → yangi media yuklanadi, matn, CTA va forma yoki shablon o'zgartirilishi mumkin | Faqat tanlangan guruhga. Media faqat kutubxonadan (yuklash yo'q). CTA o'zgarmaydi | 🟡 | Uch joy, yangi media yuklash, CTA | Duplikat oynasi: qayerga → kreativ → matn |
| 2.3 | Ishlab turgan guruhga qo'shilgan e'lon ACTIVE, yangi guruhda PAUSED | Har doim PAUSED | 🟡 | Holat qoidasi | — |
| 2.3 | Yangi kreativga 7-bo'lim sozlamalari qo'llanadi. Kreativ qo'shilgach chastota va lid narxi holati noldan | Chastota yangi kreativni ko'radi (`newest_ads`). Lid narxi xabari hali yo'q | 🟡 | B7 bilan birga | — |
| 2.4 | Forma almashtirish, ikki variant: shu e'londa (`POST /{ad_id}` creative) yoki yangi e'lon. Faqat ACTIVE formalar. "Yangi forma" tugmasi. Ogohlantirish | Faqat "yangi e'lon + eskisini o'chirish" (`NewAdvert`) | 🟡 | "Shu e'londa" varianti (T1) | Ikki variant va ogohlantirish |
| 2.5 | Xabar shabloni: salomlashish matni, tez savollar, avtomatik javoblar. Saqlash 2.4 dagidek | Faqat launch'da, javobsiz (`metaads/stories.py` → `greeting`). Ishlab turgan e'londa o'zgartirib bo'lmaydi | ❌ | Restage'da shablon va javoblar (T6) | Shablon tahrirlash oynasi |
| 2.6 | Tugmalar: kampaniya (Duplikat, Nom), guruh (Duplikat), e'lon (Duplikat, Forma, Shablon) | Yo'q | ❌ | — | Uchala darajaga tugmalar |

### 3-band. Pixel event'ini qo'lda tanlash

| § | TZ talabi | Kodda hozir | Holat | O'zgarish (backend) | Front |
|---|---|---|---|---|---|
| 3.2.1 | Pixel avtomatik: bitta bo'lsa o'sha, bir nechta bo'lsa 7 kunda eng ko'p event yuborgani. User almashtira oladi | Faol pixel, keyin nomi bo'yicha (`selectors/pixel.py`). Almashtirish bor | 🟡 | Tanlash qoidasi | — |
| 3.2.2 | Event ro'yxati va yonida 7 kunlik son | Sinxronlash bor (`/stats`, `sync_pixel_events`), lekin vaqt oralig'i berilmaydi. Ro'yxatda son yo'q | 🟡 | 7 kunlik son javobga qo'shiladi | Son ko'rsatiladi |
| 3.2.2 | Custom conversion'lar | Yo'q | ❌ | Sinxronlash, tanlash, `custom_conversion_id` (T7) | Alohida guruhda |
| 3.2.3–4 | Lead tipidagi event → `OUTCOME_LEADS`, Purchase/Checkout/Cart → `OUTCOME_SALES`. Ad set `OFFSITE_CONVERSIONS` | Event ro'yxati goal'ning maqsadi bo'yicha filtrlanadi (`core/targeting/conversion_events.py`). Maqsad event bo'yicha tanlanmaydi | 🟡 | Event bo'yicha maqsad tanlash (T7) | Barcha event'lar bitta ro'yxatda |
| 3.3 | Odatda Lead tanlangan, 0 ta → ogohlantirish, <10 → ogohlantirish, bloklanmaydi | Lead odatiy tanlov. Ogohlantirishlar yo'q | 🟡 | Ikki ogohlantirish | Ogohlantirish matni |
| 3.3 | Natija ustunida event nomi ("29 ro'yxatdan o'tish"), nomlar jadvaliga barcha event'lar va custom conversion'lar | Natija nomlari faqat turlar bo'yicha (lead, chat, call, site_lead...) (`metrics/selectors/results.py`) | 🟡 | Har bir event uchun nom | Ustunda ko'rsatiladi |
| 3.3 | Lid narxi solishtiruvi faqat bir xil event bo'yicha | 1-band yo'q | ❌ | B7 da | — |

### 4-band. Nomni tahrirlash

| § | TZ talabi | Kodda hozir | Holat | O'zgarish (backend) | Front |
|---|---|---|---|---|---|
| 4 | Faqat kampaniya nomi o'zgaradi, `POST /{campaign_id}` name | Faqat launch'gacha (`rename_campaign`). Ishlab turgan kampaniya uchun Meta yozuvi yo'q | ❌ | Adapter, action turi, API | — |
| 4 | Bo'sh bo'lmaydi, ≤100 belgi | `LAUNCH_NAME_MAX = 80` | 🟡 | 100 ga | Tekshiruv va xato |
| 4 | UI: nom yonida qalam, shu joyda tahrirlanadi | Yo'q | ❌ | — | Qalam va tahrirlash |
| 4 | Guruh va e'lon nomini user o'zgartirmaydi | Yangi guruh va e'lon qo'shishda nomni user yozadi (`AddGroupIn.name`, `NewAd.name`) | 🟡 | Nom avtomatik beriladi | Nom maydoni olib tashlanadi |

### 5-band. Faqat Instagram

| § | TZ talabi | Kodda hozir | Holat | O'zgarish (backend) | Front |
|---|---|---|---|---|---|
| 5 | `publisher_platforms = ["instagram"]` | 30 kunda: 452 ta "automatic" (Meta o'zi tanlaydi), 98 ta faqat Instagram, 25 ta FB+IG, 3 ta faqat FB. Odatiy tanlov: sahifada Instagram bo'lsa Instagram, aks holda FB | 🟡 | Hamma launch faqat Instagram (Q3) | Rejim tanlovi olib tashlanadi yoki qulflanadi |
| 5 | Barcha Instagram joylashuvlari | `stream, story, reels` (`INSTAGRAM_ONLY_PLACEMENTS`). `explore` va `explore_home` "eskirgan" deb olib tashlanadi (`RETIRED_POSITIONS`) | 🟡 | To'liq ro'yxat (T5) | Joylashuvlar ro'yxati |
| 5 | Hamma kampaniya turida, xabar kampaniyasida ham | Messenger suhbati "automatic"ga qaytariladi (`keep_chat_reachable`). Front'da Messenger tanlovi bor (`Goal.tsx`, `PlanParts.tsx`) | 🟡 | Suhbat faqat Instagram Direct | Messenger tanlovi olib tashlanadi |
| 5 | Mos kelmaydigan joylashuv xatoga aylanmaydi | Juftlik qoidalari bor (`POSITION_NEEDS`) | 🟡 | T5 natijasiga ko'ra | — |
| 5 | Har bir API versiyasida ro'yxat tekshiriladi | Qo'lda | 🟡 | Versiya almashtirish ro'yxatiga yoziladi | — |
| 5 | AI Advantage+ placements taklif qilmaydi | Launch tavsiyasi "automatic"ni taklif qilmaydi (`core/advice.py`), lekin "automatic" rejimi hali bor | 🟡 | "automatic" olib tashlanadi | — |

### 6-band. Chastota bo'yicha yangi qoida

| § | TZ talabi | Kodda hozir | Holat | O'zgarish (backend) | Front |
|---|---|---|---|---|---|
| 6.1 | Guruh darajasi, 7 kun (kam ishlagan bo'lsa, ishga tushgan kundan) | Shunday (`week_frequency.py`: 7 kunlik reach) | ✅ | — | — |
| 6.1 | Tunda tekshiriladi, xabar 09:00–10:00 da | `FREQUENCY_HOUR = 9` | ✅ | — | — |
| 6.1 | ACTIVE va dashboard'ga ulangan akkauntdagi **barcha** guruhlar | Faqat ACTIVE **va bizning platformada yaratilgan** guruhlar (`is_ours`) | 🟡 | `is_ours` sharti olib tashlanadi | — |
| 6.2 | 2.00 / 2.50 / 3.00, har biri bir marta, faqat yuqoriga | 1.70 / 2.00 / 2.50 (`core/agent/frequency.py`) | 🟡 | Chegaralar o'zgaradi | Darajalar nomi va rangi |
| 6.2 | 3.00 xabari kreativ qo'shilmaguncha **yoki frequency 3.00 dan tushmaguncha** yopilmaydi | Faqat eng past chegaradan tushganda yoki yangi kreativ qo'shilganda yopiladi | 🟡 | 3.00 dan tushganda yopiladi | — |
| 6.2 | 2.50 ogohlantirishi dashboard tepasida ham ko'rinadi | `has_pressing_alerts` bor, lekin hech qayerda chaqirilmaydi | 🟡 | Dashboard javobiga qo'shiladi | Dashboard tepasida banner |
| 6.2 | Chastota ustuni rangi shu chegaralar bo'yicha | Yo'q | ❌ | Daraja javobda yuboriladi | Ustun rangi |
| 6.3 | Ikki tugma ilovada ham, Telegram'da ham | Ilovada bor. Telegram'da faqat bitta "Batafsil" tugmasi (`announce_frequency.py` → `center_button`) | 🟡 | Telegram'ga ikki tugma | — |
| 6.3 | "Qo'shimcha kreativ" → 2.3-oyna. Telegram'dan → saytdagi shu oynaga havola | E'lonni almashtirish oynasini ochadi (`FrequencyCreative.tsx`) | 🟡 | Havola manzili | 2.3-oynaga yo'naltirish |
| 6.3 | "Yaxshi ishlayapti": keyingi xabar faqat keyingi darajada, 3.00 da 24 soatga yashiriladi | Shunday (`answer_frequency.py`, `HIDDEN_FOR = 24h`) | ✅ | — | — |
| 6.4 | Matnlar TZ'dagidek (sarlavhalar, "CTR", "Lid narxi") | Boshqacha: masalan 3-daraja sarlavhasi "Kreativni almashtirish majburiy", "Havolaga bosish ulushi", "Natija narxi" (`frequency_copy.py`) | 🟡 | Matnlar TZ'ga moslanadi | Agar front o'z matnini yozsa, o'shani ham |
| 6.4 | "odatda $0.90" = 1-banddagi odatiy narx | Qo'shni guruhlar narxi (`peers`) | 🟡 | B7 tayyor bo'lgach almashtiriladi | — |
| 6.5.1 | Har bir daraja bo'yicha bitta xabar | Shunday | ✅ | — | — |
| 6.5.2 | Bir kunlik xabarlar bitta xabarda | Bitta xabarda, lekin ko'pi bilan 5 ta (`FREQUENCY_MAX_ITEMS = 5`) | 🟡 | Cheklov olib tashlanadi | — |
| 6.5.3 | 7 kunda $3 dan kam sarflagan guruh tekshirilmaydi | `frequency_min_spend = {"USD": 300}` | ✅ | — | — |
| 6.5.4 | 2.00 dan tushsa yoki yangi kreativ qo'shilsa, holat noldan | Shunday, lekin chegara 1.70 | 🟡 | 6.2 bilan birga | — |
| 6.5.5 | Guruh to'xtatilsa, ochiq xabarlar yopiladi | Tungi tekshiruvda yopiladi | ✅ | — | — |
| 6.5.6 | Chastota va lid narxi xabari bitta xabarga birlashtiriladi | 1-band yo'q | ❌ | B7 da | B7 da |
| 6.6 | Saqlanadigan maydonlar | Hammasi bor (`agent_frequency_alerts`). `channel` alohida maydon emas: `telegram_sent_at` bor, ilovada har doim ko'rinadi | ✅ | — | — |
| Q4 | Eski diagnoz va "auditoriyani kengaytirish" qoidasi ham 1.70 ni ishlatadi (`seen_too_often`) | — | 🟡 | Q4 javobiga ko'ra | — |

### 7-band. Kreativ sozlamalari va Meta funksiyalari

| § | TZ talabi | Kodda hozir | Holat | O'zgarish (backend) | Front |
|---|---|---|---|---|---|
| 7.1 | Har bir yangi va tahrirlangan e'londa barcha `creative_features_spec` → OPT_OUT | Hech qayerda yuborilmaydi | ❌ | Config va 4 ta yo'lda yuborish: launch, yangi e'lon, kreativ almashtirish, duplikat | — |
| 7.1 | Musiqa: `asset_feed_spec.audios` bo'sh | Yo'q | ❌ | T4 dan keyin | — |
| 7.1 | Yaratilgach GET bilan tekshiriladi, yoqilgani log'ga yoziladi | Yo'q | ❌ | Shu tekshiruv | — |
| 7.2 | `is_dynamic_creative = false` | Yuborilmaydi | ❌ | Guruh yaratishda yuboriladi | — |
| 7.3 | A/B test qo'shilmaydi | Yo'q | ✅ | — | — |
| 7.4 | Tavsiyalar userga ko'rsatilmaydi | "Amallar"da `advice` turi bor (`provider_notes.py` → `inbox_notes`). Kampaniya javobida `notes` bor (front uni chizmaydi) | 🟡 | Ikkalasidan olib tashlanadi | Faqat API turi tozalanadi |
| 7.4 | Faqat texnik tavsiyalar AI'ga | AI chati barcha tavsiyalarni o'qiydi (`chat/selectors/readings.py` → `advice_of`). AI qoidasi Advantage audience tavsiyasidan kengaytirish taklif qiladi (`core/agent/rules/trouble.py` → `provider_advice`) | 🟡 | Filtr: faqat texnik. `provider_advice` qoidasi olib tashlanadi | — |
| 7.4 | Manba `GET /act_{id}/recommendations` | Endpoint yo'q (0.2) | — | Manba `recommendations` maydoni bo'lib qoladi | — |

---

## 2. Front ishi kerak bo'lgan backend o'zgarishlari

| Bosqich | Backend o'zgarishi | Frontda nima qilinadi |
|---|---|---|
| 7 | Meta tavsiyalari javoblardan olib tashlanadi | `notes` va `advice` turlari API tiplaridan olib tashlanadi |
| 4 | Ishlab turgan kampaniya nomini o'zgartirish API'si | Kampaniyalar ro'yxati va kampaniya sahifasida qalam. Bo'sh nom va 100 belgi tekshiruvi |
| 4 | Yangi guruh va e'lon nomi avtomatik | `AddDialogs` dan nom maydoni olib tashlanadi |
| 5 | Hamma launch faqat Instagram, Messenger yo'q | `Goal.tsx`, `PlanParts.tsx` dan Messenger tanlovi, `EditApps.tsx` dan "automatic" va FB rejimlari olib tashlanadi. Instagram joylashuvlari ro'yxati |
| 5 | Instagram'siz sahifa (Q3) | Q3 javobiga ko'ra xabar yoki to'siq |
| 3 | Event'lar 7 kunlik soni bilan, custom conversion'lar, ogohlantirishlar | "Kengaytirilgan" (`EditAdv.tsx`): son, guruhlar, ogohlantirish matni |
| 3 | Natija nomi event bo'yicha | Dashboard va kampaniya jadvalida "Natija" ustuni |
| 2 | Kampaniya, guruh va e'lon nusxasi API'si | Uchala darajada "Duplikat". Guruh uchun kampaniya tanlovi. E'lon uchun 3 qadamli oyna. "Tayyorlanmoqda" holati |
| 2 | Yangi media yuklash va CTA tanlash | Duplikat oynasida yuklash va CTA |
| 2 | Formani almashtirish: ikki variant | `AdEdit.tsx` da variant tanlovi va ogohlantirish |
| 2 | Xabar shablonini o'zgartirish | Yangi oyna: salomlashish matni, tez savollar, javoblar |
| 6 | Yangi darajalar, daraja javobda, dashboard banneri | Daraja nomlari va ranglari, chastota ustuni rangi, dashboard tepasidagi banner |
| 6 | "Qo'shimcha kreativ" → 2.3-oyna | `FrequencyCreative.tsx` 2.3-oynani ochadi |
| 1 | Lid narxi xabari va 3 ta tugma | "Amallar"da yangi xabar turi, tugmalar, chastota bilan birlashgan xabar |
| 1 | Maqsadli narx maydoni | Onboarding va profilda maydon |

Front ishi kerak bo'lmagan backend o'zgarishlari: 7.1–7.2, 5-banddagi joylashuvlar qoidasi, 6.1 `is_ours`, 6.2 dagi 3.00 dan tushganda yopilish, 6.3 Telegram tugmalari, 6.5.2 cheklov, 1-banddagi barcha hisoblar.

---

## 3. Ish ketma-ketligi (oxirgi qarorlar bilan, 2026-11-07)

### 3.1. Qabul qilingan qarorlar
1. Hamma narsa TZ'ga mos bo'ladi.
2. **Q1:** 3× lid narxi xabari hozirgi 2× "Qimmatlashdi" xabari o'rniga keladi.
3. **Q2:** odatiy narx TZ 1.2 bo'yicha olinadi. "Soha o'rtachasi" biznes ma'lumotlari (yo'nalishlar) ishiga qoldiriladi; u keyin qilinadi. Shungacha zaxira tartibi: akkaunt tarixi → onboarding'dagi maqsadli narx → xabar yuborilmaydi.
4. **Q3:** odatiy tanlov faqat Instagram, hamma kampaniya turida (xabar kampaniyasi Instagram Direct'da). Sahifada Instagram bo'lmasa, userga ogohlantirish chiqadi: "Instagram ulanmagan. Instagram'da yoqmoqchi bo'lsangiz, Instagram'ni ulang yoki supportga yozing", ikkala yo'lga tugma bilan.
5. **Q4:** TZ §6 eski 1.70 / 2.00 / 2.50 qoidaning o'rniga keladi: yangi darajalar 2.00 / 2.50 / 3.00. §1.4 dagi "Charchoq" nisbat bilan o'lchanadi (≥ 2.0).
6. **Q5:** Meta tavsiyalari userga ko'rsatilmaydi. AI'ga faqat texnik tavsiyalar beriladi. Byudjet, placement va Advantage+ tavsiyalari olib tashlanadi.

### 3.2. Shu qarorlardan kelib chiqadigan qoidalar
- Instagram'siz sahifa: reklama Facebook'da yoqiladi, Instagram uchun ogohlantirish chiqadi (Q3).
- 1.70 chegarasi hamma joydan olib tashlanadi. Eski AI diagnozi va "auditoriyani kengaytirish" qoidasi ham 2.00 ni oladi (Q4, TZ §6).
- Maqsadli narx onboarding'da bitta raqam, TZ 1.2 dagidek.

### 3.3. Bosqichlar

Har bosqichda tartib bir xil: backend → testlar → staging'da bitta PAUSED reklama bilan Meta'da sinash → front uchun qisqa hujjat → front → birga tekshirish.

**0-bosqich. Tekshiruvlar** (kod yo'q)
- Staging'da T1–T7 test chaqiruvlari. Natijalar shu faylga yoziladi.

**1-bosqich. Kreativ sozlamalari va Meta tavsiyalari (TZ 7)**
- Backend:
  - 23 ta `creative_features_spec` kaliti bitta config'da. Ular launch, yangi e'lon va kreativ almashtirishda OPT_OUT qilib yuboriladi.
  - Musiqani o'chirish (T4 dan keyin).
  - Guruh yaratishda `is_dynamic_creative=false`.
  - Creative yaratilgach GET bilan tekshirish va log.
  - Meta tavsiyalari "Amallar" va kampaniya `notes`'idan olib tashlanadi.
  - AI chatiga faqat texnik tavsiyalar boradi.
  - `provider_advice` qoidasi olib tashlanadi.
- Front: API tiplaridan `notes` va `advice` olib tashlanadi.

**2-bosqich. Nomni tahrirlash (TZ 4)**
- Backend:
  - Meta adapteriga nom yozish va yangi action turi.
  - Ishlab turgan kampaniya nomini o'zgartirish API'si (bo'sh emas, ≤100 belgi).
  - Yangi guruh va e'lon nomi avtomatik beriladi.
- Front:
  - Kampaniyalar ro'yxati va kampaniya sahifasida qalam, nom shu joyda tahrirlanadi.
  - `AddDialogs` dan nom maydoni olib tashlanadi.

**3-bosqich. Faqat Instagram (TZ 5)**
- Backend:
  - Barcha Instagram joylashuvlari (T5).
  - Hamma tur faqat Instagram; suhbat faqat Instagram Direct.
  - "automatic" rejimi olib tashlanadi.
  - Instagram'siz sahifa uchun ogohlantirish ma'lumoti.
- Front:
  - Messenger tanlovi (`Goal.tsx`, `PlanParts.tsx`) olib tashlanadi.
  - `EditApps.tsx` dagi rejimlar.
  - Ogohlantirish va ikki tugma: "Instagram'ni ulash", "Supportga yozish".

**4-bosqich. Pixel event'i (TZ 3)**
- Backend:
  - Pixel avtomatik tanlanadi (7 kunda eng ko'p event yuborgani).
  - Event'lar 7 kunlik son bilan.
  - Custom conversion'lar: sinxronlash va `custom_conversion_id`.
  - Event bo'yicha maqsad: LEADS yoki SALES (T7).
  - 0 va <10 ogohlantirishlari.
  - Har bir event uchun natija nomi.
- Front:
  - "Kengaytirilgan" bo'limida son, guruhlar va ogohlantirishlar.
  - "Natija" ustunida event nomi.

**5-bosqich. Duplikat, forma va shablon (TZ 2)**
- Backend:
  - Meta adapteriga `/copies` (asinxron batch bilan).
  - Kampaniya nusxasi.
  - Guruh nusxasi e'lonlari bilan, boshqa kampaniyaga ham (T3).
  - E'lon nusxasi: shu, boshqa yoki yangi guruhga; o'sha yoki yangi kreativ (media yuklash, CTA); ishlab turgan guruhda ACTIVE.
  - Formani shu e'londa almashtirish (T1).
  - Xabar shabloni: salomlashish, tez savollar va javoblar (T6).
  - Kreativ qo'shilganda chastota holati noldan.
- Front:
  - Uch darajada "Duplikat" tugmasi.
  - E'lon nusxasi uchun 3 qadamli oyna.
  - Guruh nusxasi uchun kampaniya tanlovi.
  - Forma uchun ikki variant va ogohlantirish.
  - Shablon oynasi.
  - "Tayyorlanmoqda" holati.

**6-bosqich. Chastota (TZ 6)**
- Backend:
  - Darajalar 2.00 / 2.50 / 3.00.
  - Barcha ACTIVE guruhlar, `is_ours` sharti olib tashlanadi.
  - 3.00 dan tushganda xabar yopiladi.
  - Dashboard banneri uchun ma'lumot.
  - Daraja javobda yuboriladi (ustun rangi uchun).
  - Telegram'ga ikki tugma; "kreativ qo'shish" 2.3-oynaga havola.
  - Matnlar TZ'dagidek.
  - Bir xabarda 5 ta cheklovi olib tashlanadi.
- Front:
  - Darajalar va ranglar, chastota ustuni rangi, dashboard tepasidagi banner.
  - `FrequencyCreative.tsx` 2.3-oynani ochadi.

**7-bosqich. Lid narxi ogohlantirishi (TZ 1)**
- Backend:
  - 90 kunlik odatiy narx: bir xil natija turi va event, ≥1000 ko'rsatish, ≥5 natija, mediana.
  - Onboarding'dagi maqsadli narx (yangi maydon, migratsiya).
  - Tungi tekshiruv: 3 kun, ≥3×. Istisnolar: 48 soat, 72 soat ichida o'zgartirilgan, yetkazishda muammo.
  - Sabablar nisbat bilan, ko'pi bilan 2 ta.
  - Xabar va 3 ta tugma (ilova va Telegram).
  - 72 soatlik takrorlamaslik.
  - Yangi jadval (TZ 1.7).
  - 2× "Qimmatlashdi" olib tashlanadi.
  - Chastota xabaridagi odatiy narx shu yerdagi baseline'ga o'tkaziladi.
  - Bir kunlik chastota va lid narxi xabarlari birlashtiriladi.
- Front:
  - "Amallar"da yangi xabar turi va 3 ta tugma; birlashgan xabar.
  - Onboarding va profilda maqsadli narx maydoni.

**Keyinroq (alohida ish). Biznes ma'lumotlari**
- Yo'nalish qidiruvi, sinonimlar, yetishmayotgan yo'nalishlar.
- 84 ta erkin matnni bog'lash.
- Soha o'rtachasi — 7-bosqichdagi zaxira tartibiga qo'shiladi.
