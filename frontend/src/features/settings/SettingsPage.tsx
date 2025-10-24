import { useEffect, useState } from "react";

import { api } from "../../lib/api";

interface ConfigEntry {
  section: string;
  key: string;
  value: string;
}

export function SettingsPage() {
  const [entries, setEntries] = useState<ConfigEntry[]>([]);

  useEffect(() => {
    api.get<ConfigEntry[]>("/config/").then((response) => setEntries(response.data));
  }, []);

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Paramètres</h2>
        <p className="text-sm text-slate-400">Synchronisez vos préférences avec le backend.</p>
      </header>
      <div className="rounded-lg border border-slate-800 bg-slate-900">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-900/70 text-left text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-4 py-3">Section</th>
              <th className="px-4 py-3">Clé</th>
              <th className="px-4 py-3">Valeur</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900">
            {entries.map((entry) => (
              <tr key={`${entry.section}.${entry.key}`} className="bg-slate-950 text-slate-100">
                <td className="px-4 py-3">{entry.section}</td>
                <td className="px-4 py-3 text-slate-300">{entry.key}</td>
                <td className="px-4 py-3">
                  <input
                    defaultValue={entry.value}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-1 text-sm text-slate-100"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
