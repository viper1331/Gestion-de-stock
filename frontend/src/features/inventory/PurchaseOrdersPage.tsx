import { useQuery } from "@tanstack/react-query";

import { PurchaseOrdersPanel } from "./PurchaseOrdersPanel";
import { api } from "../../lib/api";

interface Supplier {
  id: number;
  name: string;
}

export function PurchaseOrdersPage() {
  const { data: suppliers = [], isFetching } = useQuery({
    queryKey: ["suppliers", { module: "suppliers" }],
    queryFn: async () => {
      const response = await api.get<Supplier[]>("/suppliers/", {
        params: { module: "suppliers" }
      });
      return response.data;
    }
  });

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Bons de commande</h2>
        <p className="text-sm text-slate-400">
          Centralisez la création, le suivi et la réception de vos bons de commande.
        </p>
        {isFetching ? (
          <p className="text-xs text-slate-500">Chargement des fournisseurs...</p>
        ) : null}
      </header>
      <PurchaseOrdersPanel suppliers={suppliers} />
    </section>
  );
}
