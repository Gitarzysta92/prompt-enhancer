/**
 * Stable public façade for the team control-plane contract.
 *
 * Keep consumers on this path while schema, validation, and statistics remain
 * independently testable, downward-only layers.
 */
export * from "./teamControlPlaneSchema";
export * from "./teamControlPlaneIdentity";
export * from "./teamControlPlaneValidation";
export * from "./teamControlPlaneStatistics";
export * from "./teamMemberVisibilityValidation";
