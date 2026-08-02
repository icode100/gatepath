import { FOUNDATION_LEARNING_TOPICS } from "./content/foundations";
import { SYSTEMS_LEARNING_TOPICS } from "./content/systems";
import type { LearningTopic } from "./types";
import { validateLearningTopics } from "./validate";

export { LEARNING_REFERENCES } from "./sources";
export type {
  LearningCheckpoint,
  LearningConcept,
  LearningFormula,
  LearningReference,
  LearningTopic,
} from "./types";

export const LEARNING_TOPICS: LearningTopic[] = [
  ...FOUNDATION_LEARNING_TOPICS,
  ...SYSTEMS_LEARNING_TOPICS,
];

validateLearningTopics(LEARNING_TOPICS);

export const LEARNING_TOPIC_BY_KEY = new Map(
  LEARNING_TOPICS.map((topic) => [
    `${topic.subjectId}:${topic.topicId}`,
    topic,
  ]),
);
