import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchAboutInfo } from "./api";

const voiceCommands = [
  {
    label: "Ajouter des articles",
    phrases: ["ajouter [nombre] [nom]", "ajoute [nombre] [nom]"],
    description: "Augmente la quantité d'un article en stock.",
    example: "Ex. : 'ajouter 5 gants anti-feu'"
  },
  {
    label: "Retirer des articles",
    phrases: ["retirer [nombre] [nom]"],
    description: "Décrémente un article sans ouvrir l'interface.",
    example: "Ex. : 'retirer 2 bouteilles oxygène'"
  },
  {
    label: "Consulter une quantité",
    phrases: ["quantité de [nom]"],
    description: "Annonce la quantité disponible pour l'article demandé.",
    example: "Ex. : 'quantité de casque F1'"
  },
  {
    label: "Générer un code-barres",
    phrases: ["générer codebarre pour [nom]", "générer code-barres pour [nom]"],
    description: "Crée à la volée le code-barres de l'article ciblé.",
    example: "Ex. : 'générer codebarre pour radio portative'"
  },
  {
    label: "Obtenir de l'aide",
    phrases: ["aide", "aide vocale"],
    description: "Ré-explique les commandes et relit la liste disponible.",
    example: "Ex. : 'aide vocale'"
  },
  {
    label: "Arrêter l'écoute",
    phrases: ["stop voice", "arrête écoute", "arrete écoute"],
    description: "Désactive temporairement la reconnaissance vocale.",
    example: "Ex. : 'arrête écoute'"
  }
];

function formatDate(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function AboutPage() {
  const { data, isFetching, isError, error } = useQuery({
    queryKey: ["about", "info"],
    queryFn: fetchAboutInfo
  });

  const lastUpdate = useMemo(() => formatDate(data?.version.last_update ?? null), [data?.version.last_update]);

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">À propos</h2>
        <p className="text-sm text-slate-400">Découvrez la mission du programme, sa licence et la version actuellement déployée.</p>
      </header>

      {isFetching && !data ? <p className="text-sm text-slate-400">Chargement des informations...</p> : null}

      {isError ? (
        <div className="rounded-md border border-red-500 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error instanceof Error ? error.message : "Impossible de récupérer les informations."}
        </div>
      ) : null}

      {data ? (
        <div className="grid gap-6 lg:grid-cols-3">
          <section className="space-y-4 rounded-lg border border-slate-700 bg-slate-900/70 p-5 lg:col-span-2">
            <header className="space-y-1">
              <h3 className="text-lg font-semibold text-white">Résumé du programme</h3>
              <p className="text-xs text-slate-400">Présentation synthétique de Gestion Stock Pro 2.0.</p>
            </header>
            <p className="text-sm leading-relaxed text-slate-200">{data.summary}</p>
          </section>

          <section className="space-y-4 rounded-lg border border-slate-700 bg-slate-800/60 p-5">
            <header className="space-y-1">
              <h3 className="text-lg font-semibold text-white">Version et mises à jour</h3>
              <p className="text-xs text-slate-400">Informations basées sur les derniers déploiements GitHub.</p>
            </header>
            <dl className="space-y-3 text-sm text-slate-200">
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">Version</dt>
                <dd className="font-medium text-white">{data.version.label}</dd>
              </div>
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">Branche suivie</dt>
                <dd className="text-white">{data.version.branch}</dd>
              </div>
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">Dernière mise à jour</dt>
                <dd className="text-white">{lastUpdate ?? "Non renseignée"}</dd>
              </div>
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">Commit source</dt>
                <dd className="font-mono text-xs text-white">{data.version.source_commit?.slice(0, 12) ?? "-"}</dd>
              </div>
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">État</dt>
                <dd className={data.version.pending_update ? "text-amber-300" : "text-emerald-300"}>
                  {data.version.pending_update ? "Mise à jour disponible" : "Serveur synchronisé"}
                </dd>
              </div>
            </dl>
          </section>
        </div>
      ) : null}

      {data ? (
        <section className="space-y-4 rounded-lg border border-slate-700 bg-slate-900/70 p-5">
          <header className="space-y-1">
            <h3 className="text-lg font-semibold text-white">Licence</h3>
            <p className="text-xs text-slate-400">Texte complet de la licence appliquée au logiciel.</p>
          </header>
          <div className="max-h-[420px] overflow-y-auto rounded-md border border-slate-800 bg-slate-950/60 p-4 text-sm leading-relaxed text-slate-200">
            <pre className="whitespace-pre-wrap font-sans text-xs sm:text-sm">{data.license}</pre>
          </div>
        </section>
      ) : null}

      <section className="space-y-4 rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <header className="space-y-1">
          <h3 className="text-lg font-semibold text-white">Commandes vocales disponibles</h3>
          <p className="text-xs text-slate-400">
            Liste des phrases reconnues par l'assistant vocal embarqué et de leurs effets dans le stock.
          </p>
        </header>
        <div className="grid gap-4 md:grid-cols-2">
          {voiceCommands.map((command) => (
            <article key={command.label} className="space-y-2 rounded-md border border-slate-800 bg-slate-950/40 p-4">
              <div>
                <p className="text-sm font-semibold text-white">{command.label}</p>
                <p className="text-xs text-slate-400">{command.description}</p>
              </div>
              <ul className="space-y-1 text-sm text-slate-200">
                {command.phrases.map((phrase) => (
                  <li key={phrase} className="font-mono text-xs text-amber-200">{phrase}</li>
                ))}
              </ul>
              <p className="text-xs italic text-slate-400">{command.example}</p>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
