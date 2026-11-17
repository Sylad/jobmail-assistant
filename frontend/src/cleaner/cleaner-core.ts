// L4 — logique pure du nettoyeur, sans Vue ni DOM : testée par tests/js/cleaner-core.test.mjs
// (Node lit ce fichier en effaçant les types : syntaxe TypeScript effaçable seulement, pas d'enum).

export type PhaseSource = "thunderbird" | "regex" | "parsed_jobs" | "duplicates";
export type PhaseStatus = "idle" | "running" | "done" | "cancelled" | "error";

interface CoreCandidate {
  uid: string;
  can_move: boolean;
}

interface CoreResult {
  source: string;
  report: { scanned_count: number; candidates: CoreCandidate[] };
}

export interface PhaseMove {
  source: PhaseSource;
  uids: string[];
}

export const EMPTY_PARSED_JOBS_MESSAGE = "Aucun mail d'offre déjà extraite dans la base : cette phase n'a rien à proposer.";
export const EMPTY_CANDIDATES_MESSAGE = "Aucun candidat trouvé avec ces critères.";

/** Sélection d'une phase à l'arrivée de son scan : tous les candidats déplaçables. */
export function initialPhaseSelection(result: CoreResult): string[] {
  return result.report.candidates.filter((candidate) => candidate.can_move).map((candidate) => candidate.uid);
}

/** UID envoyés au déplacement, phase par phase dans l'ordre, dédupliqués entre phases. */
export function planPhaseMoves(
  order: readonly PhaseSource[],
  results: Record<PhaseSource, CoreResult | null>,
  selections: Record<PhaseSource, readonly string[]>,
): PhaseMove[] {
  const queued = new Set<string>();
  return order.flatMap((source) => {
    const result = results[source];
    if (!result) return [];
    // Toutes les phases, regex comprise, envoient leur sélection (inclusions / exclusions par
    // expéditeur). Une sélection vide n'est jamais envoyée : pour regex, le serveur lirait une
    // liste vide comme « tout le scan ».
    const uids = selections[source].filter((uid) => {
      if (queued.has(uid)) return false;
      queued.add(uid);
      return true;
    });
    return uids.length ? [{ source, uids }] : [];
  });
}

/** Total annoncé près du bouton Déplacer : exactement ce que planPhaseMoves enverra. */
export function countPlannedMoves(
  order: readonly PhaseSource[],
  results: Record<PhaseSource, CoreResult | null>,
  selections: Record<PhaseSource, readonly string[]>,
): number {
  return planPhaseMoves(order, results, selections).reduce((sum, move) => sum + move.uids.length, 0);
}

/** UID confiés à l'extension Thunderbird (t5) : la même sélection que le déplacement, à plat. */
export function plannedMoveUids(
  order: readonly PhaseSource[],
  results: Record<PhaseSource, CoreResult | null>,
  selections: Record<PhaseSource, readonly string[]>,
): string[] {
  return planPhaseMoves(order, results, selections).flatMap((move) => move.uids);
}

/** Après le scan complet : le panneau, figé sur la dernière phase, se retire quand les quatre
 * phases sont terminées (les cartes de phase portent alors les comptes). */
export function scanPanelVisibleAfterFullScan(
  order: readonly PhaseSource[],
  statuses: Record<PhaseSource, PhaseStatus>,
  visible: boolean,
): boolean {
  return visible && !order.every((source) => statuses[source] === "done");
}

/** Message affiché quand la phase active n'a aucun candidat. */
export function emptyCandidatesMessage(result: CoreResult | null): string {
  if (result?.source === "parsed_jobs" && result.report.scanned_count === 0) return EMPTY_PARSED_JOBS_MESSAGE;
  return EMPTY_CANDIDATES_MESSAGE;
}
