import { useTheme } from "../app/theme";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      onClick={toggleTheme}
      className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
      title={`Basculer vers le mode ${theme === "dark" ? "clair" : "sombre"}`}
    >
      Mode {theme === "dark" ? "clair" : "sombre"}
    </button>
  );
}
