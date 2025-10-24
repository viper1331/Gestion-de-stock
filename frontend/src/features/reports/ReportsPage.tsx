import { useQuery } from "@tanstack/react-query";

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
  const { data } = useQuery({
    queryKey: ["reports", "low-stock"],
    queryFn: async () => {
      const response = await api.get<LowStockItem[]>("/reports/low-stock", { params: { threshold: 1 } });
      return response.data;
    }
  });

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Rapports</h2>
        <p className="text-sm text-slate-400">Articles en dessous de leur seuil de sécurité.</p>
      </header>
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
            {data?.map((entry) => (
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
