export type LearningConcept = {
  title: string;
  explanation: string;
  keyIdeas: string[];
  examFocus: string;
  example: {
    prompt: string;
    walkthrough: string;
  };
};

export type LearningFormula = {
  label: string;
  expression: string;
  useWhen: string;
  presentation?: "math" | "mixed" | "text" | "code";
};

export type LearningCheckpoint = {
  question: string;
  answer: string;
};

export type LearningTopic = {
  subjectCode: string;
  subjectId: string;
  topicId: string;
  title: string;
  summary: string;
  estimatedMinutes: number;
  prerequisites: string[];
  objectives: string[];
  concepts: LearningConcept[];
  formulae: LearningFormula[];
  checkpoints: LearningCheckpoint[];
};

export type LearningReference = {
  title: string;
  publisher: string;
  url: string;
  note: string;
};
