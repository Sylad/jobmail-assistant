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
  result_json_url: string;
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
  result_json_url: string;
  cancel_url: string;
}

export interface ProgressStat {
  label: string;
  value: string | number;
}

export interface ProgressPanelState {
  visible: boolean;
  title: string;
  elapsedSeconds: number;
  active: boolean;
  cancelling: boolean;
  progressValue: number | null;
  stats: ProgressStat[];
}

export interface RegexRule {
  sender_regex: string;
  subject_regex: string;
}

export interface CleanerInitialState {
  source: CleanerSource;
  min_age_days: number;
  max_mails: number;
  scan_offset: number;
  delete_folder: string;
  mbox_patterns: string[];
  regex_rules: RegexRule[];
  imap_enabled: boolean;
}

export type CleanerSource = "thunderbird" | "regex" | "parsed_jobs" | "duplicates" | "imap";

export interface CleanerCandidatePayload {
  uid: string;
  received_at: string;
  received_date: string;
  sender: string;
  subject: string;
  reason: string;
  source: string;
  mailbox: string;
  source_path: string;
  offer_id: number;
  status: string;
  score: number;
  company: string;
  duplicate_of: string;
  can_move: boolean;
}

export interface CleanerTopSenderPayload {
  sender: string;
  count: number;
}

export interface CleanerReportPayload {
  scanned_count: number;
  candidate_count: number;
  skipped_too_recent: number;
  skipped_safety: number;
  skipped_no_match: number;
  top_senders: CleanerTopSenderPayload[];
  candidates: CleanerCandidatePayload[];
}

export interface CleanerScanResultPayload {
  job_id: string;
  source: CleanerSource;
  min_age_days: number;
  max_mails: number;
  scan_offset: number;
  regex_job_id: string;
  regex_rules: RegexRule[];
  delete_folder: string;
  report: CleanerReportPayload;
}
