import { FormEvent, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";

interface LowStockItem {
  item: {
    id: number;
    name: string;
    sku: string;
    quantity: number;
    low_stock_threshold: number;
  };
  shortage: number;
}

export function ReportsPage() {
  const queryClient = useQueryClient();
  const [threshold, setThreshold] = useState(1);
  const [debouncedThreshold, setDebouncedThreshold] = useState(1);
  const [isExporting, setIsExporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedThreshold(threshold), 300);
    return () => window.clearTimeout(timeout);
  }, [threshold]);

  const { data = [], isFetching } = useQuery({
    queryKey: ["reports", "low-stock", debouncedThreshold],
    queryFn: async () => {
      const response = await api.get<LowStockItem[]>("/reports/low-stock", { params: { threshold: debouncedThreshold } });
      return response.data;
    }
  });

  const handleExport = async (event: FormEvent) => {
    event.preventDefault();
    setIsExporting(true);
    setMessage(null);
    setError(null);
    try {
      const response = await api.get("/reports/export/csv", { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = "inventaire.csv";
      link.click();
      URL.revokeObjectURL(url);
      setMessage("Export CSV téléchargé.");
    } catch (err) {
      setError("Échec de l'export CSV.");
    } finally {
      setIsExporting(false);
      await queryClient.invalidateQueries({ queryKey: ["reports", "low-stock"] });
    }
  };

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Rapports</h2>
        <p className="text-sm text-slate-400">Articles en dessous de leur seuil de sécurité.</p>
      </header>
      <form className="flex flex-wrap items-center gap-4" onSubmit={handleExport}>
        <label className="text-sm text-slate-300">
          Seuil minimum
          <input
            type="number"
            value={threshold}
            onChange={(event) => setThreshold(Number(event.target.value))}
            className="ml-2 w-24 rounded-md border border-slate-800 bg-slate-950 px-3 py-1 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Afficher les articles dont le stock est inférieur ou égal à ce seuil"
          />
        </label>
        <button
          type="submit"
          disabled={isExporting}
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          title="Télécharger le rapport des stocks en CSV"
        >
          {isExporting ? "Export..." : "Exporter en CSV"}
        </button>
        {isFetching ? <span className="text-xs text-slate-400">Actualisation du rapport...</span> : null}
      </form>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      <div className="rounded-lg border border-slate-800 bg-slate-900">
        <table className="min-w-full divide-y divide-slate-800">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="px-4 py-3">Article</th>
              <th className="px-4 py-3">SKU</th>
              <th className="px-4 py-3">Quantité</th>
              <th className="px-4 py-3">Seuil</th>
              <th className="px-4 py-3">Manque</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900">
            {data.map((entry) => (
              <tr key={entry.item.id} className="bg-slate-950 text-sm text-slate-100">
                <td className="px-4 py-3">{entry.item.name}</td>
                <td className="px-4 py-3 text-slate-300">{entry.item.sku}</td>
                <td className="px-4 py-3 font-semibold">{entry.item.quantity}</td>
                <td className="px-4 py-3 text-slate-300">{entry.item.low_stock_threshold}</td>
                <td className="px-4 py-3 text-amber-300">{entry.shortage}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
