import type { ConfigEntry } from "../../lib/config";

export const DEFAULT_HOME_CONFIG = {
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

export type HomePageConfig = {
  -readonly [Key in keyof typeof DEFAULT_HOME_CONFIG]: string;
};

export type HomePageConfigKey = keyof typeof DEFAULT_HOME_CONFIG;

export function isHomePageConfigKey(value: string): value is HomePageConfigKey {
  return Object.prototype.hasOwnProperty.call(DEFAULT_HOME_CONFIG, value);
}

export function buildHomeConfig(entries: ConfigEntry[]): HomePageConfig {
  const config: HomePageConfig = { ...DEFAULT_HOME_CONFIG };

  entries.forEach((entry) => {
    if (entry.section !== "homepage") {
      return;
    }

    if (!isHomePageConfigKey(entry.key)) {
      return;
    }

    const trimmed = entry.value.trim();
    config[entry.key] = trimmed.length > 0 ? trimmed : DEFAULT_HOME_CONFIG[entry.key];
  });

  return config;
}
