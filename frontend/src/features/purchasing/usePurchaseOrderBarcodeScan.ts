import type { KeyboardEvent } from "react";
import { useCallback, useRef, useState } from "react";
import { AxiosError } from "axios";
import { toast } from "sonner";

import { api } from "../../lib/api";

export type BarcodeModule = "clothing" | "remise" | "pharmacy";

export interface BarcodeLookupItem {
  id: number;
  name: string;
}

interface BarcodeConflictResponse {
  matches: BarcodeLookupItem[];
}

export interface PurchaseOrderItemLabelData {
  id: number;
  name: string;
  sku?: string | null;
  barcode?: string | null;
  size?: string | null;
  dosage?: string | null;
  packaging?: string | null;
  quantity?: number | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  extra?: Record<string, unknown> | null;
}

const UNIT_KEYS = ["unit", "unit_name", "unit_label"];

export function formatPurchaseOrderItemLabel(
  item: PurchaseOrderItemLabelData,
  supplierName?: string | null
): string {
  const segments: string[] = [];
  if (item.name) {
    segments.push(item.name);
  }

  const sku = item.sku ?? item.barcode;
  if (sku) {
    segments.push(sku);
  }

  const variantParts = [item.size, item.packaging, item.dosage].filter(Boolean);
  if (variantParts.length > 0) {
    segments.push(variantParts.join(" "));
  }

  if (typeof item.quantity === "number") {
    segments.push(`Stock: ${item.quantity}`);
  }

  const unitValue =
    item.extra && typeof item.extra === "object"
      ? UNIT_KEYS.map((key) => item.extra?.[key]).find((value) => typeof value === "string")
      : null;
  if (typeof unitValue === "string" && unitValue.trim()) {
    segments.push(unitValue.trim());
  }

  const supplierLabel = supplierName ?? item.supplier_name;
  if (supplierLabel) {
    segments.push(`Fourn: ${supplierLabel}`);
  }

  return segments.join(" — ");
}

interface UsePurchaseOrderBarcodeScanOptions {
  module: BarcodeModule;
  onAddItem: (match: BarcodeLookupItem) => void;
}

export function usePurchaseOrderBarcodeScan({
  module,
  onAddItem
}: UsePurchaseOrderBarcodeScanOptions) {
  const [barcodeInput, setBarcodeInput] = useState("");
  const [conflictMatches, setConflictMatches] = useState<BarcodeLookupItem[] | null>(null);
  const [isResolving, setIsResolving] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const lastScanRef = useRef<{ value: string; at: number } | null>(null);

  const focusInput = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const handleSuccess = useCallback(
    (match: BarcodeLookupItem) => {
      onAddItem(match);
      toast.success(`Article ajouté: ${match.name}`);
    },
    [onAddItem]
  );

  const submitBarcode = useCallback(async () => {
    const trimmed = barcodeInput.trim();
    if (!trimmed) {
      return;
    }
    const normalized = trimmed.replace(/\s+/g, "");
    if (!normalized) {
      return;
    }
    const now = Date.now();
    if (
      lastScanRef.current &&
      lastScanRef.current.value === normalized &&
      now - lastScanRef.current.at < 250
    ) {
      return;
    }
    lastScanRef.current = { value: normalized, at: now };
    setIsResolving(true);
    try {
      const response = await api.get<BarcodeLookupItem>("/items/by-barcode", {
        params: { module, barcode: trimmed }
      });
      handleSuccess(response.data);
      setBarcodeInput("");
    } catch (error) {
      const axiosError = error as AxiosError<BarcodeConflictResponse>;
      const status = axiosError.response?.status;
      if (status === 404) {
        toast.error("Code-barres introuvable");
        setBarcodeInput("");
      } else if (status === 409) {
        const matches = axiosError.response?.data?.matches ?? [];
        if (matches.length > 0) {
          setConflictMatches(matches);
          setBarcodeInput("");
        } else {
          toast.error("Plusieurs articles correspondent au code-barres.");
        }
      } else {
        toast.error("Impossible de récupérer l'article.");
      }
    } finally {
      setIsResolving(false);
      focusInput();
    }
  }, [barcodeInput, focusInput, handleSuccess, module]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submitBarcode();
      }
    },
    [submitBarcode]
  );

  const selectConflictMatch = useCallback(
    (match: BarcodeLookupItem) => {
      setConflictMatches(null);
      handleSuccess(match);
      focusInput();
    },
    [focusInput, handleSuccess]
  );

  const clearConflictMatches = useCallback(() => {
    setConflictMatches(null);
    focusInput();
  }, [focusInput]);

  return {
    barcodeInput,
    setBarcodeInput,
    inputRef,
    conflictMatches,
    isResolving,
    handleKeyDown,
    submitBarcode,
    selectConflictMatch,
    clearConflictMatches
  };
}
