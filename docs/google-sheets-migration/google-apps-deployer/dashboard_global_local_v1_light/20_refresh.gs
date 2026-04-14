/*
 * GSTK V1 light - refresh des consolidations.
 */

function refreshDashboardConsolidations() {
  const spreadsheet = getDashboardSpreadsheet_();
  const configSheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.CONFIG_SOURCES);
  const summary = {
    timestamp: nowIso_(spreadsheet),
    enabledSources: 0,
    validSourceUrls: 0,
    invalidSourceKeys: [],
  };

  const lastRow = configSheet.getLastRow();
  if (lastRow > 1) {
    const values = configSheet.getRange(2, 1, lastRow - 1, Math.max(8, configSheet.getLastColumn())).getValues();
    for (let i = 0; i < values.length; i += 1) {
      const row = values[i];
      const sourceKey = String(row[0] || ("ROW_" + (i + 2))).trim();
      const sourceUrl = String(row[3] || "").trim();
      const enabled = normalizeBoolean_(row[4]);
      if (!enabled) continue;

      summary.enabledSources += 1;
      if (validateSpreadsheetUrl_(sourceUrl)) {
        summary.validSourceUrls += 1;
      } else {
        summary.invalidSourceKeys.push(sourceKey);
      }
    }
  }

  ensureControllerKpiFormulas_(spreadsheet);
  SpreadsheetApp.flush();

  logInfo_(
    "refreshDashboardConsolidations completed | enabledSources="
      + summary.enabledSources
      + " | validSourceUrls="
      + summary.validSourceUrls
      + " | invalid="
      + summary.invalidSourceKeys.join(",")
  );

  return summary;
}

function ensureControllerKpiFormulas_(spreadsheet) {
  const sheet = spreadsheet.getSheetByName(GSTK_SHEET.DASHBOARD_CONTROLEUR);
  if (!sheet) {
    logWarn_("DASHBOARD_CONTROLEUR not found, KPI refresh skipped.");
    return;
  }

  // B2 robuste: compte booleens et textes "TRUE".
  safeSetFormula_(
    sheet,
    2,
    2,
    '=SUMPRODUCT(--(((CONFIG_SOURCES!E2:E=TRUE)+(UPPER(CONFIG_SOURCES!E2:E)="TRUE"))>0))'
  );

  if (!String(sheet.getRange(3, 2).getFormula() || "").trim()) {
    safeSetFormula_(sheet, 3, 2, '=COUNTIF(SYSTEM_HEALTH_AUDIT!B:B;"KO")');
  }
  if (!String(sheet.getRange(4, 2).getFormula() || "").trim()) {
    safeSetFormula_(sheet, 4, 2, '=COUNTIF(STOCK_CONSOLIDE!I:I;"SOUS_SEUIL")');
  }
}
