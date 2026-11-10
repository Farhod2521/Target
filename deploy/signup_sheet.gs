// Sotuv jadvali: 5 daqiqada to'lov qilmagan ro'yxatdan o'tganlar.
//
// O'rnatish (bir marta):
// 1. Jadvalni oching -> Kengaytmalar (Extensions) -> Apps Script.
// 2. Bor kodni o'chirib, shu faylni joylang. TOKEN ni o'zingiz o'ylagan
//    uzun so'zga almashtiring. Saqlang.
// 3. Deploy -> New deployment -> turi: Web app.
//    Execute as: Me.  Who has access: Anyone.  Deploy -> ruxsat bering.
// 4. Chiqqan Web app URL oxiriga ?token=<TOKEN> qo'shib, serverdagi .env ga:
//    SIGNUP_SHEET_URL=https://script.google.com/macros/s/.../exec?token=...
//
// Server har daqiqada {"headings": [...], "rows": [[...], ...]} yuboradi.
// Javob "ok" bo'lmasa, keyingi daqiqada qayta yuboradi.

const TOKEN = 'BU-YERGA-UZUN-MAXFIY-SOZ';

function doPost(e) {
  if (!e || !e.parameter || e.parameter.token !== TOKEN) {
    return ContentService.createTextOutput('denied');
  }
  const body = JSON.parse(e.postData.contents);
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(body.headings);
      sheet.setFrozenRows(1);
    }
    const rows = body.rows || [];
    if (rows.length) {
      const start = sheet.getLastRow() + 1;
      const range = sheet.getRange(start, 1, rows.length, rows[0].length);
      range.setNumberFormat('@');
      range.setValues(rows);
    }
  } finally {
    lock.releaseLock();
  }
  return ContentService.createTextOutput('ok');
}
