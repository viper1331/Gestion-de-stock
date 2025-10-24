import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { persistValue, readPersistedValue } from "../../lib/persist";

interface Item {
  id: number;
  name: string;
  sku: string;
  quantity: number;
  low_stock_threshold: number;
}

export function Dashboard() {
  const { data } = useQuery({
    queryKey: ["items"],
    queryFn: async () => {
      const response = await api.get<Item[]>("/items/");
      return response.data;
    }
  });

  const columnWidths = readPersistedValue<Record<string, number>>("gsp/columns", {
    name: 220,
    sku: 140,
    quantity: 100
  });

  const saveWidth = (key: string, width: number) => {
    persistValue("gsp/columns", { ...columnWidths, [key]: width });
  };

  return (
    <section className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">Inventaire</h2>
          <p className="text-sm text-slate-400">Suivez les niveaux de stock en temps réel.</p>
        </div>
        <button className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400">
          Nouvel article
        </button>
      </header>
      <div className="overflow-hidden rounded-lg border border-slate-800">
        <table className="min-w-full divide-y divide-slate-800">
          <thead className="bg-slate-900/50">
            <tr>
              <ResizableHeader label="Article" width={columnWidths.name} onResize={(value) => saveWidth("name", value)} />
              <ResizableHeader label="SKU" width={columnWidths.sku} onResize={(value) => saveWidth("sku", value)} />
              <ResizableHeader
                label="Quantité"
                width={columnWidths.quantity}
                onResize={(value) => saveWidth("quantity", value)}
              />
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">Seuil</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900 bg-slate-950/50">
            {data?.map((item, index) => (
              <tr key={item.id} className={index % 2 === 0 ? "bg-slate-950" : "bg-slate-900/40"}>
                <td className="px-4 py-3 text-sm text-slate-100">{item.name}</td>
                <td className="px-4 py-3 text-sm text-slate-300">{item.sku}</td>
                <td className="px-4 py-3 text-sm font-semibold text-slate-100">{item.quantity}</td>
                <td className="px-4 py-3 text-sm text-slate-300">{item.low_stock_threshold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ResizableHeader({
  label,
  width,
  onResize
}: {
  label: string;
  width: number;
  onResize: (value: number) => void;
}) {
  return (
    <th style={{ width }} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
      <div className="flex items-center justify-between">
        <span>{label}</span>
        <input
          type="range"
          min={120}
          max={320}
          value={width}
          onChange={(event) => onResize(Number(event.target.value))}
          className="h-1 w-24 cursor-ew-resize appearance-none rounded-full bg-slate-700"
        />
      </div>
    </th>
  );
}
