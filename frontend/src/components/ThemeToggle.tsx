import { useTheme } from "../app/theme";

type ThemeToggleProps = {
  compact?: boolean;
};

export function ThemeToggle({ compact = false }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const label = `Mode ${theme === "dark" ? "clair" : "sombre"}`;
  const icon = theme === "dark" ? "☀️" : "🌙";

  return (
    <button
      onClick={toggleTheme}
      className={`flex items-center gap-2 rounded-md border border-slate-700 text-sm text-slate-200 hover:bg-slate-800 ${
        compact ? "justify-center px-2 py-2" : "px-3 py-2"
      }`}
      title={`Basculer vers le mode ${theme === "dark" ? "clair" : "sombre"}`}
    >
      <span aria-hidden>{icon}</span>
      <span className={compact ? "sr-only" : undefined}>{label}</span>
    </button>
  );
}
