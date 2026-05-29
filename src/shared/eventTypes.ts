export const missionEventTypes = [
  "MissionCreated",
  "MissionCommandReceived",
  "MissionStateChanged",
  "MissionMemoryRecorded",
  "FeedbackSignalReceived",
  "SpecChangeCreated",
  "SpecChangeUpdated",
  "SpecChangeStateChanged",
  "MissionPlannerRunStarted",
  "WorkflowPlanned",
  "WorkflowTemplateSelected",
  "DAGRunScheduled",
  "DAGRunStarted",
  "DAGRunCompleted",
  "NodeRunStarted",
  "NodeRunCompleted",
  "NodeRunFailed",
  "RunMessageRecorded",
  "ArtifactRecorded",
  "DecisionRecorded",
  "RouteDecided",
  "EvaluationRecorded"
] as const;

export type MissionEventType = (typeof missionEventTypes)[number];
