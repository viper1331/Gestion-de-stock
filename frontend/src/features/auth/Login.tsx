import { FormEvent, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";
import { useAuth } from "./useAuth";
import { AppTextInput } from "components/AppTextInput";

export function Login() {
  const { login, verifyTwoFactor, confirmTotpEnrollment, clearError, isLoading, error } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [remember, setRemember] = useState(true);
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpauthUri, setOtpauthUri] = useState<string | null>(null);
  const [secretMasked, setSecretMasked] = useState<string | null>(null);
  const [secretPlain, setSecretPlain] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [step, setStep] = useState<"credentials" | "totp" | "enroll">("credentials");

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const result = await login({ username, password, remember });
    if (result.status === "requires_2fa") {
      setChallengeId(result.challenge.challenge_token);
      setOtpauthUri(null);
      setSecretMasked(null);
      setSecretPlain(null);
      setStep("totp");
      setTotpCode("");
      clearError();
    } else if (result.status === "enroll_required") {
      setChallengeId(result.challenge.challenge_token);
      setOtpauthUri(result.challenge.otpauth_uri);
      setSecretMasked(result.challenge.secret_masked);
      setSecretPlain(result.challenge.secret_plain_if_allowed ?? null);
      setStep("enroll");
      setTotpCode("");
      clearError();
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

  const handleEnrollConfirm = async (event: FormEvent) => {
    event.preventDefault();
    if (!challengeId) {
      return;
    }
    await confirmTotpEnrollment({
      challengeToken: challengeId,
      code: totpCode,
      rememberSession: remember
    });
  };

  if (step !== "credentials") {
    return (
      <form className="space-y-6" onSubmit={step === "enroll" ? handleEnrollConfirm : handleVerify}>
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold">
            {step === "enroll" ? "Configurer l’authentification 2 facteurs" : "Entrer votre code"}
          </h1>
          <p className="text-sm text-slate-400">
            {step === "enroll"
              ? "Scannez le QR code puis saisissez le code généré."
              : "Entrez le code fourni par votre application Authenticator."}
          </p>
        </header>
        {step === "enroll" && otpauthUri ? (
          <div className="flex flex-col items-center gap-4 rounded-lg border border-slate-800 bg-slate-950 px-4 py-4">
            <QRCodeCanvas value={otpauthUri} size={180} />
            <div className="text-center text-xs text-slate-300">
              <p>Secret : {secretMasked}</p>
              {secretPlain ? <p className="text-slate-400">Secret (dev) : {secretPlain}</p> : null}
            </div>
          </div>
        ) : null}
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
        <div className="flex flex-wrap gap-3 text-sm">
          <button
            type="button"
            onClick={() => {
              setStep("credentials");
              setChallengeId(null);
              setOtpauthUri(null);
              setSecretMasked(null);
              setSecretPlain(null);
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
