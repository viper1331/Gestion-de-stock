import type { UserProfile } from "../auth/authStore";

export const canCertifyARI = (user: UserProfile | null | undefined) =>
  user?.role === "admin" || user?.role === "certificateur";
