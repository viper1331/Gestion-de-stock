import { useVoice } from "./useVoice";

type MicToggleProps = {
  compact?: boolean;
};

export function MicToggle({ compact = false }: MicToggleProps) {
  const { isListening } = useVoice();
  const label = isListening ? "Micro actif" : "Micro inactif";
  const icon = isListening ? "🎙️" : "🎤";

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border border-slate-800 text-xs ${
        compact ? "px-2 py-2 justify-center" : "px-3 py-2"
      } ${isListening ? "bg-emerald-500/20 text-emerald-200" : "bg-slate-800 text-slate-300"}`}
      title={isListening ? "Le micro écoute vos commandes vocales" : "Activer le micro pour utiliser la voix"}
    >
      <span className="h-2 w-2 rounded-full bg-current" />
      {compact ? <span aria-hidden>{icon}</span> : <span>{label}</span>}
      <span className="sr-only">{label}</span>
    </span>
  );
}
