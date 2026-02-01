import type { AriSession } from "../../../types/ari";
import { getAirPerMinute, getDurationMinutes } from "./ariSessionDisplay";

export type AriSessionStatus = "PENDING" | "CERTIFIED" | "REJECTED" | "COMPLETED" | "DRAFT";

export type AriSessionsFiltersState = {
  query: string;
  dateFrom: string;
  dateTo: string;
  collaboratorId: string;
  course: string;
  durationMin: string;
  durationMax: string;
  airMin: string;
  airMax: string;
  status: string;
};

export type AriSessionsSortKey = "date" | "collaborator" | "course" | "duration" | "air" | "status";

export type AriSessionsSort = {
  key: AriSessionsSortKey;
  direction: "asc" | "desc";
} | null;

export const ariSessionStatusLabels: Record<AriSessionStatus, string> = {
  PENDING: "En attente",
  CERTIFIED: "Validée",
  REJECTED: "Refusée",
  COMPLETED: "Terminée",
  DRAFT: "Brouillon"
};

export const createEmptyAriSessionsFilters = (): AriSessionsFiltersState => ({
  query: "",
  dateFrom: "",
  dateTo: "",
  collaboratorId: "",
  course: "",
  durationMin: "",
  durationMax: "",
  airMin: "",
  airMax: "",
  status: ""
});

export const getSessionStatus = (
  session: AriSession,
  pendingByCollaborator: Set<number>
): AriSessionStatus => {
  if (pendingByCollaborator.has(session.collaborator_id)) {
    return "PENDING";
  }
  switch (session.status) {
    case "CERTIFIED":
      return "CERTIFIED";
    case "REJECTED":
      return "REJECTED";
    case "COMPLETED":
      return "COMPLETED";
    case "DRAFT":
    default:
      return "DRAFT";
  }
};

export const getCollaboratorName = (
  session: AriSession,
  collaboratorMap: Map<number, { full_name: string }>
): string => collaboratorMap.get(session.collaborator_id)?.full_name ?? `#${session.collaborator_id}`;

const parseNumber = (value: string): number | null => {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const parseDateStart = (value: string): Date | null => {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  date.setHours(0, 0, 0, 0);
  return date;
};

const parseDateEnd = (value: string): Date | null => {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  date.setHours(23, 59, 59, 999);
  return date;
};

export const applyAriSessionsFilters = (
  sessions: AriSession[],
  filters: AriSessionsFiltersState,
  collaboratorMap: Map<number, { full_name: string }>,
  pendingByCollaborator: Set<number>
): AriSession[] => {
  if (!sessions.length) {
    return sessions;
  }
  const dateFrom = parseDateStart(filters.dateFrom);
  const dateTo = parseDateEnd(filters.dateTo);
  const query = filters.query.trim().toLowerCase();
  const collaboratorId = parseNumber(filters.collaboratorId);
  const durationMin = parseNumber(filters.durationMin);
  const durationMax = parseNumber(filters.durationMax);
  const airMin = parseNumber(filters.airMin);
  const airMax = parseNumber(filters.airMax);
  const statusFilter = filters.status;

  return sessions.filter((session) => {
    const performedAt = new Date(session.performed_at);
    if (dateFrom && performedAt < dateFrom) {
      return false;
    }
    if (dateTo && performedAt > dateTo) {
      return false;
    }
    if (collaboratorId !== null && session.collaborator_id !== collaboratorId) {
      return false;
    }
    if (filters.course && session.course_name !== filters.course) {
      return false;
    }
    if (durationMin !== null || durationMax !== null) {
      const durationMinutes = getDurationMinutes(session);
      if (durationMinutes === null) {
        return false;
      }
      if (durationMin !== null && durationMinutes < durationMin) {
        return false;
      }
      if (durationMax !== null && durationMinutes > durationMax) {
        return false;
      }
    }
    if (airMin !== null || airMax !== null) {
      const airPerMinute = getAirPerMinute(session);
      if (airPerMinute === null) {
        return false;
      }
      if (airMin !== null && airPerMinute < airMin) {
        return false;
      }
      if (airMax !== null && airPerMinute > airMax) {
        return false;
      }
    }
    if (statusFilter) {
      const status = getSessionStatus(session, pendingByCollaborator);
      if (status !== statusFilter) {
        return false;
      }
    }
    if (query) {
      const collaboratorName = getCollaboratorName(session, collaboratorMap).toLowerCase();
      const courseName = (session.course_name || "").toLowerCase();
      const statusLabel = ariSessionStatusLabels[getSessionStatus(session, pendingByCollaborator)].toLowerCase();
      if (
        !collaboratorName.includes(query) &&
        !courseName.includes(query) &&
        !statusLabel.includes(query)
      ) {
        return false;
      }
    }
    return true;
  });
};

const compareNullable = (
  valueA: number | string | null,
  valueB: number | string | null,
  direction: "asc" | "desc"
): number => {
  if (valueA === null && valueB === null) {
    return 0;
  }
  if (valueA === null) {
    return 1;
  }
  if (valueB === null) {
    return -1;
  }
  const multiplier = direction === "asc" ? 1 : -1;
  if (typeof valueA === "number" && typeof valueB === "number") {
    return (valueA - valueB) * multiplier;
  }
  return valueA.toString().localeCompare(valueB.toString(), "fr", { sensitivity: "base" }) * multiplier;
};

export const sortAriSessions = (
  sessions: AriSession[],
  sort: AriSessionsSort,
  collaboratorMap: Map<number, { full_name: string }>,
  pendingByCollaborator: Set<number>
): AriSession[] => {
  if (!sort) {
    return sessions;
  }
  const decorated = sessions.map((session, index) => ({
    session,
    index
  }));
  decorated.sort((first, second) => {
    let comparison = 0;
    switch (sort.key) {
      case "date":
        comparison = compareNullable(
          new Date(first.session.performed_at).getTime(),
          new Date(second.session.performed_at).getTime(),
          sort.direction
        );
        break;
      case "collaborator":
        comparison = compareNullable(
          getCollaboratorName(first.session, collaboratorMap),
          getCollaboratorName(second.session, collaboratorMap),
          sort.direction
        );
        break;
      case "course":
        comparison = compareNullable(
          first.session.course_name || "",
          second.session.course_name || "",
          sort.direction
        );
        break;
      case "duration":
        comparison = compareNullable(
          getDurationMinutes(first.session),
          getDurationMinutes(second.session),
          sort.direction
        );
        break;
      case "air":
        comparison = compareNullable(
          getAirPerMinute(first.session),
          getAirPerMinute(second.session),
          sort.direction
        );
        break;
      case "status":
        comparison = compareNullable(
          ariSessionStatusLabels[getSessionStatus(first.session, pendingByCollaborator)],
          ariSessionStatusLabels[getSessionStatus(second.session, pendingByCollaborator)],
          sort.direction
        );
        break;
      default:
        comparison = 0;
    }
    if (comparison !== 0) {
      return comparison;
    }
    return first.index - second.index;
  });
  return decorated.map((entry) => entry.session);
};
