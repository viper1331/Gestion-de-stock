import { FormEvent, useMemo, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";
import { useAuth } from "./useAuth";
import { AppTextInput } from "components/AppTextInput";
import { api } from "../../lib/api";
import { useLocation } from "react-router-dom";

export function Login() {
  const { login, verifyTwoFactor, confirmTotpEnrollment, clearError, isLoading, error } = useAuth();
  const location = useLocation();
  const [identifier, setIdentifier] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [remember, setRemember] = useState(true);
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpauthUri, setOtpauthUri] = useState<string | null>(null);
  const [secretMasked, setSecretMasked] = useState<string | null>(null);
  const [secretPlain, setSecretPlain] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [step, setStep] = useState<"credentials" | "totp" | "enroll">("credentials");
  const [mode, setMode] = useState<"login" | "register" | "register-success">("login");
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerPassword, setRegisterPassword] = useState("");
  const [registerDisplayName, setRegisterDisplayName] = useState("");
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registerLoading, setRegisterLoading] = useState(false);

  const idleLogoutMessage = useMemo(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("reason") === "idle") {
      return "Session expirée pour inactivité. Veuillez vous reconnecter.";
    }
    return null;
  }, [location.search]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedIdentifier = identifier.trim();
    const loginIdentifier = normalizedIdentifier.includes("@")
      ? normalizedIdentifier.toLowerCase()
      : normalizedIdentifier;
    const result = await login({ username: loginIdentifier, password, remember });
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

  const handleRegister = async (event: FormEvent) => {
    event.preventDefault();
    setRegisterError(null);
    setRegisterLoading(true);
    try {
      await api.post("/auth/register", {
        email: registerEmail,
        password: registerPassword,
        display_name: registerDisplayName || undefined
      });
      setMode("register-success");
    } catch (err) {
      const detail =
        typeof err === "object" && err && "response" in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      setRegisterError(detail ?? "Impossible d'envoyer la demande.");
    } finally {
      setRegisterLoading(false);
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
        {idleLogoutMessage ? (
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            {idleLogoutMessage}
          </p>
        ) : null}
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

  if (mode !== "login") {
    return (
      <form className="space-y-6" onSubmit={handleRegister}>
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold">Créer un compte</h1>
          <p className="text-sm text-slate-400">
            {mode === "register-success"
              ? "Demande envoyée, en attente de validation."
              : "Complétez le formulaire pour envoyer votre demande."}
          </p>
        </header>
        {mode === "register-success" ? (
          <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            Votre demande a bien été transmise à l’administrateur.
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <label className="block text-sm font-medium text-slate-200" htmlFor="registerEmail">
                Email
              </label>
              <AppTextInput
                id="registerEmail"
                type="email"
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
                value={registerEmail}
                onChange={(event) => setRegisterEmail(event.target.value)}
                title="Entrez votre email"
              />
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium text-slate-200" htmlFor="registerPassword">
                Mot de passe
              </label>
              <AppTextInput
                id="registerPassword"
                type="password"
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
                value={registerPassword}
                onChange={(event) => setRegisterPassword(event.target.value)}
                title="Choisissez un mot de passe"
              />
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium text-slate-200" htmlFor="registerDisplayName">
                Nom affiché (optionnel)
              </label>
              <AppTextInput
                id="registerDisplayName"
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
                value={registerDisplayName}
                onChange={(event) => setRegisterDisplayName(event.target.value)}
                title="Nom affiché"
              />
            </div>
            {registerError ? <p className="text-sm text-red-400">{registerError}</p> : null}
            <button
              type="submit"
              disabled={registerLoading}
              className="w-full rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
              title="Envoyer la demande de création de compte"
            >
              {registerLoading ? "Envoi..." : "Envoyer ma demande"}
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => {
            setMode("login");
            setRegisterError(null);
            setRegisterLoading(false);
          }}
          className="text-sm text-slate-400 hover:text-slate-200"
        >
          Retour à la connexion
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
      {idleLogoutMessage ? (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {idleLogoutMessage}
        </p>
      ) : null}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-slate-200" htmlFor="username">
          Email ou identifiant
        </label>
        <AppTextInput
          id="username"
          type="text"
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
          title="Entrez votre email ou identifiant"
          inputMode="text"
          autoComplete="username"
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
      <button
        type="button"
        onClick={() => {
          setMode("register");
          clearError();
        }}
        className="w-full text-sm text-slate-400 hover:text-slate-200"
      >
        Créer un compte
      </button>
    </form>
  );
}
