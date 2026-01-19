import { FormEvent, useEffect, useMemo, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";
import { useAuth } from "./useAuth";
import { AppTextInput } from "components/AppTextInput";
import { api } from "../../lib/api";
import { useLocation } from "react-router-dom";

export function Login() {
  const { login, verifyTwoFactor, confirmTotpEnrollment, clearError, isLoading, error } = useAuth();
  const location = useLocation();
  const [remember, setRemember] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.localStorage.getItem("gsp_login_remember") === "true";
  });
  const [identifier, setIdentifier] = useState(() => {
    if (typeof window === "undefined") {
      return "";
    }
    if (window.localStorage.getItem("gsp_login_remember") !== "true") {
      return "";
    }
    return window.localStorage.getItem("gsp_login_identifier") ?? "";
  });
  const [password, setPassword] = useState("");
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpauthUri, setOtpauthUri] = useState<string | null>(null);
  const [secretMasked, setSecretMasked] = useState<string | null>(null);
  const [secretPlain, setSecretPlain] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [step, setStep] = useState<"credentials" | "totp" | "enroll">("credentials");
  const [mode, setMode] = useState<
    "login" | "register" | "register-success" | "reset-request" | "reset-confirm"
  >("login");
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerPassword, setRegisterPassword] = useState("");
  const [registerDisplayName, setRegisterDisplayName] = useState("");
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registerLoading, setRegisterLoading] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState("");
  const [resetMessage, setResetMessage] = useState<string | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetLoading, setResetLoading] = useState(false);
  const [devResetToken, setDevResetToken] = useState<string | null>(null);

  useEffect(() => {
    setPassword("");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (!remember) {
      window.localStorage.removeItem("gsp_login_remember");
      window.localStorage.removeItem("gsp_login_identifier");
      return;
    }
    window.localStorage.setItem("gsp_login_remember", "true");
    window.localStorage.setItem("gsp_login_identifier", identifier);
  }, [identifier, remember]);

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

  const handleResetRequest = async (event: FormEvent) => {
    event.preventDefault();
    setResetError(null);
    setResetMessage(null);
    setResetLoading(true);
    setDevResetToken(null);
    try {
      const response = await api.post("/auth/password-reset/request", { email: resetEmail });
      const token = response.data?.dev_reset_token ?? null;
      setDevResetToken(token);
      setResetMessage("Si un compte existe, vous recevrez des instructions.");
      setMode("reset-confirm");
      if (token) {
        setResetToken(token);
      }
    } catch (err) {
      const detail =
        typeof err === "object" && err && "response" in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      setResetError(detail ?? "Impossible de traiter la demande.");
    } finally {
      setResetLoading(false);
    }
  };

  const handleResetConfirm = async (event: FormEvent) => {
    event.preventDefault();
    setResetError(null);
    setResetMessage(null);
    if (resetPassword !== resetPasswordConfirm) {
      setResetError("Les mots de passe ne correspondent pas.");
      return;
    }
    setResetLoading(true);
    try {
      await api.post("/auth/password-reset/confirm", {
        token: resetToken,
        new_password: resetPassword
      });
      setResetMessage("Votre mot de passe a été mis à jour.");
      setMode("login");
      setResetToken("");
      setResetPassword("");
      setResetPasswordConfirm("");
      setDevResetToken(null);
    } catch (err) {
      const detail =
        typeof err === "object" && err && "response" in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      setResetError(detail ?? "Impossible de réinitialiser le mot de passe.");
    } finally {
      setResetLoading(false);
    }
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

  if (mode === "reset-request") {
    return (
      <form className="space-y-6" onSubmit={handleResetRequest}>
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold">Mot de passe oublié</h1>
          <p className="text-sm text-slate-400">
            Entrez votre email pour recevoir les instructions de réinitialisation.
          </p>
        </header>
        <div className="space-y-2">
          <label className="block text-sm font-medium text-slate-200" htmlFor="resetEmail">
            Email
          </label>
          <AppTextInput
            id="resetEmail"
            type="email"
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={resetEmail}
            onChange={(event) => setResetEmail(event.target.value)}
            title="Entrez votre email"
            autoComplete="email"
          />
        </div>
        {resetMessage ? (
          <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            {resetMessage}
          </p>
        ) : null}
        {resetError ? <p className="text-sm text-red-400">{resetError}</p> : null}
        <button
          type="submit"
          disabled={resetLoading}
          className="w-full rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          title="Demander une réinitialisation"
        >
          {resetLoading ? "Envoi..." : "Envoyer"}
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("login");
            setResetError(null);
            setResetMessage(null);
            setDevResetToken(null);
          }}
          className="text-sm text-slate-400 hover:text-slate-200"
        >
          Retour à la connexion
        </button>
      </form>
    );
  }

  if (mode === "reset-confirm") {
    return (
      <form className="space-y-6" onSubmit={handleResetConfirm}>
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold">Réinitialiser le mot de passe</h1>
          <p className="text-sm text-slate-400">
            Saisissez le code de réinitialisation et votre nouveau mot de passe.
          </p>
        </header>
        {resetMessage ? (
          <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            {resetMessage}
          </p>
        ) : null}
        {devResetToken ? (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
            <p className="font-semibold text-amber-100">DEV uniquement</p>
            <p className="break-all">Code de réinitialisation : {devResetToken}</p>
          </div>
        ) : null}
        <div className="space-y-2">
          <label className="block text-sm font-medium text-slate-200" htmlFor="resetToken">
            Code de réinitialisation
          </label>
          <AppTextInput
            id="resetToken"
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={resetToken}
            onChange={(event) => setResetToken(event.target.value)}
            title="Entrez le code de réinitialisation"
            autoComplete="one-time-code"
          />
        </div>
        <div className="space-y-2">
          <label className="block text-sm font-medium text-slate-200" htmlFor="resetPassword">
            Nouveau mot de passe
          </label>
          <AppTextInput
            id="resetPassword"
            type="password"
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={resetPassword}
            onChange={(event) => setResetPassword(event.target.value)}
            title="Nouveau mot de passe"
            autoComplete="new-password"
          />
        </div>
        <div className="space-y-2">
          <label
            className="block text-sm font-medium text-slate-200"
            htmlFor="resetPasswordConfirm"
          >
            Confirmer le mot de passe
          </label>
          <AppTextInput
            id="resetPasswordConfirm"
            type="password"
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={resetPasswordConfirm}
            onChange={(event) => setResetPasswordConfirm(event.target.value)}
            title="Confirmez le mot de passe"
            autoComplete="new-password"
          />
        </div>
        {resetError ? <p className="text-sm text-red-400">{resetError}</p> : null}
        <button
          type="submit"
          disabled={resetLoading}
          className="w-full rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          title="Valider la réinitialisation"
        >
          {resetLoading ? "Mise à jour..." : "Réinitialiser"}
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("login");
            setResetError(null);
            setResetMessage(null);
            setDevResetToken(null);
          }}
          className="text-sm text-slate-400 hover:text-slate-200"
        >
          Retour à la connexion
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
          setMode("reset-request");
          setResetError(null);
          setResetMessage(null);
          setDevResetToken(null);
          clearError();
        }}
        className="w-full text-sm text-slate-400 hover:text-slate-200"
      >
        Mot de passe oublié ?
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
