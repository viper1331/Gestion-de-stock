export interface ExistingSkuEntry {
  id: number;
  sku: string;
}

const DIACRITICS_REGEX = /[\u0300-\u036f]/g;

function normalizeString(value: string): string {
  return value
    .normalize("NFD")
    .replace(DIACRITICS_REGEX, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

function sanitizePrefix(prefix: string): string {
  const normalized = normalizeString(prefix || "");
  return normalized || "SKU";
}

function buildBaseFromSource(prefix: string, source: string): string {
  const sanitizedPrefix = sanitizePrefix(prefix);
  const normalizedSource = normalizeString(source || "");
  if (!normalizedSource) {
    return `${sanitizedPrefix}-AUTO`;
  }
  const truncatedSource = normalizedSource.slice(0, 32);
  return `${sanitizedPrefix}-${truncatedSource}`;
}

function isSkuTaken(
  candidate: string,
  existingSkus: ExistingSkuEntry[],
  excludeId: number | null | undefined
): boolean {
  const normalizedCandidate = normalizeString(candidate);
  if (!normalizedCandidate) {
    return false;
  }
  return existingSkus.some((entry) => {
    if (!entry.sku || entry.id === excludeId) {
      return false;
    }
    return normalizeString(entry.sku) === normalizedCandidate;
  });
}

export function ensureUniqueSku({
  desiredSku,
  prefix,
  source,
  existingSkus,
  excludeId = null
}: {
  desiredSku?: string | null;
  prefix: string;
  source: string;
  existingSkus: ExistingSkuEntry[];
  excludeId?: number | null;
}): string {
  const normalizedDesired = normalizeString(desiredSku ?? "");
  const base = normalizedDesired || buildBaseFromSource(prefix, source);
  let candidate = base;
  let counter = 2;

  while (isSkuTaken(candidate, existingSkus, excludeId)) {
    candidate = `${base}-${counter}`;
    counter += 1;
  }

  return candidate;
}

export function normalizeSkuInput(value: string): string {
  return normalizeString(value || "");
}
