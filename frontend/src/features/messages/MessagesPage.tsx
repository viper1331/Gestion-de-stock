import { FormEvent, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";
import { EditablePageLayout, type EditableLayoutSet, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

const CATEGORY_OPTIONS = ["Info", "Alerte", "Maintenance", "Divers"] as const;

type UserRole = "admin" | "user";

interface MessageRecipient {
  username: string;
  role: UserRole;
}

interface MessageInboxEntry {
  id: number;
  category: string;
  content: string;
  created_at: string;
  sender_username: string;
  sender_role: UserRole;
  is_read: boolean;
  is_archived: boolean;
}

interface SentMessageRecipient {
  username: string;
  read_at: string | null;
}

interface SentMessageEntry {
  id: number;
  category: string;
  content: string;
  created_at: string;
  recipients_total: number;
  recipients_read: number;
  recipients: SentMessageRecipient[] | null;
}

interface SendMessagePayload {
  category: string;
  content: string;
  recipients: string[];
  broadcast: boolean;
}

export function MessagesPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [category, setCategory] = useState<string>(CATEGORY_OPTIONS[0]);
  const [content, setContent] = useState<string>("");
  const [recipients, setRecipients] = useState<string[]>([]);
  const [broadcast, setBroadcast] = useState<boolean>(false);
  const [includeArchived, setIncludeArchived] = useState<boolean>(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"inbox" | "sent">("inbox");
  const contentRef = useRef<HTMLTextAreaElement | null>(null);

  const { data: availableRecipients = [], isFetching: isFetchingRecipients } = useQuery({
    queryKey: ["messages", "recipients"],
    queryFn: async () => {
      const response = await api.get<MessageRecipient[]>("/messages/recipients");
      return response.data;
    },
    enabled: Boolean(user)
  });

  const {
    data: inboxMessages = [],
    isFetching: isFetchingInbox
  } = useQuery({
    queryKey: ["messages", "inbox", includeArchived],
    queryFn: async () => {
      const response = await api.get<MessageInboxEntry[]>("/messages/inbox", {
        params: {
          limit: 50,
          include_archived: includeArchived
        }
      });
      return response.data;
    },
    enabled: Boolean(user)
  });

  const {
    data: sentMessages = [],
    isFetching: isFetchingSent
  } = useQuery({
    queryKey: ["messages", "sent"],
    queryFn: async () => {
      const response = await api.get<SentMessageEntry[]>("/messages/sent", {
        params: {
          limit: 50
        }
      });
      return response.data;
    },
    enabled: Boolean(user) && activeTab === "sent",
    refetchInterval: activeTab === "sent" ? 12000 : false
  });

  const clearFeedbackLater = () => {
    window.setTimeout(() => {
      setMessage(null);
      setError(null);
    }, 4000);
  };

  const sendMessage = useMutation({
    mutationFn: async (payload: SendMessagePayload) => {
      const response = await api.post("/messages/send", payload);
      return response.data as { message_id: number; recipients_count: number };
    },
    onSuccess: async () => {
      setMessage("Message envoyé.");
      setError(null);
      setContent("");
      setRecipients([]);
      setBroadcast(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["messages", "inbox"] }),
        queryClient.invalidateQueries({ queryKey: ["messages", "sent"] })
      ]);
      clearFeedbackLater();
      contentRef.current?.focus();
    },
    onError: (err) => {
      let errorMessage = "Impossible d'envoyer le message.";
      if (err instanceof AxiosError) {
        const status = err.response?.status;
        const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
        if (status === 429 && detail) {
          errorMessage = detail;
        }
      }
      setError(errorMessage);
      clearFeedbackLater();
    }
  });

  const markRead = useMutation({
    mutationFn: async (messageId: number) => {
      await api.post(`/messages/${messageId}/read`);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["messages", "inbox"] }),
        queryClient.invalidateQueries({ queryKey: ["messages", "sent"] })
      ]);
    }
  });

  const archiveMessage = useMutation({
    mutationFn: async (messageId: number) => {
      await api.post(`/messages/${messageId}/archive`);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["messages", "inbox"] });
    }
  });

  const selectedRecipients = useMemo(() => new Set(recipients), [recipients]);
  const trimmedContent = content.trim();
  const isCategoryValid = category.trim().length > 0;
  const hasRecipients = recipients.length > 0;
  const canSend =
    Boolean(trimmedContent) &&
    isCategoryValid &&
    (broadcast || hasRecipients) &&
    !sendMessage.isPending;
  const sendScopeLabel = broadcast
    ? "Envoi à tous les utilisateurs"
    : `Envoi à ${recipients.length} destinataire(s)`;

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!trimmedContent) {
      setError("Veuillez saisir un message.");
      clearFeedbackLater();
      return;
    }

    if (!isCategoryValid) {
      setError("Veuillez sélectionner une catégorie.");
      clearFeedbackLater();
      return;
    }

    if (!broadcast && recipients.length === 0) {
      setError("Veuillez sélectionner au moins un destinataire.");
      clearFeedbackLater();
      return;
    }

    setMessage(null);
    setError(null);
    await sendMessage.mutateAsync({
      category,
      content: trimmedContent,
      recipients,
      broadcast
    });
  };

  const toggleRecipient = (username: string) => {
    setRecipients((prev) => {
      if (prev.includes(username)) {
        return prev.filter((value) => value !== username);
      }
      return [...prev, username];
    });
  };

  const inboxIsEmpty = inboxMessages.length === 0 && !isFetchingInbox;
  const sentIsEmpty = sentMessages.length === 0 && !isFetchingSent;

  const pageContent = (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold text-white">Messagerie interne</h2>
        <p className="text-sm text-slate-400">
          Envoyez des messages aux autres utilisateurs et consultez votre boîte de réception.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4 shadow-sm">
          <h3 className="text-base font-semibold text-white">Composer / Envoyer</h3>
          <form className="mt-4 space-y-4" onSubmit={handleSend}>
            <label className="flex flex-col gap-2 text-sm text-slate-200">
              Catégorie
              <select
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-2 text-sm text-slate-200">
              Message
              <AppTextArea
                className="min-h-[120px] rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                value={content}
                onChange={(event) => setContent(event.target.value)}
                placeholder="Écrivez votre message..."
                ref={contentRef}
              />
            </label>

            <label className="flex items-center gap-2 text-sm text-slate-200">
              <AppTextInput
                type="checkbox"
                className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                checked={broadcast}
                onChange={(event) => setBroadcast(event.target.checked)}
              />
              Envoyer à tous
            </label>

            <div className="space-y-2">
              <p className="text-sm font-medium text-slate-200">Destinataires</p>
              {isFetchingRecipients ? (
                <p className="text-xs text-slate-500">Chargement des utilisateurs...</p>
              ) : availableRecipients.length === 0 ? (
                <p className="text-xs text-slate-500">Aucun destinataire disponible.</p>
              ) : (
                <div className="max-h-48 space-y-2 overflow-y-auto rounded-md border border-slate-800 bg-slate-950/60 p-3">
                  {availableRecipients.map((recipient) => (
                    <label key={recipient.username} className="flex items-center gap-2 text-xs text-slate-200">
                      <AppTextInput
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                        checked={selectedRecipients.has(recipient.username)}
                        onChange={() => toggleRecipient(recipient.username)}
                        disabled={broadcast}
                      />
                      <span className="font-semibold text-white">{recipient.username}</span>
                      <span className={recipient.role === "admin" ? "text-red-400" : "text-indigo-300"}>
                        {recipient.role}
                      </span>
                    </label>
                  ))}
                </div>
              )}
              {broadcast ? (
                <p className="text-xs text-slate-500">La diffusion ignore la sélection manuelle.</p>
              ) : null}
            </div>

            {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
            {error ? <p className="text-sm text-red-300">{error}</p> : null}
            <p className="text-xs text-slate-400">{sendScopeLabel}</p>

            <button
              type="submit"
              className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={!canSend}
            >
              {sendMessage.isPending ? "Envoi en cours..." : "Envoyer"}
            </button>
          </form>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4 shadow-sm">
          <header className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-base font-semibold text-white">Messagerie</h3>
              <p className="text-xs text-slate-400">Vos 50 derniers messages.</p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                onClick={() => setActiveTab("inbox")}
                className={`rounded-md border px-3 py-1 font-semibold ${
                  activeTab === "inbox"
                    ? "border-indigo-400 bg-indigo-500/20 text-white"
                    : "border-slate-700 text-slate-300 hover:border-indigo-400 hover:text-white"
                }`}
              >
                Réception
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("sent")}
                className={`rounded-md border px-3 py-1 font-semibold ${
                  activeTab === "sent"
                    ? "border-indigo-400 bg-indigo-500/20 text-white"
                    : "border-slate-700 text-slate-300 hover:border-indigo-400 hover:text-white"
                }`}
              >
                Envoyés
              </button>
            </div>
          </header>

          {activeTab === "inbox" ? (
            <>
              <div className="mt-3 flex items-center justify-end">
                <label className="flex items-center gap-2 text-xs text-slate-300">
                  <AppTextInput
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                    checked={includeArchived}
                    onChange={(event) => setIncludeArchived(event.target.checked)}
                  />
                  Afficher archives
                </label>
              </div>
              {isFetchingInbox ? (
                <p className="mt-4 text-sm text-slate-400">Chargement des messages...</p>
              ) : inboxIsEmpty ? (
                <p className="mt-4 text-sm text-slate-400">Aucun message pour le moment.</p>
              ) : (
                <div className="mt-4 space-y-3">
                  {inboxMessages.map((entry) => (
                    <article
                      key={entry.id}
                      className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 shadow-sm"
                    >
                      <header className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${
                              entry.sender_role === "admin"
                                ? "bg-red-500/20 text-red-200"
                                : "bg-indigo-500/20 text-indigo-200"
                            }`}
                          >
                            {entry.sender_username}
                          </span>
                          <span className="rounded border border-slate-700 px-2 py-0.5 text-[10px] uppercase text-slate-300">
                            {entry.category}
                          </span>
                          {!entry.is_read ? (
                            <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-200">
                              Non lu
                            </span>
                          ) : null}
                          {entry.is_archived ? (
                            <span className="rounded border border-slate-600 px-2 py-0.5 text-[10px] text-slate-300">
                              Archivé
                            </span>
                          ) : null}
                        </div>
                        <span className="text-xs text-slate-500">{formatDateTime(entry.created_at)}</span>
                      </header>
                      <p className="mt-3 text-sm text-slate-200">{entry.content}</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:border-indigo-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                          onClick={() => markRead.mutate(entry.id)}
                          disabled={entry.is_read || markRead.isPending}
                        >
                          Marquer comme lu
                        </button>
                        <button
                          type="button"
                          className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:border-red-400 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-60"
                          onClick={() => archiveMessage.mutate(entry.id)}
                          disabled={entry.is_archived || archiveMessage.isPending}
                        >
                          Archiver
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          ) : isFetchingSent ? (
            <p className="mt-4 text-sm text-slate-400">Chargement des messages...</p>
          ) : sentIsEmpty ? (
            <p className="mt-4 text-sm text-slate-400">Aucun message envoyé pour le moment.</p>
          ) : (
            <div className="mt-4 space-y-3">
              {sentMessages.map((entry) => (
                <article
                  key={entry.id}
                  className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 shadow-sm"
                >
                  <header className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded border border-slate-700 px-2 py-0.5 text-[10px] uppercase text-slate-300">
                        {entry.category}
                      </span>
                      <span className="rounded border border-emerald-400/40 bg-emerald-400/10 px-2 py-0.5 text-[10px] text-emerald-200">
                        Lu {entry.recipients_read}/{entry.recipients_total}
                      </span>
                    </div>
                    <span className="text-xs text-slate-500">{formatDateTime(entry.created_at)}</span>
                  </header>
                  <p className="mt-3 text-sm text-slate-200">{entry.content}</p>
                  {entry.recipients?.length ? (
                    <details className="mt-3 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs text-slate-300">
                      <summary className="cursor-pointer text-xs font-semibold text-slate-200">
                        Détails des destinataires
                      </summary>
                      <ul className="mt-2 space-y-1">
                        {entry.recipients.map((recipient) => (
                          <li key={`${entry.id}-${recipient.username}`} className="flex flex-wrap gap-2">
                            <span className="font-semibold text-white">{recipient.username}</span>
                            <span className="text-slate-400">
                              {recipient.read_at ? `Lu le ${formatDateTime(recipient.read_at)}` : "Non lu"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </article>
              ))}
            </div>
          )}
          <div className="mt-4 text-right">
            <Link
              to="/"
              className="text-xs text-slate-500 hover:text-indigo-200"
            >
              Retour à l'accueil
            </Link>
          </div>
        </section>
      </div>
    </section>
  );

  const defaultLayouts = useMemo<EditableLayoutSet>(
    () => ({
      lg: [{ i: "messages-main", x: 0, y: 0, w: 12, h: 24 }],
      md: [{ i: "messages-main", x: 0, y: 0, w: 6, h: 24 }],
      sm: [{ i: "messages-main", x: 0, y: 0, w: 1, h: 24 }],
      xs: [{ i: "messages-main", x: 0, y: 0, w: 1, h: 24 }]
    }),
    []
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "messages-main",
      title: "Messagerie",
      required: true,
      containerClassName: "rounded-none border-0 bg-transparent p-0",
      render: () => (
        <EditableBlock id="messages-main">
          {pageContent}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout
      pageKey="module:messages"
      blocks={blocks}
      defaultLayouts={defaultLayouts}
      className="space-y-6"
    />
  );
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}
