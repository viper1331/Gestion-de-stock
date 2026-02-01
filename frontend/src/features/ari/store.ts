import { createWithEqualityFn } from "zustand/traditional";
import { shallow } from "zustand/shallow";

import type { AriCertification, AriCollaboratorStats, AriSession, AriSettings } from "../../types/ari";
import {
  createAriSession,
  decideAriCertification,
  getAriCertification,
  getAriCollaboratorStats,
  getAriSettings,
  listAriPending,
  listAriSessions,
  updateAriSettings
} from "../../api/ari";

interface AriState {
  ariSite: string | null;
  selectedCollaboratorId: number | null;
  settings: AriSettings | null;
  sessions: AriSession[];
  stats: AriCollaboratorStats | null;
  certification: AriCertification | null;
  pendingCertifications: AriCertification[];
  isFetchingSettings: boolean;
  isFetchingSessions: boolean;
  isFetchingStats: boolean;
  isFetchingCertification: boolean;
  isFetchingPending: boolean;
  setAriSite: (site: string | null) => void;
  setSelectedCollaboratorId: (id: number | null) => void;
  loadSettings: (site?: string) => Promise<AriSettings | null>;
  saveSettings: (payload: AriSettings, site?: string) => Promise<AriSettings | null>;
  loadSessions: (collaboratorId: number, site?: string) => Promise<AriSession[]>;
  loadStats: (collaboratorId: number, site?: string) => Promise<AriCollaboratorStats | null>;
  loadCertification: (collaboratorId: number, site?: string) => Promise<AriCertification | null>;
  loadPending: (site?: string) => Promise<AriCertification[]>;
  createSession: (
    payload: {
      collaborator_id: number;
      performed_at: string;
      course_name: string;
      duration_seconds: number;
      start_pressure_bar: number;
      end_pressure_bar: number;
      cylinder_capacity_l: number;
      stress_level: number;
      rpe?: number | null;
      physio_notes?: string | null;
      observations?: string | null;
    },
    site?: string
  ) => Promise<AriSession>;
  decideCertification: (
    payload: { collaborator_id: number; status: "APPROVED" | "REJECTED" | "CONDITIONAL"; comment?: string | null },
    site?: string
  ) => Promise<AriCertification>;
}

export const useAriStore = createWithEqualityFn<AriState>()(
  (set, get) => ({
    ariSite: null,
    selectedCollaboratorId: null,
    settings: null,
    sessions: [],
    stats: null,
    certification: null,
    pendingCertifications: [],
    isFetchingSettings: false,
    isFetchingSessions: false,
    isFetchingStats: false,
    isFetchingCertification: false,
    isFetchingPending: false,
    setAriSite: (site) => set({ ariSite: site }),
    setSelectedCollaboratorId: (id) => set({ selectedCollaboratorId: id }),
    loadSettings: async (site) => {
      set({ isFetchingSettings: true });
      try {
        const settings = await getAriSettings(site);
        set({ settings });
        return settings;
      } finally {
        set({ isFetchingSettings: false });
      }
    },
    saveSettings: async (payload, site) => {
      set({ isFetchingSettings: true });
      try {
        const settings = await updateAriSettings(payload, site);
        set({ settings });
        return settings;
      } finally {
        set({ isFetchingSettings: false });
      }
    },
    loadSessions: async (collaboratorId, site) => {
      set({ isFetchingSessions: true });
      try {
        const sessions = await listAriSessions(collaboratorId, site);
        set({ sessions });
        return sessions;
      } finally {
        set({ isFetchingSessions: false });
      }
    },
    loadStats: async (collaboratorId, site) => {
      set({ isFetchingStats: true });
      try {
        const stats = await getAriCollaboratorStats(collaboratorId, site);
        set({ stats });
        return stats;
      } finally {
        set({ isFetchingStats: false });
      }
    },
    loadCertification: async (collaboratorId, site) => {
      set({ isFetchingCertification: true });
      try {
        const certification = await getAriCertification(collaboratorId, site);
        set({ certification });
        return certification;
      } finally {
        set({ isFetchingCertification: false });
      }
    },
    loadPending: async (site) => {
      set({ isFetchingPending: true });
      try {
        const pending = await listAriPending(site);
        set({ pendingCertifications: pending });
        return pending;
      } finally {
        set({ isFetchingPending: false });
      }
    },
    createSession: async (payload, site) => {
      const session = await createAriSession(payload, site);
      const current = get().sessions;
      set({ sessions: [session, ...current] });
      return session;
    },
    decideCertification: async (payload, site) => {
      const decision = await decideAriCertification(payload, site);
      set({ certification: decision });
      return decision;
    }
  }),
  shallow
);
