/*
 * GSTK V1 light - menu minimal.
 */

function onOpen() {
  buildGSTKMenu_();
}

function buildGSTKMenu_() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu("GSTK V1")
    .addItem("Refresh consolidations", "refreshDashboardConsolidations")
    .addItem("Run system health check", "runSystemHealthCheckFromDashboard")
    .addSeparator()
    .addItem("Open FORM_LINKS", "openFormLinksSheet_")
    .addItem("Open SYSTEM_HEALTH_AUDIT", "openSystemHealthAuditSheet_")
    .addSeparator()
    .addItem("Ensure FORM_LINKS keys (V1)", "ensureFormLinksKeysV1_")
    .addToUi();
}

function openFormLinksSheet_() {
  const spreadsheet = getDashboardSpreadsheet_();
  const sheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.FORM_LINKS);
  spreadsheet.setActiveSheet(sheet);
}

function openSystemHealthAuditSheet_() {
  const spreadsheet = getDashboardSpreadsheet_();
  const sheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.SYSTEM_HEALTH_AUDIT);
  spreadsheet.setActiveSheet(sheet);
}
