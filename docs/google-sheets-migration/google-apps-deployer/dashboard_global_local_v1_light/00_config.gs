/*
 * GSTK V1 light - configuration et helpers partages.
 * Cible: dashboard central uniquement, sans UI HTML ni logique lourde.
 */

const GSTK_V1_LIGHT_VERSION = "2026.04.14.1";
const GSTK_DASHBOARD_ID = "1tVyxYrlDwI2Nj5u2ToRFixZzenzda8NHAPpYbuBnJg4";

const GSTK_SHEET = {
  CONFIG_SOURCES: "CONFIG_SOURCES",
  CONFIG_ACCESS: "CONFIG_ACCESS",
  FORM_LINKS: "FORM_LINKS",
  SYSTEM_HEALTH_AUDIT: "SYSTEM_HEALTH_AUDIT",
  STOCK_CONSOLIDE: "STOCK_CONSOLIDE",
  ALERTS_CONSOLIDE: "ALERTS_CONSOLIDE",
  LOTS_CONSOLIDE: "LOTS_CONSOLIDE",
  PURCHASE_CONSOLIDE: "PURCHASE_CONSOLIDE",
  DASHBOARD_USER: "DASHBOARD_USER",
  DASHBOARD_CONTROLEUR: "DASHBOARD_CONTROLEUR",
};

const GSTK_REQUIRED_FORM_KEYS = [
  "FORM_FIRE_MOVEMENT_JLL",
  "FORM_FIRE_REPLENISH_JLL",
  "FORM_PHARMA_MOVEMENT_JLL",
  "FORM_PHARMA_INVENTORY_JLL",
  "FORM_PHARMA_LOT_IN_JLL",
  "FORM_PURCHASE_REQUEST_INC_JLL",
  "FORM_PURCHASE_REQUEST_PHA_JLL",
  "FORM_FIRE_ITEM_CREATE_JLL",
];

const GSTK_FORM_LINK_DEFAULTS = [
  ["FORM_FIRE_MOVEMENT_JLL", "INCENDIE", "JLL", "MOVEMENT", "", "TRUE", "Formulaire actif V1 - mouvements stock incendie"],
  ["FORM_FIRE_REPLENISH_JLL", "INCENDIE", "JLL", "REPLENISH", "", "TRUE", "Formulaire actif V1 - demandes de reappro incendie"],
  ["FORM_PHARMA_MOVEMENT_JLL", "PHARMACIE", "JLL", "MOVEMENT", "", "TRUE", "Formulaire actif V1 - mouvements stock pharmacie"],
  ["FORM_PHARMA_INVENTORY_JLL", "PHARMACIE", "JLL", "INVENTORY", "", "TRUE", "Formulaire actif V1 - inventaire pharmacie"],
  ["FORM_PHARMA_LOT_IN_JLL", "PHARMACIE", "JLL", "LOT_IN", "", "FALSE", "Prevu V2 - reception de lots pharmacie"],
  ["FORM_PURCHASE_REQUEST_INC_JLL", "INCENDIE", "JLL", "PURCHASE", "", "FALSE", "Prevu V2 - demande achat incendie"],
  ["FORM_PURCHASE_REQUEST_PHA_JLL", "PHARMACIE", "JLL", "PURCHASE", "", "FALSE", "Prevu V2 - demande achat pharmacie"],
  ["FORM_FIRE_ITEM_CREATE_JLL", "INCENDIE", "JLL", "ITEM_CREATE", "", "FALSE", "Prevu V2 - creation article incendie controlee"],
];

function getDashboardSpreadsheet_() {
  if (GSTK_DASHBOARD_ID) {
    try {
      return SpreadsheetApp.openById(GSTK_DASHBOARD_ID);
    } catch (error) {
      logWarn_("OpenById fallback to active spreadsheet: " + String(error && error.message ? error.message : error));
    }
  }
  const active = SpreadsheetApp.getActiveSpreadsheet();
  if (!active) {
    throw new Error("No active spreadsheet available.");
  }
  return active;
}

function getRequiredSheet_(spreadsheet, sheetName) {
  const sheet = spreadsheet.getSheetByName(sheetName);
  if (!sheet) {
    throw new Error("Missing sheet: " + sheetName);
  }
  return sheet;
}

function validateSpreadsheetUrl_(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  const re = /^https:\/\/docs\.google\.com\/spreadsheets\/d\/[A-Za-z0-9_-]+(?:\/.*)?$/;
  return re.test(text);
}

function normalizeBoolean_(value) {
  if (value === true) return true;
  const text = String(value || "").trim().toUpperCase();
  return text === "TRUE" || text === "VRAI" || text === "1" || text === "YES";
}

function safeWriteBlock_(sheet, startRow, startColumn, values) {
  if (!sheet) return false;
  if (!Array.isArray(values) || values.length === 0) return false;
  if (!Number.isInteger(startRow) || !Number.isInteger(startColumn) || startRow < 1 || startColumn < 1) return false;

  const width = Array.isArray(values[0]) ? values[0].length : 0;
  if (width < 1) return false;

  for (let i = 0; i < values.length; i += 1) {
    if (!Array.isArray(values[i]) || values[i].length !== width) {
      logWarn_("safeWriteBlock_ rejected non rectangular payload.");
      return false;
    }
  }

  const targetLastRow = startRow + values.length - 1;
  const targetLastColumn = startColumn + width - 1;
  const maxRows = sheet.getMaxRows();
  const maxColumns = sheet.getMaxColumns();

  if (targetLastRow > maxRows) {
    sheet.insertRowsAfter(maxRows, targetLastRow - maxRows);
  }
  if (targetLastColumn > maxColumns) {
    sheet.insertColumnsAfter(maxColumns, targetLastColumn - maxColumns);
  }

  sheet.getRange(startRow, startColumn, values.length, width).setValues(values);
  return true;
}

function safeSetFormula_(sheet, row, column, formula) {
  if (!sheet) return false;
  if (!Number.isInteger(row) || !Number.isInteger(column) || row < 1 || column < 1) return false;
  const text = String(formula || "").trim();
  if (!text) return false;

  const maxRows = sheet.getMaxRows();
  const maxColumns = sheet.getMaxColumns();
  if (row > maxRows) {
    sheet.insertRowsAfter(maxRows, row - maxRows);
  }
  if (column > maxColumns) {
    sheet.insertColumnsAfter(maxColumns, column - maxColumns);
  }

  sheet.getRange(row, column).setFormula(text);
  return true;
}

function indexByHeader_(headerRow) {
  const map = {};
  for (let i = 0; i < headerRow.length; i += 1) {
    const key = String(headerRow[i] || "").trim();
    if (key) {
      map[key] = i;
    }
  }
  return map;
}

function nowIso_(spreadsheet) {
  const ss = spreadsheet || SpreadsheetApp.getActiveSpreadsheet();
  const timezone = (ss && ss.getSpreadsheetTimeZone()) || "Europe/Paris";
  return Utilities.formatDate(new Date(), timezone, "yyyy-MM-dd HH:mm:ss");
}

function logInfo_(message) {
  Logger.log("[GSTK V1] " + String(message || ""));
}

function logWarn_(message) {
  Logger.log("[GSTK V1][WARN] " + String(message || ""));
}
