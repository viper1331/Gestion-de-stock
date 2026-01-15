import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./useAuth";
import { AppTextInput } from "components/AppTextInput";

export function Login() {
  const navigate = useNavigate();
  const { login, verifyTwoFactor, verifyRecoveryCode, clearError, isLoading, error } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [remember, setRemember] = useState(true);
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [step, setStep] = useState<"credentials" | "totp" | "recovery">("credentials");
  const [needsTwoFactorSetup, setNeedsTwoFactorSetup] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const result = await login({ username, password, remember });
    if (result.status === "requires_2fa") {
      setChallengeId(result.challenge.challenge_id);
      setStep("totp");
      setTotpCode("");
      setRecoveryCode("");
      setNeedsTwoFactorSetup(false);
      clearError();
    }
    if (result.status === "2fa_setup_required") {
      setNeedsTwoFactorSetup(true);
    } else {
      setNeedsTwoFactorSetup(false);
    }
  };

  const handleVerify = async (event: FormEvent) => {
    event.preventDefault();
    if (!challengeId) {
      return;
    }
    await verifyTwoFactor({
      challengeId,
      code: totpCode,
      rememberSession: remember
    });
  };

  const handleRecovery = async (event: FormEvent) => {
    event.preventDefault();
    if (!challengeId) {
      return;
    }
    await verifyRecoveryCode({
      challengeId,
      recoveryCode,
      rememberSession: remember
    });
  };

  if (step !== "credentials") {
    return (
      <form
        className="space-y-6"
        onSubmit={step === "recovery" ? handleRecovery : handleVerify}
      >
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold">Vérification 2FA</h1>
          <p className="text-sm text-slate-400">
            Entrez le code fourni par votre application Authenticator.
          </p>
        </header>
        {step === "totp" ? (
          <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-200" htmlFor="totpCode">
              Code à 6 chiffres
            </label>
            <AppTextInput
              id="totpCode"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={totpCode}
              onChange={(event) => setTotpCode(event.target.value)}
              title="Saisissez le code 2FA"
              inputMode="numeric"
            />
          </div>
        ) : (
          <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-200" htmlFor="recoveryCode">
              Code de récupération
            </label>
            <AppTextInput
              id="recoveryCode"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={recoveryCode}
              onChange={(event) => setRecoveryCode(event.target.value.toUpperCase())}
              title="Saisissez un code de récupération"
            />
          </div>
        )}
        <div className="flex flex-wrap gap-3 text-sm">
          {step === "totp" ? (
            <button
              type="button"
              onClick={() => {
                setStep("recovery");
                clearError();
              }}
              className="text-indigo-300 hover:text-indigo-200"
            >
              Utiliser un code de récupération
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                setStep("totp");
                clearError();
              }}
              className="text-indigo-300 hover:text-indigo-200"
            >
              Revenir au code TOTP
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              setStep("credentials");
              setChallengeId(null);
              setNeedsTwoFactorSetup(false);
              clearError();
            }}
            className="text-slate-400 hover:text-slate-200"
          >
            Retour à la connexion
          </button>
        </div>
        {error ? <p className="text-sm text-red-400">{error}</p> : null}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          title="Valider le code 2FA"
        >
          {isLoading ? "Vérification..." : "Valider"}
        </button>
      </form>
    );
  }

  return (
    <form className="space-y-6" onSubmit={handleSubmit}>
      <header className="space-y-1 text-center">
        <h1 className="text-2xl font-semibold">Connexion</h1>
        <p className="text-sm text-slate-400">Entrez vos identifiants pour accéder au stock.</p>
      </header>
      <div className="space-y-2">
        <label className="block text-sm font-medium text-slate-200" htmlFor="username">
          Identifiant
        </label>
        <AppTextInput
          id="username"
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          title="Entrez votre identifiant de connexion"
        />
      </div>
      <div className="space-y-2">
        <label className="block text-sm font-medium text-slate-200" htmlFor="password">
          Mot de passe
        </label>
        <AppTextInput
          id="password"
          type="password"
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          title="Saisissez votre mot de passe"
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <AppTextInput
          type="checkbox"
          checked={remember}
          onChange={(event) => setRemember(event.target.checked)}
          title="Rester connecté sur cet appareil"
        />
        Se souvenir de moi
      </label>
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      {needsTwoFactorSetup ? (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
          <p>La 2FA est obligatoire pour se connecter.</p>
          <button
            type="button"
            onClick={() => navigate("/settings")}
            className="mt-2 inline-flex items-center text-sm font-semibold text-amber-100 hover:text-amber-50"
          >
            Configurer 2FA
          </button>
        </div>
      ) : null}
      <button
        type="submit"
        disabled={isLoading}
        className="w-full rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
        title="Valider mes identifiants"
      >
        {isLoading ? "Connexion..." : "Se connecter"}
      </button>
    </form>
  );
}
