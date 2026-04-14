/*
 * GSTK V1 light - outils admin optionnels et legers.
 */

function ensureFormLinksKeysV1_() {
  const spreadsheet = getDashboardSpreadsheet_();
  const sheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.FORM_LINKS);
  const totalColumns = Math.max(7, sheet.getLastColumn());
  const header = sheet.getRange(1, 1, 1, totalColumns).getDisplayValues()[0];
  const headerIndex = indexByHeader_(header);

  if (typeof headerIndex.FormKey === "undefined") {
    throw new Error("FORM_LINKS header must contain 'FormKey'.");
  }

  const existingRows = sheet.getLastRow() > 1
    ? sheet.getRange(2, 1, sheet.getLastRow() - 1, totalColumns).getDisplayValues()
    : [];

  const existingKeys = {};
  for (let i = 0; i < existingRows.length; i += 1) {
    const key = String(existingRows[i][headerIndex.FormKey] || "").trim();
    if (key) existingKeys[key] = true;
  }

  const missing = [];
  for (let j = 0; j < GSTK_FORM_LINK_DEFAULTS.length; j += 1) {
    const item = GSTK_FORM_LINK_DEFAULTS[j];
    if (!existingKeys[item[0]]) {
      missing.push(item);
    }
  }

  if (missing.length === 0) {
    logInfo_("ensureFormLinksKeysV1_: nothing to add.");
    return {
      added: 0,
      message: "All keys already present.",
    };
  }

  const rowsToWrite = [];
  for (let k = 0; k < missing.length; k += 1) {
    const row = new Array(totalColumns).fill("");
    writeIfHeaderExists_(row, headerIndex, "FormKey", missing[k][0]);
    writeIfHeaderExists_(row, headerIndex, "Module", missing[k][1]);
    writeIfHeaderExists_(row, headerIndex, "SiteKey", missing[k][2]);
    writeIfHeaderExists_(row, headerIndex, "FormType", missing[k][3]);
    writeIfHeaderExists_(row, headerIndex, "FormUrl", missing[k][4]);
    writeIfHeaderExists_(row, headerIndex, "Enabled", missing[k][5]);
    writeIfHeaderExists_(row, headerIndex, "Notes", missing[k][6]);
    rowsToWrite.push(row);
  }

  safeWriteBlock_(sheet, sheet.getLastRow() + 1, 1, rowsToWrite);
  logInfo_("ensureFormLinksKeysV1_: added " + rowsToWrite.length + " row(s).");

  return {
    added: rowsToWrite.length,
    message: "Missing V1/V2 keys appended.",
  };
}

function openConfigSourcesSheet_() {
  const spreadsheet = getDashboardSpreadsheet_();
  const sheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.CONFIG_SOURCES);
  spreadsheet.setActiveSheet(sheet);
}

function writeIfHeaderExists_(row, headerIndex, headerName, value) {
  if (typeof headerIndex[headerName] !== "undefined") {
    row[headerIndex[headerName]] = value;
  }
}
