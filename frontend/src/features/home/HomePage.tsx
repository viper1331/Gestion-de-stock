import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "../auth/useAuth";
import { fetchConfigEntries, ConfigEntry } from "../../lib/config";

const DEFAULT_CONFIG = {
  title: "Gestion Stock Pro",
  subtitle: "Centralisez vos opérations de stock, vos achats et vos dotations en un seul endroit.",
  welcome_message:
    "Bienvenue sur votre espace de travail. Retrouvez ici une vue synthétique de vos modules et vos actions prioritaires.",
  primary_link_label: "Ouvrir l'inventaire habillement",
  primary_link_path: "/inventory",
  secondary_link_label: "Consulter les rapports d'activité",
  secondary_link_path: "/reports",
  announcement:
    "Pensez à vérifier les mises à jour dans l'onglet \"Mises à jour\" pour garder votre environnement à jour.",
  focus_1_label: "Inventaire habillement",
  focus_1_description: "Suivez les entrées, sorties et niveaux de stock en temps réel pour l'ensemble des articles.",
  focus_2_label: "Gestion des dotations",
  focus_2_description: "Attribuez les équipements aux collaborateurs et gardez l'historique des dotations à jour.",
  focus_3_label: "Rapports et analyses",
  focus_3_description: "Identifiez rapidement les tendances et anticipez les besoins grâce aux rapports consolidés."
} as const;

type HomePageConfig = { [Key in keyof typeof DEFAULT_CONFIG]: string };

type HomePageConfigKey = keyof typeof DEFAULT_CONFIG;

function isHomePageConfigKey(value: string): value is HomePageConfigKey {
  return Object.prototype.hasOwnProperty.call(DEFAULT_CONFIG, value);
}

function buildHomeConfig(entries: ConfigEntry[]): HomePageConfig {
  const config: HomePageConfig = { ...DEFAULT_CONFIG };

  entries.forEach((entry) => {
    if (entry.section !== "homepage") {
      return;
    }

    if (!isHomePageConfigKey(entry.key)) {
      return;
    }

    const trimmed = entry.value.trim();
    config[entry.key] = trimmed.length > 0 ? trimmed : DEFAULT_CONFIG[entry.key];
  });

  return config;
}

export function HomePage() {
  const { user } = useAuth();
  const { data: entries = [], isFetching } = useQuery({
    queryKey: ["config"],
    queryFn: fetchConfigEntries
  });

  const config = useMemo(() => buildHomeConfig(entries), [entries]);

  const quickLinks = useMemo(
    () =>
      [
        { label: config.primary_link_label, path: config.primary_link_path },
        { label: config.secondary_link_label, path: config.secondary_link_path }
      ].filter((link) => link.path.trim().length > 0),
    [config.primary_link_label, config.primary_link_path, config.secondary_link_label, config.secondary_link_path]
  );

  const focusCards = [
    { label: config.focus_1_label, description: config.focus_1_description },
    { label: config.focus_2_label, description: config.focus_2_description },
    { label: config.focus_3_label, description: config.focus_3_description }
  ];

  return (
    <section className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-gradient-to-r from-indigo-500/10 via-slate-950 to-slate-950 p-6 shadow-lg">
        <p className="text-sm text-indigo-300">Bonjour {user?.username ?? ""} !</p>
        <h1 className="mt-2 text-3xl font-bold text-white sm:text-4xl">{config.title}</h1>
        <p className="mt-3 max-w-3xl text-sm text-slate-300 sm:text-base">{config.subtitle}</p>
        <p className="mt-4 max-w-3xl text-sm text-slate-400">{config.welcome_message}</p>
        {quickLinks.length > 0 ? (
          <div className="mt-6 flex flex-wrap gap-3">
            {quickLinks.map((link) => (
              <Link
                key={`${link.label}-${link.path}`}
                to={link.path}
                className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-300"
              >
                {link.label}
              </Link>
            ))}
          </div>
        ) : null}
        {isFetching ? (
          <p className="mt-4 text-xs text-slate-500">Mise à jour de la configuration...</p>
        ) : null}
      </div>

      {config.announcement ? (
        <div className="rounded-lg border border-indigo-500/40 bg-indigo-950/60 p-4 text-indigo-100 shadow">
          <p className="text-xs font-semibold uppercase tracking-wide text-indigo-300">Annonce</p>
          <p className="mt-2 text-sm leading-relaxed">{config.announcement}</p>
        </div>
      ) : null}

      <section className="space-y-3">
        <header>
          <h2 className="text-lg font-semibold text-white">Vos priorités</h2>
          <p className="text-sm text-slate-400">
            Adaptez ces encadrés depuis les paramètres pour refléter l'organisation de votre service.
          </p>
        </header>
        <div className="grid gap-4 md:grid-cols-3">
          {focusCards.map((card) => (
            <article
              key={card.label}
              className="rounded-lg border border-slate-800 bg-slate-900/70 p-4 shadow-sm transition-colors hover:border-indigo-500/60"
            >
              <h3 className="text-base font-semibold text-white">{card.label}</h3>
              <p className="mt-2 text-sm text-slate-400">{card.description}</p>
            </article>
          ))}
        </div>
      </section>

      {user?.role === "admin" ? (
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4 shadow">
          <h2 className="text-base font-semibold text-white">Personnalisez l'accueil</h2>
          <p className="mt-2 text-sm text-slate-400">
            Les textes et liens de cette page proviennent de la section « homepage » de la configuration. Modifiez-les pour
            refléter vos procédures internes.
          </p>
          <div className="mt-4">
            <Link
              to="/settings"
              className="inline-flex items-center justify-center rounded-md border border-indigo-500 px-3 py-2 text-sm font-semibold text-indigo-200 hover:bg-indigo-500/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-300"
            >
              Ouvrir les paramètres
            </Link>
          </div>
        </section>
      ) : null}
    </section>
  );
}
