export type CleanerJobStatus = "running" | "done" | "cancelled" | "error";

export interface CleanerScanJobPayload {
  id: string;
  status: CleanerJobStatus;
  scanned_count: number;
  candidate_count: number;
  skipped_too_recent: number;
  skipped_safety: number;
  skipped_no_match: number;
  current_mailbox: string;
  elapsed_seconds: number;
  error: string;
  result_url: string;
  cancel_url: string;
}

export interface CleanerMoveJobPayload {
  id: string;
  status: CleanerJobStatus;
  moved_count: number;
  total_count: number;
  elapsed_seconds: number;
  error: string;
  result_url: string;
  cancel_url: string;
}
