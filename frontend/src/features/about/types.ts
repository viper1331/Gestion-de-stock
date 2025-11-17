export interface AboutVersionInfo {
  label: string;
  branch: string;
  last_update: string | null;
  source_commit: string | null;
  pending_update: boolean;
}

export interface AboutInfo {
  summary: string;
  license: string;
  version: AboutVersionInfo;
}
