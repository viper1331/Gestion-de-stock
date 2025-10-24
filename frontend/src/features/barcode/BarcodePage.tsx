import { FormEvent, useState } from "react";

import { api } from "../../lib/api";

export function BarcodePage() {
  const [sku, setSku] = useState("SKU-001");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setIsGenerating(true);
    try {
      const response = await api.post(`/barcode/generate/${sku}`, undefined, { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      setImageUrl(url);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Codes-barres</h2>
        <p className="text-sm text-slate-400">Générez ou scannez les codes-barres des articles.</p>
      </header>
      <form onSubmit={handleSubmit} className="flex items-end gap-4">
        <label className="flex flex-col text-sm text-slate-300">
          SKU
          <input
            value={sku}
            onChange={(event) => setSku(event.target.value)}
            className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
          />
        </label>
        <button
          type="submit"
          disabled={isGenerating}
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:opacity-70"
        >
          {isGenerating ? "Génération..." : "Générer"}
        </button>
      </form>
      {imageUrl ? (
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-6">
          <img src={imageUrl} alt={`Barcode ${sku}`} className="mx-auto" />
        </div>
      ) : null}
    </section>
  );
}
