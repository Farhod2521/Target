# Reklama metrikalari: ish rejasi

2026-11-05. Manba: `bazaviy-metrikalar-v3.md` (24 ta bazaviy metrika).

## Maqsad

Mutaxassis Reklama bo'limi va Dashboard'da to'liq va to'g'ri raqamlarni ko'radi. Raqamlar Ads Manager bilan bir xil chiqadi.

## Qoidalar

1. **Hamma formula backendda, bitta katalogda** (`core/metrics`). Bir metrikaning formulasi boshqa joyda qayta yozilmaydi. Formula kerak bo'lgan har bir joy (Reklama, Dashboard, panel, chat, Telegram bot, AI, office) katalogdan oladi.
2. **Frontda formula yo'q.** Front faqat tayyor qiymatni ko'rsatadi, Jami qatori ham backenddan keladi.
3. **Tarmoqlar.** Hamma metrika bir xil tuzilishda yoziladi: nomi, birligi, formulasi, qaysi darajada va qaysi tarmoqda bor. Umumiy metrikalar (Sarflandi, Ko'rsatildi, Klik, CTR, CPC, CPM, Natija, Lid, Sifatli lid, Sotuv) hamma tarmoq uchun bitta formula bilan hisoblanadi. Tarmoqning o'z metrikalari (Meta: Qamrov, Chastota, Reytinglar, Hook, Hold; Google: Impression share va boshqalar) katalogning o'z qismida turadi va bir-biriga aralashmaydi.
4. **Expert mode.** "Targetolog" rejimining nomi "Expert mode" bo'ladi. Tugmasi tepaga (biznes tanlagichning chap tomoniga) chiqadi. Tanlov foydalanuvchi sozlamasida saqlanadi. Expert mode Reklama bo'limini ham, Dashboard'ni ham o'zgartiradi.
5. **Oddiy mode** ikkala joyda hozirgidek qoladi. Uni to'liq redesign qilish keyingi alohida reja.
6. **Frontda har bir sahifa o'zgarishidan oldin namuna dizayn so'raladi.** Namuna bo'lsa, unga qarab qilinadi. Bo'lmasa, UI/UX talablariga mos redesign qilinadi.
7. Har bosqich to'liq tugatiladi va tekshiriladi. Avval backend, keyin front.

## Qarorlar

| Savol | Qaror |
|---|---|
| Sotuvlar | Ikki manba, alohida ustunlarda: **Sotuv (sayt)** — pixel `Purchase`, Meta'dan; **Sotuv (CRM)** — "Sotildi" bosqichi. Bitta mijoz ikkalasida ham bo'lishi mumkin, shuning uchun qo'shilmaydi. CRM eventlari Meta'ga `TargetologAI...` nomi bilan ketadi, `Purchase` bilan aralashmaydi |
| Reyting davr uchun | Davrning oxirgi kunidagi qiymat (Ads Manager kabi) |
| "Bittasi" | Ads Manager kabi: ko'rish va qamrov maqsadida 1000 ko'rsatish narxi, qolgan hamma maqsadda (eslab qolish ham) Sarflandi ÷ Natija |
| Qo'shimcha | Sotuv summasi va ROAS (pixel `Purchase` qiymatidan) |

## Darajalar bo'yicha ustunlar (Expert mode)

| Daraja | Ustunlar |
|---|---|
| Kampaniya va Guruh | Holati, Sarflandi, Natija, Bittasi, Qamrov, Ko'rsatildi, Chastota, CPM, Link kliklar, Noyob kliklar, CTR, CPC, Lidlar, Forma konversiyasi, Sifatli lid, Sifatli lid %, Sifatli lid narxi, Sotuv (sayt), Sotuv (CRM), Sotuv narxi, Sotuv summasi, ROAS |
| Reklama | Yuqoridagilarning hammasi, CPC'dan keyin: Hook rate, Hold rate, Sifat, Faollik, Konversiya |

## "–" qoidalari

Qiymat o'rniga `–` va uning sababi chiqadi:
- xabar kampaniyasi: link ustunlari va forma konversiyasi;
- rasmli reklama: Hook va Hold;
- 500 ko'rsatishdan kam: reytinglar (Meta `UNKNOWN` qaytaradi);
- bo'luvchi 0: narxlar va foizlar;
- Meta hali o'qimagan.

**Jami qatori:** foiz va narxlar yig'indilardan qayta hisoblanadi, o'rtachadan emas. Qamrov, Noyob kliklar va Chastota butun davr uchun Meta'dan o'qiladi, chunki kunlarni qo'shib bo'lmaydi.

## Ish ketma-ketligi

| # | Bosqich | Nima qilinadi |
|---|---|---|
| 1 ✅ | Formulalar katalogi | `core/metrics` ichida bitta katalog: umumiy, Meta, Google qismlari. Formulalar hujjatdagi misollar bilan test qilinadi |
| 2 ✅ | Eski formulalarni ko'chirish | Hozirgi 15 ga yaqin joy katalogdan oladi: panel, dashboard, chat, bot, AI, backoffice. Natija o'zgarmasligi testlar bilan tekshiriladi |
| 3 ✅ | Ma'lumotni to'ldirish (Meta) | Noyob kliklar davr bo'yicha o'qiladi; pixel `Purchase` soni va summasi olinadi. Migratsiya, 90 kunni qayta o'qish |
| 4 ✅ | Ma'lumotni to'ldirish (CRM) | Sifatli lid va CRM sotuvlari guruh va reklama darajasida |
| 5 ✅ | Reklama bo'limi API'si (Expert) | 3 daraja tayyor qiymatlar bilan; Jami qatori, ustunlar katalogi, ustun tanlovini saqlash, "–" sababi, yangilanish vaqti, attribution oynasi |
| 6 ✅ | Dashboard API'si (Expert) | Katalogdan. Nima chiqishi avval kelishib olinadi |
| 7 ✅ | Expert mode (backend) | Foydalanuvchi sozlamasida saqlash va API |
| 8 ✅ | Ads Manager bilan solishtirish | Kechki avtomatik tekshiruv: bizning yig'indi va Meta'ning davr bo'yicha jami raqami. Staging'da o'lchanadi |
| 9 ✅ | Front: Expert mode tugmasi | Tepaga chiqadi. Namuna so'raladi |
| 10 | Front: Reklama redesign (Expert) | Jadval katalogdan quriladi; ustun to'plamlari (Umumiy, Video, Lid sifati, Sotuv), izohlar va normalar, reyting ranglari, Jami qatori. Namuna so'raladi |
| 11 | Front: Dashboard redesign (Expert) | Namuna so'raladi |
| 12 | Oddiy mode'dan formulalarni olib tashlash | Ko'rinish o'zgarmaydi; `Manager.tsx`, `dashboard.ts` dagi hisoblar backendga o'tadi |
| 13 | Google | Google metrikalari katalogning o'z qismiga |
| 14 | Ishga tushirish | Deploy, production'da Ads Manager bilan solishtirish |

Keyingi alohida reja: Oddiy mode'ni to'liq redesign qilish.

## Hozirgi holat (2026-11-05 tekshiruvi)

- Raqamlar Meta Insights'dan har 30 daqiqada o'qiladi (`packages/metaads/src/metaads/insights.py`, `INSIGHT_FIELDS`) va `metrics_daily` jadvaliga yoziladi.
- Formulalar ko'p joyda takrorlanadi: `core/metrics/contracts.py` (`Totals`), `core/metrics/panel.py` (`PanelTotals`), `core/metrics/engagement.py`, `app/modules/metrics/selectors/panel.py`, `app/modules/ads/contract/figures_v2.py`, `app/modules/ads/selectors/google.py`, chat, backoffice, agent; frontda `Manager.tsx` va `dashboard.ts`.
- Front metrikalar katalogidagi ba'zi kartalarni tushirib yuboradi (`packages/api/src/live/bridges/metrics.ts`).
- `Manager.tsx:307` da pul `/ 100` ga bo'linadi. So'm ISO 4217 bo'yicha 2 xonali, shuning uchun bugun xato yo'q, lekin bu hisob 12-bosqichda backendga ko'chadi.

## Bosqichlar holati

- **1-bosqich (2026-11-05):** `core/metrics/catalogue/` (umumiy — `common.py`, Meta — `meta.py`, tuzilma — `spec.py`), bo'lish amallari `core/metrics/arithmetic.py`. Testlar: `tests/core/metrics/test_catalogue.py`. Eski hisoblar hali ko'chirilmagan (2-bosqich). "Natija" sotuv maqsadli (pixel `Purchase`) kampaniyalarda hozircha `uncounted` — 3-bosqichda pixel sotuvlari bilan to'ldiriladi.
- **2-bosqich (2026-11-05):** har metrikaning formulasi `core/metrics/formulas.py` da, bo'lish va yaxlitlash `core/metrics/arithmetic.py` da. Ularga ulandi: `core/metrics` (Totals, PanelTotals, engagement, derive, segment_compare), kabinet selectorlari, chat hisobotlari, office, Google va ChatGPT qatorlari, AI agent. Natija maydoni va 1000 ga narx (`field`, `per`) `formulas.RESULT_OF` dan olinadi. `tests/core/metrics/test_one_place.py` boshqa joyda yozilgan formulani topsa yiqiladi (eski kodda 52 ta topgan). Qoida chegaralari (byudjet ulushi va h.k.), billing va sotuv menejerlari foizlari metrika emas, o'z joyida qoldi.
  - Testlar: 4898 ta, bazali testlar bilan birga, hammasi o'tdi.
  - Farqlar: foizlar endi yarimni yuqoriga yaxlitlaydi (2.5 → 3, avval 2). Sarf 0 bo'lgan qatorda CPM, CPC va natija narxi 0 emas, `–` chiqadi. Office va ChatGPT'dagi CPM va CPC endi pastga kesilmaydi, yaxlitlanadi.
- **3-bosqich (2026-11-05):** migratsiya `0023` (`0022_support_guests` dan keyin).
  - `metrics_daily` ga `purchases_site` va `purchase_value_site_minor` qo'shildi. Ular Meta'ning `offsite_conversion.fb_pixel_purchase` eventi, Ads Manager'dagi "Website purchases" (pixel va CAPI), shu kunlik so'rovdan olinadi. `purchase` va `omni_purchase` olinmaydi, chunki ularga ilova va oflayn sotuvlar qo'shiladi.
  - `metrics_people_count` ga `unique_link_clicks` qo'shildi: qamrov bilan bir so'rovda, butun davr uchun.
  - Qo'shimcha Meta so'rovi yo'q.
  - **Deploydan keyin:** migratsiya; keyin `python -m app.modules.metrics.refill` (hisobot) va `--apply` (har Meta hisobini 90 soniya oraliq bilan navbatga qo'yadi, 90 kunni qayta o'qiydi). Noyob kliklar keyingi sinxronlashda o'zi to'ladi.
  - Tekshirilmagan: haqiqiy Meta hisobida sotuv nomi (`fetch_action_totals` bilan tekshirish mumkin).
- **4-bosqich (2026-11-05):** sifatli lid va CRM sotuvi faqat CRM bo'yicha, ta'rif bitta joyda: `app/modules/crm/quality.py` (CAPI bilan bir xil). Lid kelgan kun bo'yicha sanaladi. CRM yoqilmagan bo'lsa, `no_crm`. Qo'lda baho sanalmaydi.
  - Keyinga qoldirildi: lidlar sahifasidagi qo'lda baho tugmalari va ularning CAPI signali.
- **5-bosqich (2026-11-05):** `GET /api/v2/campaigns/expert`, `GET/PUT /api/v2/campaigns/expert/columns`, hujjat `docs/API_EXPERT.md`. Migratsiya `0024` (`metric_preferences.expert_chosen`). Qatorlar `/manager` dan, eski raqamlarsiz; kataklar katalogdan; Jami katalogning `add_up` idan.
  - Hali yo'q: Jami qatorida qamrov, noyob kliklar va chastota (bir qatordan ortiq bo'lsa `not_asked`). Ular uchun hisob darajasida davr bo'yicha qamrovni o'qish kerak, 8-bosqich bilan birga qilinadi.
- **6-bosqich (2026-11-05):** `GET /api/v1/metrics/expert`, hujjat `docs/API_EXPERT.md`. Tarkib siz bilan kelishilgan: asosiy ko'rsatkichlar, kunlik grafik, voronka, maqsad bo'yicha, eng yaxshi va eng yomon kampaniyalar, diqqat talab reklamalar, kesimlar, lid sifati. Mantiq `core/metrics/catalogue/board.py` da, normalar `catalogue/meta.py` da. Kesimlar hozirgi Dashboard bilan bitta funksiyadan (`page_segments`).
  - Hold ostonasi: 10% (foydalanuvchi qarori, 2026-11-05). AI agent ham katalogdagi `HOLD_WEAK_PCT`, `HOOK_WEAK_PCT` ni oladi, son bitta joyda.
- **7-bosqich (2026-11-05):** `users.expert_mode` (migratsiya `0025`), `GET /api/v1/account` da `expert_mode`, `PUT /api/v1/account/expert-mode`.
- **8-bosqich (2026-11-05):**
  - **Jami qatoridagi Qamrov, Noyob kliklar, Chastota:** odamlar soni endi hisob darajasida ham o'qiladi (`metrics_people_count`, `level = 'account'`, xuddi shu davrlar). Jami shu sonni oladi, lekin faqat bitta hisob bo'lsa va davrda ko'rsatilgan hamma ob'ekt qatorlarda bo'lsa (`whole_account_people`). Aks holda `not_asked`. Reklama jadvali va Expert Dashboard ikkalasi ham shundan oladi. Meta'ga har odamlar o'qishida (taxminan 25 daqiqada bir) 2 ta qo'shimcha so'rov: asosiy davrlar va qo'shimcha davrlar.
  - **Har kechki solishtirish:** kechki o'qishdan keyin Meta'ning butun hisob bo'yicha jamisi yopilgan oxirgi 7 kun uchun qayta o'qiladi va bizdagi guruh qatorlari yig'indisi bilan solishtiriladi (`app/modules/metrics/services/check.py`). Solishtiriladi: Sarf, Ko'rsatildi, Klik, Link klik, Sotuv (sayt). Lidlar solishtirilmaydi: hisob darajasida hamma turdagi lid sanaladi, guruhda faqat o'z maqsadi. Farq 1% dan va 1 birlikdan oshsa, kun "farq qiladi" deb belgilanadi va logga yoziladi. Natija `metrics_checks` jadvalida (migratsiya `0026`). Meta'ga kechasiga 1 ta qo'shimcha so'rov. Solishtirish ishlamasa ham kechki o'qish to'xtamaydi.
  - **Hisobot:** `python -m app.modules.metrics.check` (oxirgi 7 kun) yoki `--days 30`.
  - **Tekshirilmagan:** haqiqiy Meta hisobida. Staging'da o'lchash uchun deploy kerak (14-bosqich bilan yoki oldinroq staging'ga).
- **9-bosqich (2026-11-05):** front, `feat/ads-metrics` branchi, commit d585a1f. Headerda biznes tanlagichning chap tomonida Expert tugmasi turadi: belgi, "Expert" yozuvi va tumbler, telefonda belgi va tumbler. Tanlov akkauntda saqlanadi (`PUT /account/expert-mode`). Reklama bo'limidagi "Oddiy / Targetolog" tanlovi va `?rejim=targetolog` olib tashlandi. Expert yoqilganda Reklama hozircha eski uch darajali jadvalni ko'rsatadi, yangisi 10-bosqichda. Dashboard 11-bosqichgacha o'zgarmaydi.
