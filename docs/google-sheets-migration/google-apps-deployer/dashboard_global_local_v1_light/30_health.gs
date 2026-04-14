/*
 * GSTK V1 light - health check dashboard.
 */

function runSystemHealthCheckFromDashboard() {
  const spreadsheet = getDashboardSpreadsheet_();
  const healthSheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.SYSTEM_HEALTH_AUDIT);
  const checks = [];

  checks.push(checkConfigSources_(spreadsheet));
  checks.push(checkConsolidationSheetFormula_(spreadsheet, GSTK_SHEET.STOCK_CONSOLIDE, "Stock consolidation formula in A1"));
  checks.push(checkConsolidationSheetFormula_(spreadsheet, GSTK_SHEET.ALERTS_CONSOLIDE, "Alerts consolidation formula in A1"));
  checks.push(checkConsolidationSheetFormula_(spreadsheet, GSTK_SHEET.LOTS_CONSOLIDE, "Lots consolidation formula in A1"));
  checks.push(checkPurchaseSheetHeader_(spreadsheet));
  checks.push(checkFormLinksKeys_(spreadsheet));

  const runAt = nowIso_(spreadsheet);
  const table = [["Controle", "Statut", "Details", "LastRun", "OwnerAction"]];

  for (let i = 0; i < checks.length; i += 1) {
    table.push([
      checks[i].control,
      checks[i].status,
      checks[i].details,
      runAt,
      checks[i].ownerAction,
    ]);
  }

  safeWriteBlock_(healthSheet, 1, 1, table);
  SpreadsheetApp.flush();
  logInfo_("runSystemHealthCheckFromDashboard completed with " + checks.length + " checks.");

  return {
    timestamp: runAt,
    checks: checks,
  };
}

function checkConfigSources_(spreadsheet) {
  try {
    const sheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.CONFIG_SOURCES);
    const lastRow = sheet.getLastRow();
    if (lastRow <= 1) {
      return {
        control: "CONFIG_SOURCES",
        status: "KO",
        details: "No source row configured.",
        ownerAction: "Add at least 2 source rows with valid URLs.",
      };
    }

    const rows = sheet.getRange(2, 1, lastRow - 1, Math.max(8, sheet.getLastColumn())).getValues();
    let enabledCount = 0;
    let validUrlCount = 0;

    for (let i = 0; i < rows.length; i += 1) {
      const enabled = normalizeBoolean_(rows[i][4]);
      if (!enabled) continue;
      enabledCount += 1;
      if (validateSpreadsheetUrl_(rows[i][3])) {
        validUrlCount += 1;
      }
    }

    const ok = enabledCount >= 2 && validUrlCount >= 2;
    return {
      control: "CONFIG_SOURCES",
      status: ok ? "OK" : "KO",
      details: "Enabled=" + enabledCount + " | ValidUrls=" + validUrlCount,
      ownerAction: ok ? "None" : "Ensure at least two enabled source URLs are valid.",
    };
  } catch (error) {
    return {
      control: "CONFIG_SOURCES",
      status: "KO",
      details: "Error: " + String(error && error.message ? error.message : error),
      ownerAction: "Fix sheet structure and retry.",
    };
  }
}

function checkConsolidationSheetFormula_(spreadsheet, sheetName, label) {
  try {
    const sheet = getRequiredSheet_(spreadsheet, sheetName);
    const a1Formula = String(sheet.getRange(1, 1).getFormula() || "").trim();
    const a1Value = String(sheet.getRange(1, 1).getDisplayValue() || "").trim();
    const hasHeader = !!a1Value;
    const ok = !!a1Formula || hasHeader;
    return {
      control: label,
      status: ok ? "OK" : "KO",
      details: ok ? "Sheet ready." : "A1 formula and header are empty.",
      ownerAction: ok ? "None" : "Restore consolidation header/formula.",
    };
  } catch (error) {
    return {
      control: label,
      status: "KO",
      details: "Error: " + String(error && error.message ? error.message : error),
      ownerAction: "Recreate missing sheet.",
    };
  }
}

function checkPurchaseSheetHeader_(spreadsheet) {
  try {
    const sheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.PURCHASE_CONSOLIDE);
    const header = sheet.getRange(1, 1, 1, Math.max(10, sheet.getLastColumn())).getDisplayValues()[0];
    const hasHeader = header.some(function (cell) {
      return String(cell || "").trim() !== "";
    });
    return {
      control: "PURCHASE_CONSOLIDE",
      status: hasHeader ? "OK" : "KO",
      details: hasHeader ? "Header exists. Empty data is allowed in V1." : "Missing header row.",
      ownerAction: hasHeader ? "None" : "Restore purchase header.",
    };
  } catch (error) {
    return {
      control: "PURCHASE_CONSOLIDE",
      status: "KO",
      details: "Error: " + String(error && error.message ? error.message : error),
      ownerAction: "Recreate sheet header.",
    };
  }
}

function checkFormLinksKeys_(spreadsheet) {
  try {
    const sheet = getRequiredSheet_(spreadsheet, GSTK_SHEET.FORM_LINKS);
    const lastRow = sheet.getLastRow();
    if (lastRow <= 1) {
      return {
        control: "FORM_LINKS_KEYS",
        status: "KO",
        details: "No form keys found.",
        ownerAction: "Run ensureFormLinksKeysV1_.",
      };
    }

    const rows = sheet.getRange(2, 1, lastRow - 1, 1).getDisplayValues();
    const existing = {};
    for (let i = 0; i < rows.length; i += 1) {
      const key = String(rows[i][0] || "").trim();
      if (key) existing[key] = true;
    }

    const missing = [];
    for (let j = 0; j < GSTK_REQUIRED_FORM_KEYS.length; j += 1) {
      if (!existing[GSTK_REQUIRED_FORM_KEYS[j]]) {
        missing.push(GSTK_REQUIRED_FORM_KEYS[j]);
      }
    }

    return {
      control: "FORM_LINKS_KEYS",
      status: missing.length === 0 ? "OK" : "KO",
      details: missing.length === 0 ? "All expected keys are present." : "Missing: " + missing.join(", "),
      ownerAction: missing.length === 0 ? "None" : "Run ensureFormLinksKeysV1_.",
    };
  } catch (error) {
    return {
      control: "FORM_LINKS_KEYS",
      status: "KO",
      details: "Error: " + String(error && error.message ? error.message : error),
      ownerAction: "Fix FORM_LINKS and retry.",
    };
  }
}
