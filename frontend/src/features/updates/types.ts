export interface PullRequestInfo {
  number: number;
  title: string;
  url: string;
  merged_at: string | null;
  head_sha: string;
}

export interface UpdateStatus {
  repository: string;
  branch: string;
  current_commit: string | null;
  latest_pull_request: PullRequestInfo | null;
  last_deployed_pull: number | null;
  last_deployed_sha: string | null;
  last_deployed_at: string | null;
  pending_update: boolean;
}

export interface UpdateAvailability {
  pending_update: boolean;
  branch: string | null;
}

export interface UpdateApplyResponse {
  updated: boolean;
  status: UpdateStatus;
}
