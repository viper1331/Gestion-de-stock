import { useVoice } from "./useVoice";

export function MicToggle() {
  const { isListening } = useVoice();
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs ${
      isListening ? "bg-emerald-500/20 text-emerald-200" : "bg-slate-800 text-slate-300"
    }`}>
      <span className="h-2 w-2 rounded-full bg-current" />
      {isListening ? "Micro actif" : "Micro inactif"}
    </span>
  );
}
